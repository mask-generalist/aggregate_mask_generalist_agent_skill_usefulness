"""Trace conversion and deserialization."""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

from agent_inspect.models.metrics.agent_trace import (
    AgentDialogueTrace,
    AgentResponse,
    Step,
    TurnTrace,
)
from agent_inspect.models.metrics.agent_data_sample import ToolInputParameter
from agent_inspect.models.metrics.skill_data_sample import SkillCall

from experiment_clean.config import load_runner_config, trace_converter_from

logger = logging.getLogger(__name__)


def next_trace_path(trial_folder: Path) -> Path:
    """Return a versioned trace_<N>_<ts>.json path."""
    n = len(list(trial_folder.glob("trace_*.json"))) + 1
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    return trial_folder / f"trace_{n}_{ts}.json"


def latest_trace(trial_folder: Path) -> Optional[Path]:
    """Return the most recent trace file, or None."""
    traces = sorted(trial_folder.glob("trace_*.json"), key=lambda p: p.stat().st_mtime)
    return traces[-1] if traces else None


def convert_trace(trial_folder: Path) -> Path:
    """Convert per-run DB → versioned trace JSON.

    The turn-skeleton source is selected by the ``trace_converter`` key in
    ``runner_config.yaml`` (see
    :func:`experiment_clean.config.trace_converter_from`):

    - ``"stream"``: build from the untruncated ``stream_events`` table via
      :func:`trace_converter_stream.convert_trace_from_stream`.
    - ``"legacy"``: build from ``conversation_history`` via
      :func:`trace_converter.convert_trace_from_db` (subject to
      sliding-window / summarization truncation).

    Tool calls, steps, skill_calls, tokens, and latency come from the DB/stream
    events in both cases. After conversion, a non-mutating turn-count check
    compares the trace's turn count against ``conversation.json`` and warns on
    mismatch.
    """
    converter = trace_converter_from(load_runner_config())

    # Imported lazily: these CUGA-side modules are only needed for the DB→trace
    # conversion path (never used by the Pi runner, which writes trace JSON
    # directly). Keeping them out of module scope lets load_trace/latest_trace
    # import with no CUGA dependency.
    from trace_converter import convert_trace_from_db
    from trace_converter_stream import convert_trace_from_stream

    """Convert per-run DB → versioned trace JSON."""
    thread_id = (trial_folder / "thread_id.txt").read_text().strip()
    dbs = list(trial_folder.glob("*_cuga_db.db"))
    if not dbs:
        raise FileNotFoundError(f"No *_cuga_db.db in {trial_folder}")
    out = next_trace_path(trial_folder)

    if converter == "stream":
        convert_trace_from_stream(db_path=str(dbs[0]), thread_id=thread_id, output_path=str(out))
    else:  # "legacy" — trace_converter_from only ever returns "stream" or "legacy"
        convert_trace_from_db(db_path=str(dbs[0]), thread_id=thread_id, output_path=str(out))

    _check_turn_count(out, trial_folder / "conversation.json")

    logger.info("Converted trace (%s) -> %s", converter, out)
    return out


def _check_turn_count(trace_path: Path, conv_path: Path) -> None:
    """Warn if the trace's turn count differs from conversation.json.

    Non-mutating sanity check. ``conversation.json`` is the ground-truth record
    of the live session; a mismatch signals the trace lost (or gained) turns
    during conversion — the exact symptom the stream converter fixes.
    """
    if not conv_path.exists():
        return
    trace = json.loads(trace_path.read_text())
    conv = json.loads(conv_path.read_text())
    n_trace = len(trace.get("turns") or [])
    n_conv = len(conv.get("conversations") or [])
    if n_trace != n_conv:
        logger.warning(
            "Turn-count mismatch for %s: trace has %d, conversation.json has %d",
            trace_path.name, n_trace, n_conv,
        )


def load_trace(path: Path) -> AgentDialogueTrace:
    """Deserialize a trace JSON into AgentDialogueTrace."""
    raw = json.loads(path.read_text())
    token_keys = (
        "input_token_consumption", "output_token_consumption",
        "reasoning_token_consumption", "total_token_consumption",
    )
    totals = {k: 0 for k in token_keys}
    turns = []

    for t in raw.get("turns") or []:
        for k in token_keys:
            totals[k] += t.get(k) or 0

        steps = []
        for s in t.get("steps") or []:
            skill_calls = [
                SkillCall(skill_id=sc["skill_id"], skill_name=sc.get("skill_name"))
                for sc in (s.get("skill_calls") or [])
                if sc.get("skill_id")
            ]
            steps.append(Step(
                id=s["id"],
                parent_ids=s.get("parent_ids") or [],
                skill_calls=skill_calls,
                tool=s.get("tool"),
                tool_input_args=[
                    ToolInputParameter(name=p["name"], value=p.get("value"))
                    for p in (s.get("tool_input_args") or [])
                ],
                tool_output=s.get("tool_output"),
                agent_thought=s.get("agent_thought"),
            ))

        resp = t.get("agent_response") or {}
        # Empty string "" is a valid response — only None means missing.
        agent_response = (
            AgentResponse(response=resp["response"], status_code=resp.get("status_code"))
            if resp.get("response") is not None
            else None
        )

        turns.append(TurnTrace(
            id=t["id"],
            agent_input=t.get("agent_input", ""),
            agent_response=agent_response,
            from_id=t.get("from_id"),
            steps=steps,
            latency_in_ms=t.get("latency_in_ms"),
        ))

    return AgentDialogueTrace(turns=turns, metadata=totals)
