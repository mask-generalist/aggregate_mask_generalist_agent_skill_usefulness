"""
Main application for running tasks with CugaAgent and MCP integration.

This example demonstrates how to use the CugaAgent with MCP (Model Context Protocol)
to perform tasks on web applications.
"""

import os

os.environ["ENV_FILE"] = os.path.join(os.path.dirname(__file__), ".env")
os.environ["DYNA_CONF_ADVANCED_FEATURES__MODE"] = "api"
os.environ["DYNA_CONF_FEATURES__LOCAL_SANDBOX"] = "true"
import asyncio
from cuga.backend.activity_tracker.tracker import ActivityTracker
from cuga.backend.cuga_graph.utils.controller import AgentRunner as CugaAgent, ExperimentResult as AgentResult
from loguru import logger
from langchain_example_tool import tools as gmail_dummy_tools

# Initialize components
tracker = ActivityTracker()
cuga_agent = None


async def run_task(task: str) -> AgentResult:
    global cuga_agent

    if not cuga_agent:
        cuga_agent = CugaAgent(browser_enabled=False)
        await cuga_agent.initialize_appworld_env()
        tools = gmail_dummy_tools
        for tool in tools:
            tool.metadata = {'server_name': "gmail"}
        tracker.set_tools(tools)
    task_result: AgentResult = await cuga_agent.run_task_generic(eval_mode=False, goal=task)
    return task_result


async def perform_task(task: str) -> str:
    try:
        agent_result: AgentResult = await run_task(task)
        return agent_result.answer
    except Exception as e:
        logger.exception(f"Task execution failed: {e}")
        return "Task failed due to an error"


async def main():
    """Main entry point for the application."""
    task = "Get top account by revenue from my accounts in digital sales, then send an email to the account owner, and save it to to file in my filesystem under cuga_workspace/email_sent.md"
    result = await perform_task(task)
    print(f"Task Result: {result}")


if __name__ == "__main__":
    asyncio.run(main())
