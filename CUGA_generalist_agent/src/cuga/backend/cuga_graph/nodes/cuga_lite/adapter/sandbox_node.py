"""Sandbox execute node for the CugaLite agent graph."""

from __future__ import annotations

import json
from typing import Any, Callable, Optional

from langchain_core.messages import HumanMessage
from langchain_core.runnables import RunnableConfig
from loguru import logger

from cuga.backend.activity_tracker.tracker import Step
from cuga.backend.cuga_graph.nodes.cuga_agent_core.execution.todos import extract_task_todos_from_new_vars
from cuga.backend.cuga_graph.nodes.cuga_agent_core.graph.graph_nodes import (
    append_chat_messages_with_step_limit as core_append_with_step_limit,
    create_error_command as core_create_error_command,
    execution_output_text,
)
from cuga.backend.cuga_graph.nodes.cuga_agent_core.policy.execution_policy import ExecutionRouter
from cuga.backend.cuga_graph.nodes.cuga_agent_core.policy.tool_approval_handler import ToolApprovalHandler
from cuga.backend.cuga_graph.nodes.cuga_lite.adapter.response_utils import reflection_current_task
from cuga.backend.cuga_graph.nodes.cuga_lite.executors.code_executor import (
    CodeExecutor,
    is_find_tools_listing_markdown,
)
from cuga.backend.cuga_graph.nodes.cuga_lite.reflection.reflection import reflection_task
from cuga.backend.cuga_graph.utils.context_management_utils import (
    prepare_reflection_context,
    truncate_text_for_context,
)
from cuga.backend.cuga_graph.utils.token_counter import clamp_watsonx_completion_for_messages
from cuga.backend.llm.models import LLMManager
from cuga.config import settings

_llm_manager = LLMManager()


def _describe_observed_shape(result: Any) -> str:
    """Render a short, human-readable description of an observed tool result."""
    if isinstance(result, dict):
        keys = list(result.keys())[:8]
        suffix = ", ..." if len(result) > len(keys) else ""
        return f"dict with keys [{', '.join(repr(k) for k in keys)}{suffix}]"
    if isinstance(result, (list, tuple)):
        kind = type(result).__name__
        if result:
            return (
                f"{kind} of {len(result)} items, e.g. first item: "
                f"{type(result[0]).__name__} {str(result[0])[:120]!r}"
            )
        return f"empty {kind}"
    if isinstance(result, str):
        return f"str of {len(result)} chars, e.g. {result[:120]!r}"
    return type(result).__name__


def _record_weak_schema_shapes(adapter: Any, tool_calls: list) -> None:
    """Stash the first observed output shape for any weak-schema tool this session."""
    weak_schema_tool_names = getattr(adapter, "_weak_schema_tool_names", frozenset())
    if not weak_schema_tool_names:
        return
    observed = getattr(adapter, "_observed_tool_shapes", {})
    for call in tool_calls:
        name = call.get("name")
        if name not in weak_schema_tool_names or name in observed or call.get("error"):
            continue
        observed[name] = _describe_observed_shape(call.get("result"))


def _needs_shape_tracking(adapter: Any) -> bool:
    """True when at least one weak-schema tool's shape hasn't been observed yet this session."""
    weak_schema_tool_names = getattr(adapter, "_weak_schema_tool_names", frozenset())
    observed = getattr(adapter, "_observed_tool_shapes", {})
    return bool(weak_schema_tool_names - observed.keys())


def create_sandbox_node(adapter: Any, base_thread_id: Any, base_apps_list: Any) -> Callable:
    async def sandbox(state: Any, config: Optional[RunnableConfig] = None):
        """Execute code in sandbox and return results."""
        from cuga.backend.cuga_graph.nodes.cuga_lite.tracking.tracker import ToolCallTracker

        # Check if user denied approval (only if policies are enabled)
        if settings.policy.enabled:
            denial_command = ToolApprovalHandler.handle_denial(adapter, state)
            if denial_command:
                return denial_command

        configurable = config.get("configurable", {}) if config else {}
        from cuga.backend.cuga_graph.utils.langfuse_tracing import sync_langfuse_callbacks_from_config

        sync_langfuse_callbacks_from_config(config)
        max_steps = configurable.get("cuga_lite_max_steps") if "cuga_lite_max_steps" in configurable else None
        if "thread_id" in configurable:
            current_thread_id = configurable["thread_id"]
        else:
            current_thread_id = state.thread_id or base_thread_id
        current_apps_list = configurable.get("apps_list", base_apps_list)
        track_tool_calls = configurable.get("track_tool_calls", False)
        reflection_enabled = (
            configurable.get("reflection_enabled")
            if "reflection_enabled" in configurable
            else settings.advanced_features.reflection_enabled
        )

        # Get existing variables using CugaLiteState's own variables_manager
        existing_vars = {}
        for var_name in list(state.variables_manager.get_variable_names()):
            var_value = state.variables_manager.get_variable(var_name)
            if is_find_tools_listing_markdown(var_value):
                state.variables_manager.remove_variable(var_name)
                continue
            existing_vars[var_name] = var_value

        # Add tools to context, wrapping each callable to record outputs
        # in execution order for trace conversion.
        #
        # We record BOTH real tool-call outputs and the stdout produced by the
        # pure-code segments between them, interleaved in execution order. The
        # trace converter represents those pure-code segments as synthetic
        # "code_execution" steps; recording their stdout here (positionally)
        # lets the converter link each code_execution step to its real output
        # instead of guessing from the raw text.
        from cuga.backend.cuga_graph.nodes.cuga_lite.executors.local.local_executor import (
            current_stdout_len,
            current_stdout_value,
            set_stdout_finalize_hook,
            reset_stdout_finalize_hook,
        )

        _tool_call_history: list = []  # [(tool_name, serialized_output), ...]
        # Offset into the live stdout buffer up to which we've already
        # attributed output to a prior step. None means stdout position is
        # unavailable (e.g. remote execution) — we then skip code_execution
        # capture and let the converter fall back to its text heuristic.
        _stdout_cursor: list = [0]

        def _record_code_segment_before_tool() -> None:
            """Record stdout produced since the last step as a code_execution entry.

            Called just before a tool's output is recorded, so any print output
            from the code that ran between the previous tool call and this one is
            attributed to a synthetic code_execution step, in order.
            """
            cur_len = current_stdout_len()
            if cur_len is None:
                return
            full = current_stdout_value() or ""
            start = _stdout_cursor[0]
            if cur_len > start:
                segment = full[start:cur_len]
                if segment.strip():
                    _tool_call_history.append(("code_execution", segment))
            _stdout_cursor[0] = cur_len

        def _record_trailing_code_segment(raw_stdout: str) -> None:
            """Finalize hook: record stdout after the last tool call.

            Invoked by the executor at the end of the code block, while the
            stdout buffer is still live. Captures the trailing pure-code
            segment — everything printed after the final tool call, or the
            whole output when no tool ran — as a last code_execution entry, so
            the ordered timeline in _tool_call_history is complete.
            """
            start = _stdout_cursor[0]
            if len(raw_stdout) > start:
                segment = raw_stdout[start:]
                if segment.strip():
                    _tool_call_history.append(("code_execution", segment))
            _stdout_cursor[0] = len(raw_stdout)

        def _wrap_tool_for_history(tool_name: str, tool_fn):
            """Wrap a tool callable to record its output in _tool_call_history."""
            import functools
            import asyncio

            def _serialize(result):
                try:
                    if hasattr(result, 'model_dump'):
                        return result.model_dump()
                    elif hasattr(result, 'dict'):
                        return result.dict()
                    return result
                except Exception:
                    return str(result)

            @functools.wraps(tool_fn)
            async def _async_wrapper(*args, **kwargs):
                result = await tool_fn(*args, **kwargs)
                # Attribute any stdout since the last step to a code_execution
                # step, then record this tool's output — preserving order.
                _record_code_segment_before_tool()
                _tool_call_history.append((tool_name, _serialize(result)))
                # Advance the cursor past whatever the tool call itself printed
                # so it isn't re-attributed to the next code_execution segment.
                _cur = current_stdout_len()
                if _cur is not None:
                    _stdout_cursor[0] = _cur
                return result

            @functools.wraps(tool_fn)
            def _sync_wrapper(*args, **kwargs):
                result = tool_fn(*args, **kwargs)
                _record_code_segment_before_tool()
                _tool_call_history.append((tool_name, _serialize(result)))
                _cur = current_stdout_len()
                if _cur is not None:
                    _stdout_cursor[0] = _cur
                return result

            if asyncio.iscoroutinefunction(tool_fn):
                return _async_wrapper
            return _sync_wrapper

        wrapped_tools = {}
        for tool_name, tool_fn in adapter._tools_context.items():
            if callable(tool_fn):
                wrapped_tools[tool_name] = _wrap_tool_for_history(tool_name, tool_fn)
            else:
                wrapped_tools[tool_name] = tool_fn

        context = {**existing_vars, **wrapped_tools}

        # Start tool call tracking (enabled via invoke parameter, or internally
        # whenever a weak-schema tool's output shape hasn't been observed yet)
        ToolCallTracker.start_tracking(enabled=track_tool_calls or _needs_shape_tracking(adapter))

        try:
            # Execute the script - pass the CugaLiteState itself since it has variables_manager
            _exec_plan = ExecutionRouter.resolve(settings)
            if _exec_plan.split_execution_active:
                logger.info(
                    "Split execution: python=%s shell=%s fs=%s",
                    _exec_plan.python_backend,
                    _exec_plan.shell_backend,
                    _exec_plan.filesystem_backend,
                )
            logger.debug(f"\n\n------\n\n📝 Generated code:\n\n{state.script}\n\n------\n\n")
            _finalize_token = set_stdout_finalize_hook(_record_trailing_code_segment)
            try:
                output, new_vars = await CodeExecutor.eval_with_tools_async(
                    code=state.script,
                    _locals=context,
                    state=state,  # Pass CugaLiteState - it has variables_manager property
                    thread_id=current_thread_id,
                    apps_list=current_apps_list,
                    plan=_exec_plan,
                )
            finally:
                reset_stdout_finalize_hook(_finalize_token)

            adapter._tracker.collect_step(step=Step(name="User_output", data=output))
            adapter._tracker.collect_step(
                step=Step(
                    name="User_output_variables",
                    data=json.dumps(
                        new_vars,
                        default=lambda o: o.model_dump() if hasattr(o, "model_dump") else str(o),
                    ),
                )
            )

            # Output is already formatted and trimmed by code_executor
            logger.debug(f"\n\n------\n\n📝 Execution output:\n\n{output}\n\n------\n\n")

            # Update variables using CugaLiteState's variables_manager
            # This automatically updates state.variables_storage
            for name, value in new_vars.items():
                if is_find_tools_listing_markdown(value):
                    continue
                state.variables_manager.add_variable(
                    value, name=name, description="Created during code execution"
                )

            # Store tool call history for trace conversion.
            # This provides per-call outputs in execution order so the trace
            # converter can map each tool step to its actual output.
            if _tool_call_history:
                state.variables_storage["_tool_call_outputs"] = {
                    "value": _tool_call_history,
                    "description": "Ordered tool call outputs for trace conversion",
                    "type": "list",
                    "created_at": "",
                    "count_items": len(_tool_call_history),
                }

            reflection_output = ""
            if reflection_enabled:
                try:
                    active_model = configurable.get("llm") or _llm_manager.get_model(
                        settings.agent.planner.model
                    )
                    reflection_agent = reflection_task(llm=active_model)
                    reflection_text_limit = min(
                        30_000,
                        settings.advanced_features.execution_output_max_length // 2,
                    )
                    agent_history, coder_output = await prepare_reflection_context(
                        list(state.chat_messages),
                        output,
                        active_model,
                        max_output_chars=reflection_text_limit,
                        max_history_chars=reflection_text_limit,
                        tracker=adapter._tracker,
                    )
                    skills_prompt_section = truncate_text_for_context(
                        state.reflection_skills_prompt_section or "",
                        reflection_text_limit,
                        label="Skills prompt section",
                    )
                    current_task = reflection_current_task(state) or "(no task text)"
                    clamp_watsonx_completion_for_messages(
                        active_model,
                        [
                            {
                                "role": "user",
                                "content": "\n".join(
                                    [current_task, agent_history, coder_output, skills_prompt_section]
                                ),
                            }
                        ],
                    )
                    reflection_result = await reflection_agent.ainvoke(
                        {
                            "instructions": "",
                            "current_task": current_task,
                            "agent_history": agent_history,
                            "coder_agent_output": coder_output,
                            "apps": state.reflection_apps or [],
                            "enable_find_tools": state.reflection_enable_find_tools,
                            "skills_enabled": state.reflection_skills_enabled,
                            "skills_prompt_section": skills_prompt_section,
                            "force_autonomous_mode": settings.advanced_features.force_autonomous_mode,
                        },
                        config=config or {},
                    )
                    reflection_output = reflection_result.content
                    logger.debug(f"Reflection output:\n{reflection_output}")
                except Exception as e:
                    logger.warning(f"Reflection failed: {e}")
                    reflection_output = ""

            # Output is already formatted by code_executor
            execution_message_content = execution_output_text(output)
            if reflection_output:
                execution_message_content = (
                    f"{execution_message_content}\n\n---\n\nSummary:\n{reflection_output}"
                )

            adapter._tracker.collect_step(
                step=Step(
                    name="User_return",
                    data=execution_message_content,
                )
            )

            new_message = HumanMessage(content=execution_message_content)
            updated_messages, error_message = core_append_with_step_limit(
                adapter, state, [new_message], max_steps
            )

            # Collect tool calls from this execution
            execution_tool_calls = ToolCallTracker.stop_tracking()
            _record_weak_schema_shapes(adapter, execution_tool_calls)
            accumulated_tool_calls = (state.tool_calls or []) + (
                execution_tool_calls if track_tool_calls else []
            )

            if error_message:
                return core_create_error_command(
                    adapter,
                    updated_messages,
                    error_message,
                    state.step_count,
                    additional_updates={
                        "variables_storage": state.variables_storage,
                        "variable_counter_state": state.variable_counter_state,
                        "variable_creation_order": state.variable_creation_order,
                        "tool_calls": accumulated_tool_calls,
                    },
                )

            todo_state_update = extract_task_todos_from_new_vars(new_vars)
            base_update = {
                "chat_messages": updated_messages,
                "variables_storage": state.variables_storage,
                "variable_counter_state": state.variable_counter_state,
                "variable_creation_order": state.variable_creation_order,
                "step_count": state.step_count + 1,
                "tool_calls": accumulated_tool_calls,
            }
            if todo_state_update is not None:
                base_update["task_todos"] = todo_state_update
            return base_update
        except Exception as e:
            # Collect tool calls even on error
            execution_tool_calls = ToolCallTracker.stop_tracking()
            _record_weak_schema_shapes(adapter, execution_tool_calls)
            accumulated_tool_calls = (state.tool_calls or []) + (
                execution_tool_calls if track_tool_calls else []
            )

            error_msg = f"Error during execution: {str(e)}"
            logger.error(error_msg)
            new_message = HumanMessage(content=error_msg)
            updated_messages, limit_error_message = core_append_with_step_limit(
                adapter, state, [new_message], max_steps
            )

            if limit_error_message:
                return core_create_error_command(
                    adapter, updated_messages, limit_error_message, state.step_count
                )

            return {
                "chat_messages": updated_messages,
                "error": error_msg,
                "final_answer": error_msg,
                "execution_complete": True,
                "step_count": state.step_count + 1,
                "tool_calls": accumulated_tool_calls,
            }

    return sandbox
