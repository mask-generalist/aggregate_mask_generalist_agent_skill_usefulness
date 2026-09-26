import os
from typing import Any, Optional
from loguru import logger
import docker

from cuga.backend.cuga_graph.state.agent_state import AgentState
from cuga.backend.cuga_graph.nodes.cuga_lite.executors.base_executor import RemoteExecutor
from cuga.backend.cuga_graph.nodes.cuga_lite.executors.common import CallApiHelper


class DockerExecutor(RemoteExecutor):
    """Handles code execution in Docker/Podman containers."""

    def __init__(self):
        """Initialize Docker client."""
        self.docker_client = self._get_docker_client()

    def _get_docker_client(self):
        """Get Docker/Podman client with automatic socket detection."""
        podman_socket = f"/run/user/{os.getuid()}/podman/podman.sock"
        docker_socket = os.path.expanduser("~/.rd/docker.sock")

        if os.path.exists(podman_socket):
            socket_path = podman_socket
            logger.debug("Using Podman socket")
        elif os.path.exists(docker_socket):
            socket_path = docker_socket
            logger.debug("Using Rancher Desktop Docker socket")
        else:
            socket_path = "/var/run/docker.sock"
            logger.debug("Using default Docker socket")

        return docker.DockerClient(base_url=f"unix://{socket_path}")

    async def execute_for_cuga_lite(
        self,
        wrapped_code: str,
        context_locals: dict[str, Any],
        state: AgentState,
        thread_id: Optional[str] = None,
        apps_list: Optional[list[str]] = None,
    ) -> tuple[str, dict[str, Any]]:
        """Execute code for cuga_lite mode in Docker container.

        Note: This is not yet fully implemented. Docker execution for cuga_lite
        would require serializing context_locals and tools, similar to E2B.

        Args:
            wrapped_code: Wrapped Python code to execute
            context_locals: Dictionary of variables and tools
            state: AgentState instance
            thread_id: Thread ID (unused for Docker)
            apps_list: List of app names for parsing tool names

        Returns:
            Tuple of (execution result, new variables dictionary)
        """
        raise NotImplementedError(
            "Docker execution for cuga_lite mode is not yet implemented. Use local or E2B mode for cuga_lite."
        )

    async def execute_for_code_agent(
        self,
        wrapped_code: str,
        state: AgentState,
        thread_id: Optional[str] = None,
    ) -> str:
        """Execute code for CodeAgent mode in Docker container.

        Args:
            wrapped_code: Wrapped Python code to execute
            state: AgentState instance
            thread_id: Thread ID (unused for Docker)

        Returns:
            Execution result string (stdout)
        """
        from llm_sandbox import SandboxSession

        function_call_url = CallApiHelper.get_function_call_url()
        trajectory_path = CallApiHelper.get_trajectory_path()
        call_api_helper = CallApiHelper.create_remote_call_api_code(function_call_url, trajectory_path)

        variables_code = state.variables_manager.get_variables_formatted() if state.variables_manager else ""

        # Docker needs asyncio.run() wrapper
        complete_code = f"""
{call_api_helper}

{variables_code}

{wrapped_code}

import asyncio
asyncio.run(_async_main())
"""

        try:
            with SandboxSession(
                client=self.docker_client,
                image="python:3.12-slim",
                keep_template=False,
                commit_container=False,
                lang="python",
                verbose=True,
            ) as session:
                result = session.run(complete_code)
                logger.debug(f"Docker execution completed with exit code: {result.exit_code}")

                if result.exit_code != 0:
                    error_msg = result.stderr if result.stderr else "Unknown error"
                    logger.error(f"Docker execution failed: {error_msg}")
                    return error_msg

                return result.stdout
        except Exception as e:
            logger.error(f"Docker execution error: {e}")
            return f"Error during Docker execution: {repr(e)}"
