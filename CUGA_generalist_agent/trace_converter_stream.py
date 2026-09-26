"""Stream-based trace converter.

Builds an AgentDialogueTrace turn skeleton from the ``stream_events`` table
instead of ``conversation_history``.

Why this exists: ``conversation_history.messages`` is lossy by design — before
each turn is persisted the agent state applies a sliding message window
(``apply_message_sliding_window``) and context summarization
(``manage_message_context``), so long conversations lose their earliest turns
and gain a synthesized "Here is a summary of the conversation to date" head
message. ``stream_events`` suffers neither: ``save_stream_events`` appends every
turn's event buffer and renumbers ``sequence`` to stay monotonic, so it is a
complete, ordered record of the whole conversation.

The event payloads are not in the shape the parser wants, so
``_reconstruct_messages_from_stream`` assembles them into the same
role/content ``messages`` list ``convert_trace_to_agent_dialogue`` expects:

    UserMessage / HITLResponse   -> user message (starts a turn)
    CodeAgent_Reasoning          -> leading thought for the next assistant msg
    CodeAgent (code)             -> assistant message with a ```python``` block
    CodeAgent (execution_output) -> "Execution output:" user message
    FinalAnswerAgent             -> trailing assistant message (the response)

All step/tool/skill/latency parsing is delegated to the existing helpers in
``trace_converter`` so the two converters stay behaviourally aligned.
"""

from __future__ import annotations

import json
import os
import sqlite3
from dataclasses import asdict
from datetime import datetime
from typing import List, Optional

from trace_converter import (
    AgentDialogueTrace,
    convert_trace_to_agent_dialogue,
    _extract_hitl_approval_infos_from_stream,
    _extract_tool_call_outputs_from_stream,
    _extract_turn_metrics_from_stream,
    _DEFAULT_DB_PATH,
    _DEFAULT_OUTPUT_DIR,
)

# Turn boundaries in the event stream — same set the metrics extractor uses.
_BOUNDARY_EVENTS = {"UserMessage", "HITLResponse"}

_EXECUTION_OUTPUT_PREFIX = "Execution output:\n"


def _sse_data(event_data) -> str:
    """Return the payload portion of an SSE-style event_data.

    Events are stored either as raw strings/JSON or as ``event: X\\ndata: {json}``.
    Mirrors the split idiom used by the extractors in trace_converter.
    """
    if isinstance(event_data, str) and "data: " in event_data:
        return event_data.split("data: ", 1)[1]
    return event_data


def _parse_payload(event: dict):
    """Parse an event's JSON payload, tolerating SSE prefixes and non-JSON bodies."""
    data = _sse_data(event.get("event_data", ""))
    if isinstance(data, dict):
        return data
    if isinstance(data, str):
        try:
            return json.loads(data)
        except (json.JSONDecodeError, TypeError):
            return None
    return None


def _reconstruct_messages_from_stream(stream_events: List[dict]) -> List[dict]:
    """Rebuild a conversation_history-style ``messages`` list from stream events.

    The result is a flat list of ``{"role", "content", "metadata"}`` dicts in the
    exact shape ``convert_trace_to_agent_dialogue`` parses. Turns are segmented on
    ``UserMessage`` / ``HITLResponse`` events (in ``sequence`` order).

    Invariant: emit exactly one ``"Execution output:"`` user message per CodeAgent
    execution event so the count matches ``_extract_tool_call_outputs_from_stream``
    — otherwise the stream-alignment guard in trace_converter nulls tool outputs.
    """
    try:
        ordered = sorted(stream_events, key=lambda e: e.get("sequence", 0))
    except TypeError:
        ordered = list(stream_events)

    messages: List[dict] = []
    thought_buffer: List[str] = []

    def flush_thought() -> str:
        nonlocal thought_buffer
        text = "\n".join(t for t in thought_buffer if t).strip()
        thought_buffer = []
        return text

    for event in ordered:
        name = event.get("event_name")

        if name in _BOUNDARY_EVENTS:
            # New turn. Any buffered thought belongs to no assistant message yet;
            # drop it (the reasoning for the previous turn is already emitted).
            thought_buffer = []
            if name == "UserMessage":
                content = _sse_data(event.get("event_data", ""))
                if not isinstance(content, str):
                    content = str(content)
                messages.append({
                    "role": "user",
                    "content": content,
                    "metadata": {"hitl": False},
                })
            else:  # HITLResponse
                payload = _parse_payload(event) or {}
                messages.append({
                    "role": "user",
                    "content": payload.get("text_response", ""),
                    "metadata": {"hitl": True},
                })

        elif name == "CodeAgent_Reasoning":
            thought = _sse_data(event.get("event_data", ""))
            if isinstance(thought, str):
                thought_buffer.append(thought)

        elif name == "CodeAgent":
            payload = _parse_payload(event)
            if not isinstance(payload, dict):
                continue
            code = (payload.get("code") or "").strip()
            output = (payload.get("execution_output") or "").strip()
            if code:
                thought = flush_thought()
                content = (f"{thought}\n\n" if thought else "") + f"```python\n{code}\n```"
                messages.append({"role": "assistant", "content": content})
            if output:
                messages.append({
                    "role": "user",
                    "content": f"{_EXECUTION_OUTPUT_PREFIX}{output}",
                })

        elif name == "FinalAnswerAgent":
            payload = _parse_payload(event) or {}
            messages.append({
                "role": "assistant",
                "content": payload.get("final_answer", ""),
            })

    return messages


def convert_trace_from_stream(
    db_path: str = _DEFAULT_DB_PATH,
    output_path: Optional[str] = None,
    thread_id: Optional[str] = None,
) -> AgentDialogueTrace:
    """Convert a conversation to AgentDialogueTrace using ``stream_events``.

    Drop-in alternative to ``trace_converter.convert_trace_from_db`` — same
    signature — but sources the turn skeleton from the untruncated stream rather
    than the truncated ``conversation_history`` blob.

    Args:
        db_path: Path to the (per-trial) SQLite database.
        output_path: Optional path to write the converted trace JSON. If None, a
            timestamped file is created in ./converted_traces/.
        thread_id: Optional thread_id to convert. If None, converts the most
            recently updated conversation's thread.

    Returns:
        The converted AgentDialogueTrace object.
    """
    if not os.path.exists(db_path):
        raise FileNotFoundError(f"Database not found: {db_path}")

    conn = sqlite3.connect(db_path)
    try:
        # Resolve thread_id from conversation_history when not supplied, matching
        # convert_trace_from_db's "most recently updated" selection.
        if not thread_id:
            row = conn.execute(
                "SELECT thread_id FROM conversation_history "
                "ORDER BY updated_at DESC LIMIT 1"
            ).fetchone()
            if row is None:
                raise ValueError(
                    "No conversation records found in the database. "
                    "The conversation_history table is empty."
                )
            thread_id = row[0]

        se_row = conn.execute(
            "SELECT events FROM stream_events WHERE thread_id = ?",
            (thread_id,),
        ).fetchone()
    finally:
        conn.close()

    if not se_row or not se_row[0]:
        raise ValueError(
            f"No stream_events found for thread {thread_id}. "
            "The stream-based converter requires stream_events; "
            "use the legacy converter for DBs without them."
        )

    stream_events = json.loads(se_row[0])

    trace_messages = _reconstruct_messages_from_stream(stream_events)
    hitl_infos = _extract_hitl_approval_infos_from_stream(stream_events)
    tool_call_outputs_by_turn = _extract_tool_call_outputs_from_stream(stream_events)
    turn_metrics_by_turn = _extract_turn_metrics_from_stream(stream_events)

    dialogue_trace = convert_trace_to_agent_dialogue(
        trace_messages, hitl_infos,
        tool_call_outputs_by_turn=tool_call_outputs_by_turn,
        turn_metrics_by_turn=turn_metrics_by_turn,
    )
    # Stamp the DB thread_id so the trace ties back to its stream_events row and
    # its sandbox workspace (thread_id == workspace id).
    dialogue_trace.thread_id = thread_id

    if output_path is None:
        os.makedirs(_DEFAULT_OUTPUT_DIR, exist_ok=True)
        timestamp = datetime.now().strftime("%Y-%m-%dT%H-%M-%S")
        output_path = os.path.join(
            _DEFAULT_OUTPUT_DIR, f"trace_{timestamp}_{thread_id or 'unknown'}.json"
        )

    with open(output_path, "w") as f:
        json.dump(asdict(dialogue_trace), f, indent=2, default=str)

    print(f"Converted trace (stream) written to: {output_path}")
    return dialogue_trace
