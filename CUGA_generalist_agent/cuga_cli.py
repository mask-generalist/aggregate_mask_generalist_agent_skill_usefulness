"""
Interactive terminal chat with the CUGA agent — no UI, no server.

Uses the same settings as `cuga start demo_skills` (skills + OpenSandbox).
Conversation history is maintained across turns via thread_id.

Run:
    python chat.py
    python chat.py --no-sandbox   # native sandbox-exec instead of Docker
"""

import os
import sys

# Must be set before importing cuga (Dynaconf reads env at import time).
os.environ["DYNACONF_SKILLS__ENABLED"] = "true"
os.environ["DYNACONF_ADVANCED_FEATURES__ENABLE_SHELL_TOOL"] = "true"
os.environ["DYNACONF_ADVANCED_FEATURES__ENABLE_FILESYSTEM_TOOLS"] = "true"
os.environ["DYNACONF_STORAGE__PRESERVE_CONFIGS_ON_STARTUP"] = "local"

if "--no-sandbox" in sys.argv:
    os.environ["DYNACONF_ADVANCED_FEATURES__SANDBOX_MODE"] = "native"
    os.environ["DYNACONF_ADVANCED_FEATURES__OPENSANDBOX_SANDBOX"] = "false"
else:
    os.environ["DYNACONF_ADVANCED_FEATURES__SANDBOX_MODE"] = "opensandbox"
    os.environ["DYNACONF_ADVANCED_FEATURES__OPENSANDBOX_SANDBOX"] = "true"

SKILLS_FOLDER = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".cuga")

import asyncio
import datetime
import json
import time
import uuid
from cuga.sdk import CugaAgent
from cuga.backend.cuga_graph.nodes.human_in_the_loop.followup_model import ActionResponse, ActionType


def _make_response(thread_id: str, text: str) -> ActionResponse:
    return ActionResponse(
        action_id="tool_approval",
        response_type=ActionType.CONFIRMATION,
        text_response=text,
        timestamp=datetime.datetime.now().isoformat(),
        user_id=thread_id,
        session_id=thread_id,
    )


async def _run_turn_with_stream(
    agent: CugaAgent,
    thread_id: str,
    user_input: str | None,
    resume: ActionResponse | None = None,
) -> tuple[str, bool]:
    """Run one agent turn via AgentLoop, capturing stream events for trace_converter."""
    from cuga.backend.cuga_graph.utils.agent_loop import AgentLoop, AgentLoopAnswer, StreamEvent
    from cuga.backend.cuga_graph.state.agent_state import AgentState, default_state
    from cuga.backend.activity_tracker.tracker import ActivityTracker
    from cuga.backend.server.conversation_history import get_conversation_db

    event_sequence = 0
    buffer = []

    if user_input is not None:
        buffer.append({
            "event_name": "UserMessage",
            "event_data": user_input,
            "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "sequence": event_sequence,
        })
        event_sequence += 1
    elif resume is not None:
        buffer.append({
            "event_name": "HITLResponse",
            "event_data": json.dumps({
                "action_id": resume.action_id,
                "response_type": resume.response_type,
                "text_response": resume.text_response,
                "timestamp": resume.timestamp,
            }),
            "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "sequence": event_sequence,
        })
        event_sequence += 1

    # Build state for new turns (resume turns use resume= only)
    local_state = None
    if user_input is not None:
        from langchain_core.messages import HumanMessage
        new_message = HumanMessage(content=user_input)
        try:
            existing = agent.graph.get_state({"configurable": {"thread_id": thread_id}}).values
            if existing:
                local_state = AgentState(**existing)
                local_state.chat_messages = (local_state.chat_messages or []) + [new_message]
                local_state.input = user_input
                local_state.apply_message_sliding_window()
            else:
                local_state = default_state(page=None, observation=None, goal="")
                local_state.chat_messages = [new_message]
                local_state.input = user_input
                local_state.thread_id = thread_id
        except Exception:
            local_state = default_state(page=None, observation=None, goal="")
            local_state.chat_messages = [new_message]
            local_state.input = user_input
            local_state.thread_id = thread_id

    agent_loop = AgentLoop(
        thread_id=thread_id,
        langfuse_handler=None,
        graph=agent.graph,
        tracker=ActivityTracker(),
    )

    answer = ""
    interrupted = False

    # Snapshot cumulative token counters + wall clock before the turn so we can
    # log the per-turn delta / latency as a native TurnMetrics stream event.
    _tracker = ActivityTracker()
    _tok0 = (
        _tracker.input_token_usage,
        _tracker.output_token_usage,
        _tracker.reasoning_token_usage,
        _tracker.token_usage,
    )
    _t0 = time.perf_counter()

    async for event in agent_loop.run_stream(state=local_state, resume=resume):
        if isinstance(event, AgentLoopAnswer):
            interrupted = bool(event.interrupt)
            if interrupted and not event.answer:
                # get_output() returns answer="" on __interrupt__; read final_answer from state instead
                try:
                    state_vals = agent.graph.get_state({"configurable": {"thread_id": thread_id}}).values
                    state_obj = AgentState(**state_vals)
                    meta = state_obj.cuga_lite_metadata or {}
                    answer = (
                        state_obj.final_answer
                        or meta.get("approval_message")
                        or "Approve tool use to continue?"
                    )
                except Exception:
                    answer = "Approve tool use to continue?"
            else:
                answer = event.answer or ""
        else:
            try:
                parsed = StreamEvent.parse(event)
                name = parsed.name
                if name and name != "ChatAgent":
                    buffer.append({
                        "event_name": name,
                        "event_data": event,
                        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                        "sequence": event_sequence,
                    })
                    event_sequence += 1
            except Exception:
                pass

    # Emit a per-turn metrics event (latency + token deltas) for trace_converter.
    _latency_ms = (time.perf_counter() - _t0) * 1000.0
    buffer.append({
        "event_name": "TurnMetrics",
        "event_data": json.dumps({
            "latency_in_ms": _latency_ms,
            "input_tokens": _tracker.input_token_usage - _tok0[0],
            "output_tokens": _tracker.output_token_usage - _tok0[1],
            "reasoning_tokens": _tracker.reasoning_token_usage - _tok0[2],
            "total_tokens": _tracker.token_usage - _tok0[3],
        }),
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "sequence": event_sequence,
    })
    event_sequence += 1

    try:
        db = get_conversation_db()
        await db.save_stream_events("cuga-default", thread_id, "default_user", buffer)
    except Exception as exc:
        print(f"\nStream events save failed: {exc}")

    return answer, interrupted


async def chat_loop(agent: CugaAgent, thread_id: str) -> None:
    print(f"CUGA chat  (thread: {thread_id})")
    print("Type your message and press Enter. Ctrl-C or 'exit' to quit.\n")

    while True:
        try:
            user_input = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nBye.")
            break

        if not user_input or user_input.lower() in ("exit", "quit"):
            print("Bye.")
            break

        try:
            answer, interrupted = await _run_turn_with_stream(agent, thread_id, user_input)

            while interrupted:
                print(f"Agent: {answer}")
                try:
                    choice = input("Your response: ")
                except (EOFError, KeyboardInterrupt):
                    choice = "no"
                answer, interrupted = await _run_turn_with_stream(
                    agent, thread_id, None, resume=_make_response(thread_id, choice)
                )

            print(f"Agent: {answer}\n")

        except KeyboardInterrupt:
            print("\n(interrupted)\n")


async def _save_to_db(agent: CugaAgent, thread_id: str) -> None:
    try:
        from cuga.backend.cuga_graph.state.agent_state import AgentState
        from cuga.backend.server.main import save_conversation_to_db

        state_snapshot = agent.graph.get_state({"configurable": {"thread_id": thread_id}})
        if not state_snapshot or not state_snapshot.values:
            return
        state = AgentState(**state_snapshot.values)
        await save_conversation_to_db(
            agent_id="cuga-default",
            thread_id=thread_id,
            state=state,
            user_id="default_user",
        )
        print("Conversation saved to DB.")
    except Exception as exc:
        print(f"\nDB save failed: {exc}")


async def _seed_policies() -> None:
    from cuga.backend.server.config_store import load_config
    from cuga.backend.cuga_graph.policy.utils import apply_policies_data_to_storage
    from cuga.backend.cuga_graph.policy.configurable import PolicyConfigurable
    from cuga.backend.server.manage_routes.helpers import policies_list_from_config

    config, _ = await load_config(None) or (None, None)
    raw_policies = (config or {}).get("policies")
    policies_list = policies_list_from_config(raw_policies) if raw_policies is not None else []
    policy_system = PolicyConfigurable.get_instance()
    await policy_system.initialize()
    await apply_policies_data_to_storage(
        policy_system.storage,
        policies_list,
        clear_existing=True,
    )
    await policy_system.initialize()


async def main() -> None:
    from cuga.backend.server.demo_manage_setup import setup_demo_manage_config
    setup_demo_manage_config("demo_skills")
    await _seed_policies()

    agent = CugaAgent(enable_skills=True, skills_folder=SKILLS_FOLDER)
    thread_id = str(uuid.uuid4())

    try:
        from cuga.backend.cuga_graph.nodes.cuga_lite.executors.code_executor import CodeExecutor
        executor = CodeExecutor._get_opensandbox_executor()
    except Exception:
        executor = None

    if executor and os.environ.get("DYNACONF_ADVANCED_FEATURES__SANDBOX_MODE") == "opensandbox":
        print("Starting sandbox container...")
        try:
            await executor.get_interpreter_for_thread(thread_id)
            print("Sandbox ready.\n")
        except Exception as exc:
            print(f"Sandbox failed to start ({exc}), will retry on first command.\n")

    try:
        await chat_loop(agent, thread_id)
    finally:
        await _save_to_db(agent, thread_id)
        if executor:
            try:
                await asyncio.shield(executor.release_sandbox(thread_id))
            except Exception:
                pass
        await agent.aclose()


if __name__ == "__main__":
    asyncio.run(main())
