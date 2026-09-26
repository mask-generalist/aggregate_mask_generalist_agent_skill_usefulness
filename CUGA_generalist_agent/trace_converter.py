"""
Converts a CUGA agent trace JSON file into the AgentDialogueTrace format
defined in agent_inspect.models.metrics.agent_trace.

The source trace is a list of messages with roles ("user", "assistant") and
string content. Assistant messages embed tool calls as fenced ```python blocks
containing `await <tool_name>(...)` calls. User messages after an assistant
message typically carry "Execution output:" prefixes representing tool outputs.

This module parses those conventions and produces:
    AgentDialogueTrace -> List[TurnTrace] -> List[Step]
"""

import json
import os
import re
import sqlite3
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Optional, List, Union, Any, Dict


# ─── Target dataclasses (mirror of agent_trace.py) ───────────────────────────

@dataclass
class ToolInputParameter:
    """A parameter the tool was called with."""
    name: str
    value: Optional[Any] = None
    check: Optional[str] = None


@dataclass
class SkillInputParameter:
    """A parameter the skill was called with."""
    name: str
    value: Optional[Any] = None


@dataclass
class SkillCall:
    """Represents a skill call identified by its skill id."""
    skill_id: str
    skill_name: Optional[str] = None
    skill_parameters: Optional[List[SkillInputParameter]] = None


@dataclass
class AgentResponse:
    """An agent response produced by the agent in one turn."""
    response: Union[str, dict]
    status_code: Optional[str] = None


@dataclass
class Step:
    """A step the agent takes within a turn (tool call, thinking, etc.)."""
    id: str
    parent_ids: List[str]
    skill_calls: List[SkillCall] = field(default_factory=list)
    tool: Optional[str] = None
    tool_input_args: Optional[List[ToolInputParameter]] = None
    tool_output: Optional[Any] = None
    agent_thought: Optional[str] = None


@dataclass
class TurnTrace:
    """One back-and-forth conversation turn between agent and user/user proxy."""
    id: str
    agent_input: str
    agent_response: Optional[AgentResponse] = None
    from_id: Optional[str] = None
    steps: Optional[List[Step]] = None
    latency_in_ms: Optional[float] = None
    # Per-turn token totals (summed across every LLM call made during the turn),
    # sourced from the native "TurnMetrics" stream event.
    input_token_consumption: Optional[int] = None
    output_token_consumption: Optional[int] = None
    reasoning_token_consumption: Optional[int] = None
    total_token_consumption: Optional[int] = None


@dataclass
class AgentDialogueTrace:
    """Complete agent trace for one evaluation run."""
    thread_id: Optional[str] = None  # DB thread_id / workspace id, for traceability
    turns: Optional[List[TurnTrace]] = None


# ─── Parsing helpers ─────────────────────────────────────────────────────────

# Matches ```python ... ``` blocks in assistant content
CODE_BLOCK_RE = re.compile(
    r"```python\s*\n(.*?)```",
    re.DOTALL
)

# Matches a function call with keyword arguments
KWARG_RE = re.compile(r"(\w+)\s*=\s*(.+)")


def _generate_id() -> str:
    """Generate a unique step/turn ID."""
    return str(uuid.uuid4())[:8]


def _parse_tool_args(args_str: str) -> List[ToolInputParameter]:
    """
    Parse tool arguments from a function call string.
    Handles both positional and keyword arguments.
    """
    params = []
    if not args_str.strip():
        return params

    # Simple argument splitting - handles basic cases
    # For complex nested structures, we treat the whole thing as a single arg
    try:
        depth = 0
        in_single = False
        in_double = False
        current_arg = []
        args_list = []

        for char in args_str:
            if char == '"' and not in_single:
                in_double = not in_double
                current_arg.append(char)
            elif char == "'" and not in_double:
                in_single = not in_single
                current_arg.append(char)
            elif char in "([{" and not in_single and not in_double:
                depth += 1
                current_arg.append(char)
            elif char in ")]}" and not in_single and not in_double:
                depth -= 1
                current_arg.append(char)
            elif char == "," and depth == 0 and not in_single and not in_double:
                args_list.append("".join(current_arg).strip())
                current_arg = []
            else:
                current_arg.append(char)

        if current_arg:
            args_list.append("".join(current_arg).strip())

        for i, arg in enumerate(args_list):
            arg = arg.strip()
            if not arg:
                continue
            kwarg_match = KWARG_RE.match(arg)
            if kwarg_match:
                params.append(ToolInputParameter(
                    name=kwarg_match.group(1),
                    value=kwarg_match.group(2).strip().strip("'\"")
                ))
            else:
                params.append(ToolInputParameter(
                    name=f"arg_{i}",
                    value=arg.strip().strip("'\"")
                ))
    except Exception:
        params.append(ToolInputParameter(name="raw_args", value=args_str))

    return params


def _scan_line(line: str, depth: int, in_string):
    """Update paren/bracket depth and string state for one source line.

    Tracks entry/exit of ``'``, ``"``, ``'''``, and ``\"\"\"`` strings,
    handles escaped quotes, and skips ``#`` comments.  Only counts
    ``([{`` / ``)}]`` when outside a string literal.

    Returns:
        (depth, in_string) — the updated state after processing *line*.
    """
    i = 0
    while i < len(line):
        ch = line[i]
        # --- inside a string literal ---------------------------------
        if in_string:
            if in_string in ("'''", '"""'):
                if line[i:i + 3] == in_string:
                    in_string = None
                    i += 3
                    continue
            else:
                if ch == '\\':
                    i += 2
                    continue
                if ch == in_string:
                    in_string = None
                    i += 1
                    continue
            i += 1
            continue
        # --- outside a string literal --------------------------------
        if line[i:i + 3] in ("'''", '"""'):
            in_string = line[i:i + 3]
            i += 3
            continue
        if ch in ("'", '"'):
            in_string = ch
            i += 1
            continue
        if ch == '#':
            break
        if ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
        i += 1
    return depth, in_string


def _extract_tool_calls_from_code_block(code_block: str) -> List[dict]:
    """
    Extract tool calls from a Python code block.
    Returns a list of dicts with keys: tool, args_str, raw_code, assign_var

    Handles both single-line and multi-line tool calls by joining lines
    when parentheses are unbalanced.
    """
    calls = []
    lines = code_block.strip().split("\n")

    # First pass: join multi-line statements by tracking paren/bracket depth
    statements: List[tuple] = []  # (joined_line, assign_var_from_first_line)
    current_lines: List[str] = []
    depth = 0
    in_string = None
    current_assign_var = None

    for line in lines:
        stripped = line.strip()
        if not current_lines:
            # Starting a new statement
            if stripped.startswith("#") or not stripped:
                continue
            # Check for assignment on the first line
            assignment_match = re.match(r"(\w+)\s*=\s*(.*)", stripped)
            if assignment_match:
                current_assign_var = assignment_match.group(1)
            else:
                current_assign_var = None
            current_lines.append(stripped)
            # Count open/close parens/brackets (string-aware)
            depth, in_string = _scan_line(stripped, depth, in_string)
        else:
            # Continuation of a multi-line statement
            current_lines.append(stripped)
            depth, in_string = _scan_line(stripped, depth, in_string)

        # Statement is complete when depth returns to 0 and outside strings
        if depth <= 0 and in_string is None:
            joined = " ".join(current_lines)
            statements.append((joined, current_assign_var))
            current_lines = []
            depth = 0
            current_assign_var = None

    # Handle any remaining (unclosed) lines
    if current_lines:
        joined = " ".join(current_lines)
        statements.append((joined, current_assign_var))

    # Second pass: extract tool calls from joined statements
    for joined_line, assign_var in statements:
        # Remove assignment prefix for matching
        if assign_var:
            assignment_match = re.match(r"\w+\s*=\s*(.*)", joined_line)
            call_line = assignment_match.group(1) if assignment_match else joined_line
        else:
            call_line = joined_line

        # Record whether 'await' was present before stripping it
        has_await = bool(re.match(r"^\s*await\s+", call_line))
        call_line = re.sub(r"^\s*await\s+", "", call_line)

        # Match function call — only treat as a tool call if 'await' was used
        func_match = re.match(r"(\w+)\s*\((.*)\)\s*$", call_line, re.DOTALL)
        if func_match and has_await:
            tool_name = func_match.group(1)
            args_str = func_match.group(2)
            # Skip print() and common non-tool calls
            if tool_name in ("print", "json", "str", "int", "len", "type",
                             "list", "dict", "set", "tuple", "range",
                             "enumerate", "zip", "map", "filter", "sorted",
                             "open", "getattr", "setattr", "hasattr",
                             "isinstance", "issubclass", "super", "format"):
                continue
            calls.append({
                "tool": tool_name,
                "args_str": args_str,
                "raw_code": joined_line,
                "assign_var": assign_var,
            })

    return calls


@dataclass
class _CodeBlockGroup:
    """A group of tool calls from a single code block with its preceding thought.

    Tool calls within the SAME group are independent (parallel) — they share a
    parent. Tool calls across groups are sequential.
    The ``thought`` is the reasoning text that immediately precedes this code block.
    """
    thought: Optional[str]
    tool_calls: List[dict]


def _extract_structured_blocks(assistant_content: str, is_hitl_gated: bool = False) -> tuple:
    """
    Parse an assistant message preserving the interleaving of thoughts and
    code blocks, and preserving which tool calls share a code block (parallel).

    Returns:
        (groups: List[_CodeBlockGroup], response_text: str)

    Each _CodeBlockGroup pairs the reasoning text that immediately precedes a
    code block with the tool calls extracted from that block. Tool calls within
    the SAME group are independent (parallel) — they share a parent. Tool calls
    across groups are sequential.

    If NO code blocks exist, returns ([], full_content_as_response).

    Args:
        is_hitl_gated: When True, discard text segments between code blocks.
            In HITL-gated messages, the LLM pre-generates predicted execution
            outputs between code blocks. These are hallucinated and should not
            appear as agent_thought steps — the real execution output comes from
            a separate "Execution output:" message after user approval.
    """
    parts = CODE_BLOCK_RE.split(assistant_content)
    groups: List[_CodeBlockGroup] = []
    response_text = ""

    has_code_blocks = len(parts) > 1
    if not has_code_blocks:
        return [], assistant_content.strip()

    last_text_idx = len(parts) - 1 if len(parts) % 2 == 1 else len(parts) - 2

    pending_thought: Optional[str] = None

    for i, part in enumerate(parts):
        if i % 2 == 0:
            # Text segment
            text = part.strip()
            if not text:
                continue
            # In HITL-gated messages, text between code blocks is predicted
            # execution output (not real reasoning). Discard it.
            if is_hitl_gated and groups:
                continue
            if i == last_text_idx and i > 0:
                response_text = text
            else:
                # Accumulate text preceding the next code block
                if pending_thought:
                    pending_thought += "\n\n" + text
                else:
                    pending_thought = text
        else:
            # Code block content
            calls = _extract_tool_calls_from_code_block(part)
            if not calls and part.strip():
                # Pure logic block (no tool calls but code was executed).
                # Represent as a code_execution step so it appears in the trace.
                calls = [{
                    "tool": "code_execution",
                    "args_str": "",
                    "raw_code": part.strip(),
                    "assign_var": None,
                    "_code_body": part.strip(),
                }]
            groups.append(_CodeBlockGroup(
                thought=pending_thought,
                tool_calls=calls,
            ))
            pending_thought = None

    # If there's trailing thought with no code block (edge case), attach to
    # response or create an empty group
    if pending_thought and not response_text:
        response_text = pending_thought

    return groups, response_text


def _extract_tool_call_outputs_from_stream(
    stream_events: List[dict],
) -> List[List[tuple]]:
    """
    Extract per-execution-turn ordered tool call outputs from stream_events.

    The agent records a `_tool_call_outputs` entry in variables_storage containing
    a list of (tool_name, output) tuples in execution order for each code block.
    We only collect from sandbox events (those with `execution_output` set) since
    the variables are cumulative and would be duplicated in subsequent call_model
    events.

    Returns a list of lists, one per execution turn. Each inner list contains
    (tool_name, output_value) tuples in the order the tools were called.
    """
    results: List[List[tuple]] = []

    for ev in stream_events:
        if ev.get("event_name") != "CodeAgent":
            continue
        event_data = ev.get("event_data", "")
        if "data: " in event_data:
            data_part = event_data.split("data: ", 1)[1]
        else:
            data_part = event_data
        try:
            payload = json.loads(data_part)
        except (json.JSONDecodeError, TypeError):
            continue

        # Only consider sandbox events (those with execution_output)
        execution_output = payload.get("execution_output", "")
        if not execution_output or not execution_output.strip():
            continue

        variables = payload.get("variables")
        if not variables:
            continue
        if isinstance(variables, str):
            try:
                variables = json.loads(variables)
            except (json.JSONDecodeError, TypeError):
                continue

        tool_outputs_entry = variables.get("_tool_call_outputs")
        if tool_outputs_entry and isinstance(tool_outputs_entry, dict):
            value = tool_outputs_entry.get("value")
            if isinstance(value, list):
                # Each CodeAgent execution event (one per code block) emits
                # its own _tool_call_outputs independently.  Do NOT deduplicate
                # by value equality — two consecutive execution turns can
                # legitimately produce identical (tool_name, output) lists
                # (e.g. the same tool is called with the same result).
                # Deduplicating drops one, shifting the positional cursor and
                # mis-assigning outputs for all subsequent turns.
                results.append([(item[0], item[1]) for item in value if isinstance(item, (list, tuple)) and len(item) >= 2])

    return results


def _extract_turn_metrics_from_stream(
    stream_events: List[dict],
) -> List[Optional[dict]]:
    """
    Extract per-turn metrics (latency + token totals) from stream_events.

    CUGA emits one ``TurnMetrics`` event per turn (see cuga_cli._run_turn_with_stream
    and server main.py), carrying a JSON payload:
        {"latency_in_ms", "input_tokens", "output_tokens",
         "reasoning_tokens", "total_tokens"}

    Turn boundaries are marked by ``UserMessage`` / ``HITLResponse`` events. We
    segment the (sequence-ordered) event stream on those boundaries and pick the
    ``TurnMetrics`` event within each segment.

    Returns an ordered list with one entry per turn (``None`` when a turn has no
    metrics event — e.g. older DBs). Empty list if none are present.
    """
    boundary_names = {"UserMessage", "HITLResponse"}
    # Order by sequence when available so segmentation matches emission order.
    try:
        ordered = sorted(stream_events, key=lambda e: e.get("sequence", 0))
    except TypeError:
        ordered = list(stream_events)

    per_turn: List[Optional[dict]] = []
    started = False
    for ev in ordered:
        name = ev.get("event_name")
        if name in boundary_names:
            # New turn segment begins; default its metrics slot to None.
            per_turn.append(None)
            started = True
            continue
        if name == "TurnMetrics":
            if not started:
                # Metrics without a preceding boundary — open a slot for it.
                per_turn.append(None)
                started = True
            try:
                payload = json.loads(ev.get("event_data", ""))
            except (json.JSONDecodeError, TypeError):
                payload = None
            if isinstance(payload, dict):
                per_turn[-1] = payload

    return per_turn


# ─── Main conversion logic ───────────────────────────────────────────────────

def _make_parent_ids(prev_step_id) -> List[str]:
    """Normalize prev_step_id (str, list, or None) into a parent_ids list."""
    if prev_step_id is None:
        return []
    if isinstance(prev_step_id, list):
        return prev_step_id
    return [prev_step_id]




def _stringify_tool_output(value: Any) -> Optional[str]:
    """Convert tool_output to a string representation.

    Returns None for None, passes through strings unchanged, and uses
    repr() for dicts/lists/other objects. Reversible via ast.literal_eval().
    """
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return repr(value)


def _assign_execution_outputs(
    steps: List[Step],
    tool_call_outputs: Optional[List[tuple]] = None,
) -> None:
    """
    Match execution outputs to steps that haven't received output yet.

    Strategy:
    0. (Primary) If tool_call_outputs is available (ordered list of
       (tool_name, output) from _tool_call_outputs in stream), match
       positionally to NAMED tool steps by tool name — this is the
       definitive source.
    0b. Match code_execution entries from tool_call_outputs to unmatched
        code_execution steps, positionally within gaps between the
        named-tool anchors established by Strategy 0.  Surplus entries
        (more outputs than steps) are concatenated into the last matched
        step; surplus steps stay null.

    When tool_call_outputs is None (old DBs without _tool_call_outputs in
    stream_events, or stream-alignment mismatch), no output matching is
    performed — steps retain tool_output=None.  _prune_unexecuted_steps
    will label error/timeout cases separately.

    Args:
        tool_call_outputs: Ordered list of (tool_name, output_value) tuples
            from _tool_call_outputs in stream variables. When available, this
            is the authoritative per-call output source.
    """
    tool_steps = [s for s in steps if s.tool is not None and s.tool_output is None]

    # Track step IDs matched by Strategy 0 (these outputs appear in stdout
    # and can be used as positional anchors in the raw text).
    strategy0_matched_ids: set = set()

    # Strategy 0: Use tool_call_outputs for direct positional matching.
    # This is the most reliable source — one entry per actual tool invocation
    # in exact execution order.
    #
    # IMPORTANT: We match NAMED tools only here, never code_execution steps.
    # tool_call_outputs now interleaves ("code_execution", stdout_segment)
    # entries between the real tool outputs (recorded by the sandbox to give
    # positional data). Those code_execution entries do NOT line up 1:1 with
    # the code_execution *steps* parsed from the assistant text: a code block
    # that mixes a tool call with print() output yields only a named-tool step,
    # yet still emits a code_execution stdout segment. Letting the positional
    # loop consume code_execution entries would both strand named-tool steps
    # (a leading code segment early-stops the scan via future_tool_names) and
    # mis-assign code_execution steps (surplus in-block segments outnumber the
    # steps). So we filter code_execution out here and handle them separately
    # in Strategy 0b below.
    named_tool_steps = [ts for ts in tool_steps if ts.tool != "code_execution"]
    named_tool_outputs = (
        [o for o in tool_call_outputs if o[0] != "code_execution"]
        if tool_call_outputs
        else []
    )
    if named_tool_outputs and named_tool_steps:
        # Match named_tool_outputs to named_tool_steps positionally by tool name.
        # Both lists are in execution order. For each step, we look for the
        # next output with a matching tool name — but we must NOT skip past
        # outputs that belong to later steps (e.g. skipping a create_update_todos
        # output while looking for a tool that doesn't exist in outputs).
        #
        # Strategy: build a set of tool names that appear in remaining steps,
        # and stop scanning outputs when we hit a name needed by a future step.
        output_idx = 0
        for step_i, ts in enumerate(named_tool_steps):
            if output_idx >= len(named_tool_outputs):
                break
            # Names of tools needed by steps AFTER this one
            future_tool_names = set(
                s.tool for s in named_tool_steps[step_i + 1:] if s.tool is not None
            )
            # Scan forward in outputs for a match, but stop if we'd consume
            # an output needed by a future step (unless it matches current step)
            scan_idx = output_idx
            found = False
            while scan_idx < len(named_tool_outputs):
                out_name, out_value = named_tool_outputs[scan_idx]
                if out_name == ts.tool:
                    # Found a match for the current step
                    ts.tool_output = out_value
                    strategy0_matched_ids.add(ts.id)
                    output_idx = scan_idx + 1
                    found = True
                    break
                # This output doesn't match current step.
                # If it matches a FUTURE step, stop — don't consume it.
                if out_name in future_tool_names:
                    break
                # Otherwise skip this output (tool not in any step, e.g. load_skill)
                scan_idx += 1

            if not found:
                # No match found for this step — leave it unmatched.
                pass

        # Check if all tool steps got assigned (code_execution steps
        # still need Strategy 0b below).
        remaining_unmatched = [s for s in tool_steps if s.tool_output is None]
        if not remaining_unmatched:
            return  # All matched via tool_call_outputs — done

    # Strategy 0b: Match code_execution entries from tool_call_outputs to
    # code_execution steps, positionally within gaps between named-tool anchors.
    #
    # Strategy 0 filtered out code_execution from both the step list and the
    # output stream because code_execution entries don't map 1:1 to steps (a
    # code block mixing a tool call with print() emits an extra code_execution
    # stdout segment without a corresponding step).  Here we use those
    # code_execution entries directly — matching them positionally to unmatched
    # code_execution steps within the gaps between named-tool anchor positions
    # in the original unfiltered tool_call_outputs list.
    #
    # Surplus entries (more entries than steps in a gap) get concatenated into
    # the last matched step's output.  Surplus steps (more steps than entries)
    # stay null — honest "not captured" rather than misattributed.
    if tool_call_outputs:
        all_tool_steps = [s for s in steps if s.tool is not None]
        unmatched_ce_steps = [
            s for s in all_tool_steps
            if s.tool_output is None and s.tool == "code_execution"
        ]

        if unmatched_ce_steps:
            # Build a set of original indices consumed by Strategy 0's named-tool
            # matching.  Strategy 0 worked on filtered lists; we need to map back
            # to the original unfiltered tool_call_outputs indices.
            consumed_orig_indices: set = set()
            if named_tool_outputs and strategy0_matched_ids:
                # Rebuild the mapping: filtered_index -> original_index
                filtered_to_orig = []
                for orig_i, (tname, _) in enumerate(tool_call_outputs):
                    if tname != "code_execution":
                        filtered_to_orig.append(orig_i)

                # Walk through Strategy 0's matching to find which filtered
                # indices were consumed.  Replay the same scan logic.
                output_idx = 0
                for step_i, ts in enumerate(named_tool_steps):
                    if ts.id not in strategy0_matched_ids:
                        continue
                    if output_idx >= len(named_tool_outputs):
                        break
                    future_tool_names = set(
                        s.tool for s in named_tool_steps[step_i + 1:]
                        if s.tool is not None
                    )
                    scan_idx = output_idx
                    while scan_idx < len(named_tool_outputs):
                        out_name, _ = named_tool_outputs[scan_idx]
                        if out_name == ts.tool:
                            consumed_orig_indices.add(filtered_to_orig[scan_idx])
                            output_idx = scan_idx + 1
                            break
                        if out_name in future_tool_names:
                            break
                        scan_idx += 1

            # Segment the original tool_call_outputs into gaps separated by
            # consumed named-tool positions. Each gap contains code_execution
            # entries that correspond to the code_execution steps sitting
            # between the same named-tool steps.
            consumed_sorted = sorted(consumed_orig_indices)

            # Build boundaries: -1, consumed[0], consumed[1], ..., len(outputs)
            boundaries = [-1] + consumed_sorted + [len(tool_call_outputs)]

            # Similarly, locate each tool step's position among all_tool_steps
            # relative to the consumed named-tool steps.  We need to know which
            # gap each unmatched code_execution step falls into.
            #
            # Build a mapping: consumed_orig_index -> position_in_all_tool_steps
            # for each Strategy-0-matched named-tool step.  The position is the
            # step's index in all_tool_steps.
            #
            # We also need the reverse: for each gap in tool_call_outputs, which
            # code_execution steps fall in the corresponding gap in all_tool_steps.

            # Map each consumed orig index to its step's position in all_tool_steps
            consumed_to_step_idx: Dict[int, int] = {}
            # Build by matching: for each named_tool_step that was matched,
            # find it in all_tool_steps
            step_id_to_all_idx = {s.id: i for i, s in enumerate(all_tool_steps)}
            # Replay the Strategy 0 matching one more time, but track which
            # consumed orig index -> step
            if consumed_sorted:
                output_idx = 0
                for step_i, ts in enumerate(named_tool_steps):
                    if ts.id not in strategy0_matched_ids:
                        continue
                    if output_idx >= len(named_tool_outputs):
                        break
                    future_tool_names = set(
                        s.tool for s in named_tool_steps[step_i + 1:]
                        if s.tool is not None
                    )
                    scan_idx = output_idx
                    while scan_idx < len(named_tool_outputs):
                        out_name, _ = named_tool_outputs[scan_idx]
                        if out_name == ts.tool:
                            orig_idx = filtered_to_orig[scan_idx]
                            consumed_to_step_idx[orig_idx] = step_id_to_all_idx[ts.id]
                            output_idx = scan_idx + 1
                            break
                        if out_name in future_tool_names:
                            break
                        scan_idx += 1

            # Build step-level boundaries matching the output-level boundaries
            step_boundaries = [-1]
            for ci in consumed_sorted:
                step_boundaries.append(consumed_to_step_idx.get(ci, -1))
            step_boundaries.append(len(all_tool_steps))

            # Process each gap
            for g in range(len(boundaries) - 1):
                left_out = boundaries[g]
                right_out = boundaries[g + 1]
                left_step = step_boundaries[g]
                right_step = step_boundaries[g + 1]

                # Collect code_execution entries in this output gap
                ce_entries = []
                for oi in range(left_out + 1, right_out):
                    if oi in consumed_orig_indices:
                        continue
                    tname, tval = tool_call_outputs[oi]
                    if tname == "code_execution":
                        ce_entries.append(tval)

                if not ce_entries:
                    continue

                # Collect unmatched code_execution steps in this step gap
                ce_gap_steps = [
                    all_tool_steps[si]
                    for si in range(left_step + 1, right_step)
                    if all_tool_steps[si].tool_output is None
                    and all_tool_steps[si].tool == "code_execution"
                ]

                if not ce_gap_steps:
                    continue

                # Positional matching: first entry → first step, etc.
                for k, step in enumerate(ce_gap_steps):
                    if k < len(ce_entries):
                        step.tool_output = ce_entries[k]
                    else:
                        break  # More steps than entries — leave rest as null

                # Surplus entries: concatenate extras into last matched step
                if len(ce_entries) > len(ce_gap_steps):
                    last_step = ce_gap_steps[-1]
                    extras = ce_entries[len(ce_gap_steps):]
                    combined = [
                        last_step.tool_output if last_step.tool_output else ""
                    ] + [e for e in extras if e]
                    last_step.tool_output = "\n".join(
                        s for s in combined if s
                    )


def _process_turn_messages(
    trace_messages: List[dict],
    j: int,
    steps: List[Step],
    prev_step_id,
    is_hitl_turn: bool = False,
    tool_call_outputs_by_turn: Optional[List[List[tuple]]] = None,
    tool_call_outputs_cursor: Optional[List[int]] = None,
) -> tuple:
    """
    Process messages forward from index j as part of the current turn.

    Every user message (HITL or normal) starts a new turn. This function
    processes assistant messages and execution outputs until it encounters
    any user message — that's the boundary.

    For HITL turns (is_hitl_turn=True), the caller pre-populates steps from the
    gated assistant message (the one immediately before this HITL user message).
    This function then matches execution outputs against those steps.

    Args:
        trace_messages: Full message list.
        j: Starting index (first message after the turn's initial user message).
        steps: Accumulates steps for this turn (mutated in place).
        prev_step_id: Parent ID for the first step.
        is_hitl_turn: Whether this turn started with a HITL user message.
        tool_call_outputs_by_turn: Optional list of per-execution tool call
            output lists (from _extract_tool_call_outputs_from_stream). Each
            entry is a list of (tool_name, output) tuples in execution order.
        tool_call_outputs_cursor: Mutable single-element list [idx] tracking
            which tool_call_outputs_by_turn entries have been consumed.

    Returns:
        (j, last_assistant_step_start):
        - j: index of the next unprocessed message.
        - last_assistant_step_start: index into `steps` where the last
          assistant message's steps begin (used to identify gated steps).
    """
    last_assistant_step_start = len(steps)
    # Track where each assistant message's steps begin.  Used by
    # _prune_unexecuted_steps to reset the thought-tagger at assistant
    # boundaries so recovery thoughts from later messages aren't tagged.
    assistant_step_starts: List[int] = []

    while j < len(trace_messages):
        msg = trace_messages[j]

        if msg["role"] == "assistant":
            # Record where this assistant's steps will start
            last_assistant_step_start = len(steps)
            assistant_step_starts.append(last_assistant_step_start)
            # Process the assistant message (thoughts + tool calls interleaved)
            prev_step_id, _ = _process_assistant_blocks(
                msg["content"], steps, prev_step_id,
            )
            j += 1
            continue

        elif msg["role"] == "user":
            if msg["content"].startswith("Execution output:"):
                # Determine tool_call_outputs for this execution turn.
                tc_outputs = None
                if tool_call_outputs_by_turn and tool_call_outputs_cursor is not None:
                    tc_idx = tool_call_outputs_cursor[0]
                    if tc_idx < len(tool_call_outputs_by_turn):
                        tc_outputs = tool_call_outputs_by_turn[tc_idx]
                        tool_call_outputs_cursor[0] = tc_idx + 1

                # Execution output — assign to pending steps
                _assign_execution_outputs(
                    steps,
                    tool_call_outputs=tc_outputs,
                )
                # If an error occurred, record it on the failing step and
                # remove subsequent steps that never executed.
                _prune_unexecuted_steps(
                    steps, msg["content"],
                    tool_call_outputs=tc_outputs,
                    assistant_step_starts=assistant_step_starts,
                )
                j += 1
                continue
            else:
                # Any user message (HITL or normal) → next turn starts here.
                break

        else:
            j += 1

    return j, last_assistant_step_start


def _process_assistant_blocks(
    assistant_content: str,
    steps: List[Step],
    prev_step_id,
    is_hitl_gated: bool = False,
) -> tuple:
    """
    Process an assistant message using structured block extraction.

    Creates steps with proper thought distribution and parallel grouping:
    - Each code block's preceding reasoning becomes its own thought step.
    - Tool calls within the SAME code block share a parent (parallel).
    - Tool calls across code blocks are sequential.

    Args:
        prev_step_id: str, List[str], or None — the parent(s) for the next step.
        is_hitl_gated: When True, discard predicted execution output text
            between code blocks (HITL-gated messages contain LLM-hallucinated
            outputs interleaved with the code blocks).

    Returns: (prev_step_id, response_text: str)
        prev_step_id may be a str (single parent) or List[str] (multiple
        parallel parents for the next step to depend on).
    """
    groups, response_text = _extract_structured_blocks(assistant_content, is_hitl_gated=is_hitl_gated)

    for group in groups:
        # Create a thought step for this group's reasoning (if any)
        if group.thought:
            thought_step_id = _generate_id()
            thought_step = Step(
                id=thought_step_id,
                parent_ids=_make_parent_ids(prev_step_id),
                agent_thought=group.thought,
            )
            steps.append(thought_step)
            prev_step_id = thought_step_id

        if not group.tool_calls:
            # Code block had no recognized tool calls (pure logic/print)
            continue

        # All tool calls in the same code block are parallel — they share
        # the same parent (the thought step above, or the previous group's
        # last step).
        group_parent_ids = _make_parent_ids(prev_step_id)
        group_step_ids: List[str] = []

        for tc in group.tool_calls:
            step_id = _generate_id()

            # For code_execution steps, use the code body as the input arg
            if tc.get("_code_body"):
                tool_params = [ToolInputParameter(name="code", value=tc["_code_body"])]
            else:
                tool_params = _parse_tool_args(tc["args_str"])

            step = Step(
                id=step_id,
                parent_ids=group_parent_ids,
                tool=tc["tool"],
                tool_input_args=tool_params if tool_params else None,
            )
            steps.append(step)
            group_step_ids.append(step_id)

        # After this group, the next group's parent is:
        # - If single tool call: that step's id (str)
        # - If multiple (parallel): all their ids (list) — next step depends on all
        if len(group_step_ids) == 1:
            prev_step_id = group_step_ids[0]
        else:
            prev_step_id = group_step_ids

    return prev_step_id, response_text


@dataclass
class HITLApprovalInfo:
    """Metadata about an HITL approval gate as shown to the user."""
    policy_name: str
    approval_message: str
    required_tools: List[str] = field(default_factory=list)


def _extract_hitl_approval_infos_from_stream(
    stream_events: List[dict],
) -> List[HITLApprovalInfo]:
    """
    Extract WaitForResponse events from stream_events (ordered).

    Each WaitForResponse event corresponds positionally to an HITL message in
    conversation_history. Returns one HITLApprovalInfo per HITL gate.
    """
    infos: List[HITLApprovalInfo] = []
    for event in stream_events:
        if event.get("event_name") != "WaitForResponse":
            continue
        event_data = event.get("event_data", "")
        # Parse SSE format: "event: ...\ndata: {json}"
        if "data: " in event_data:
            data_part = event_data.split("data: ", 1)[1]
        else:
            data_part = event_data
        try:
            payload = json.loads(data_part)
        except (json.JSONDecodeError, TypeError):
            continue

        action_name = payload.get("action_name", "")
        description = payload.get("description", "")
        additional = payload.get("additional_data", {})
        tool_info = additional.get("tool", {})
        required_tools = tool_info.get("required_tools", [])

        # Extract the policy name from action_name
        # Format is "Approve Tool Execution - <policy_name>"
        policy_name = action_name
        if " - " in action_name:
            policy_name = action_name.split(" - ", 1)[1]

        infos.append(HITLApprovalInfo(
            policy_name=policy_name,
            approval_message=description,
            required_tools=required_tools,
        ))
    return infos


def _extract_hitl_approval_infos_from_agent_config(
    db_path: str,
    agent_id: str = "cuga-default",
) -> List[HITLApprovalInfo]:
    """
    Fallback: read tool_approval policies from agent_configs to build a
    single HITLApprovalInfo that applies to all HITL gates for this agent.

    Returns a list with one entry (the configured policy), or empty if none.
    """
    if not os.path.exists(db_path):
        return []
    try:
        conn = sqlite3.connect(db_path)
        cur = conn.execute(
            "SELECT config_json FROM agent_configs WHERE agent_id = ?",
            (agent_id,),
        )
        row = cur.fetchone()
        conn.close()
    except Exception:
        return []

    if not row:
        return []

    try:
        cfg = json.loads(row[0])
    except (json.JSONDecodeError, TypeError):
        return []

    infos: List[HITLApprovalInfo] = []
    policies = cfg.get("policies", {}).get("policies", [])
    for p in policies:
        if p.get("policy_type") == "tool_approval" and p.get("enabled", True):
            infos.append(HITLApprovalInfo(
                policy_name=p.get("name", "Tool Approval"),
                approval_message=p.get(
                    "approval_message",
                    "This tool requires your approval before execution.",
                ),
                required_tools=p.get("required_tools", []),
            ))
    return infos


def _has_execution_error(execution_content: str) -> bool:
    """Check if execution content contains an execution error.

    Uses the cuga executor's canonical error prefix which is produced by
    every error path (local_executor, code_executor, sandbox_node, sandbox.py).
    Also recognises the "Output before error:" prefix emitted when the
    execution partially succeeds before hitting an error.
    """
    return ("Error during execution:" in execution_content
            or "Output before error:" in execution_content)


def _prune_unexecuted_steps(
    steps: List[Step],
    execution_content: str,
    tool_call_outputs: Optional[List[tuple]] = None,
    assistant_step_starts: Optional[List[int]] = None,
) -> None:
    """Handle execution errors: record error/status on unexecuted steps rather
    than silently dropping them.

    After _assign_execution_outputs has matched outputs to steps, some callable
    steps may still have tool_output=None. This is normal for tools that don't
    produce tracked output (e.g. create_update_todos). However, if the execution
    content contains the executor's canonical error prefix, then some steps
    genuinely failed or never ran — and their tool_output should carry the
    error/timeout message so downstream consumers can see what happened.

    Uses tool_call_outputs (from stream_events) as the authoritative record of
    which tools actually ran.  Any tool step whose name never appeared in
    tool_call_outputs was never executed — mark it "Tool call not executed".
    When the execution had an error/timeout, tool steps whose name IS in
    tool_call_outputs but whose specific positional instance wasn't matched
    (Strategy 0 ran out of outputs before reaching them) are marked
    "Tool call not executed (execution timed out)".

    The thought tagger marks pre-generated thoughts that follow unexecuted
    tools.  The ``assistant_step_starts`` parameter records the step indices
    where each assistant message's steps begin — the tagger resets at these
    boundaries so that a recovery assistant message after an execution error
    is not incorrectly tagged.

    Note: HITL-gated steps are handled separately at the turn level — gated
    steps are removed before reaching this function, denied turns are cleared
    after, and approved turns execute normally. This function only deals with
    execution errors and timeouts.
    """
    if not steps or tool_call_outputs is None:
        return

    has_error = _has_execution_error(execution_content)
    executed_tools = {name for name, _output in tool_call_outputs}
    for s in steps:
        if s.tool is None or s.tool_output is not None:
            continue
        if s.tool not in executed_tools:
            # Tool name never appeared in tool_call_outputs — never ran.
            s.tool_output = "Tool call not executed"
        elif has_error:
            # Tool name ran elsewhere in this execution, but this specific
            # call wasn't reached before the error/timeout.
            s.tool_output = "Tool call not executed (execution timed out)"

    # Tag thought steps that follow unexecuted tools.
    # Reset the flag at assistant-message boundaries so recovery thoughts
    # from a later assistant message are not incorrectly tagged.
    boundary_set = set(assistant_step_starts) if assistant_step_starts else set()
    saw_unexecuted = False
    for idx, s in enumerate(steps):
        if idx in boundary_set:
            saw_unexecuted = False
        if s.tool is not None and s.tool_output in (
            "Tool call not executed",
            "Tool call not executed (execution timed out)",
        ):
            saw_unexecuted = True
        elif s.agent_thought and saw_unexecuted:
            s.agent_thought = (
                "**INVALID THOUGHT — PRE-GENERATED BEFORE TOOL EXECUTION** "
                + s.agent_thought
            )


def _convert_load_skill_steps(steps: List[Step]) -> None:
    """Convert load_skill tool steps into SkillCall steps in-place."""
    for step in steps:
        if step.tool != "load_skill":
            continue

        skill_id = None
        skill_params: List[SkillInputParameter] = []

        if step.tool_input_args:
            for param in step.tool_input_args:
                if param.name in ("arg_0", "name"):
                    skill_id = param.value
                elif param.name in ("arg_1", "args") and param.value:
                    skill_params.append(SkillInputParameter(name="args", value=param.value))

        if skill_id:
            step.skill_calls = [SkillCall(
                skill_id=skill_id,
                skill_name=skill_id,
                skill_parameters=skill_params if skill_params else None,
            )]
            step.tool = None
            step.tool_input_args = None
            step.tool_output = None


def convert_trace_to_agent_dialogue(
    trace_messages: List[dict],
    hitl_approval_infos: Optional[List[HITLApprovalInfo]] = None,
    tool_call_outputs_by_turn: Optional[List[List[tuple]]] = None,
    turn_metrics_by_turn: Optional[List[Optional[dict]]] = None,
) -> AgentDialogueTrace:
    """
    Convert a CUGA agent trace (list of role/content messages) into
    an AgentDialogueTrace.

    The trace alternates user/assistant messages. Each user→assistant pair
    forms a turn. Tool calls within assistant messages become Steps.
    Subsequent user messages containing "Execution output:" are matched
    as tool outputs for the preceding assistant's tool calls.

    Parallelism: tool calls within the same ```python code block are treated
    as parallel (they share a parent). Tool calls across blocks are sequential.

    Args:
        trace_messages: List of dicts with keys: role, content, timestamp, metadata
        hitl_approval_infos: Optional list of HITLApprovalInfo objects (one per
            HITL gate, in order). When provided, the approval metadata (policy
            name, message, required tools) is incorporated into the agent
            response for gated turns. If None or exhausted, falls back to the
            generic "[Awaiting tool approval]" prefix.
        tool_call_outputs_by_turn: Optional list of per-execution tool call
            output lists (from _extract_tool_call_outputs_from_stream). Each
            entry is a list of (tool_name, output) tuples in execution order.

    Returns:
        AgentDialogueTrace with populated turns and steps.
    """
    # ── Stream-alignment guard ──────────────────────────────────────────
    # stream_events may only cover the latest graph invocation, which can
    # be a SUBSET (or even a SUPERSET, when the conversation was resumed
    # from a summarised history) of the execution turns recorded in
    # trace_messages.  When the counts diverge, the positional cursor
    # that feeds tool_call_outputs to each execution turn is unreliable —
    # the i-th stream entry no longer corresponds to the i-th
    # "Execution output:" message.  In that case, disable the stream-based
    # strategies entirely — unmatched steps stay null.
    _exec_msg_count = sum(
        1 for m in trace_messages
        if m["role"] == "user" and m["content"].startswith("Execution output:")
    )
    if tool_call_outputs_by_turn is not None and len(tool_call_outputs_by_turn) != _exec_msg_count:
        tool_call_outputs_by_turn = None

    turns: List[TurnTrace] = []
    # Counter for positional matching of HITL gates to approval infos
    _hitl_gate_idx = 0
    # Cursor for tool_call_outputs_by_turn consumption
    _tool_call_outputs_cursor: List[int] = [0]
    # Index into turn_metrics_by_turn — one entry per turn, in order.
    _turn_metrics = turn_metrics_by_turn or []
    _turn_idx = 0
    i = 0

    while i < len(trace_messages):
        msg = trace_messages[i]

        if msg["role"] == "user":
            # Start of a new turn.
            # Every user message (including HITL approvals) starts a new turn.
            # Strip the "## Available Variables" context that gets appended to
            # user messages after code execution produces variables — only keep
            # the actual user message.
            raw_content = msg["content"]
            _var_marker = "\n\n## Available Variables"
            _var_idx = raw_content.find(_var_marker)
            if _var_idx != -1:
                raw_content = raw_content[:_var_idx]
            user_input = raw_content.strip()
            is_hitl = msg.get("metadata", {}).get("hitl", False)
            turn_id = _generate_id()
            steps: List[Step] = []
            agent_resp: Optional[AgentResponse] = None
            prev_step_id: Optional[str] = None

            j = i + 1

            # For HITL turns, pre-populate steps from the gated assistant message.
            # The gated assistant (at i-1) proposed code that was blocked by HITL.
            # Now that the user approved, those tools execute — so we include them
            # here with interleaved thoughts and will match execution output to them.
            # Skip leading thought steps — they were already shown in the previous
            # turn as the agent's reasoning before the gate.
            if is_hitl:
                gated_assistant_idx = i - 1
                if (gated_assistant_idx >= 0
                        and trace_messages[gated_assistant_idx]["role"] == "assistant"):
                    gated_content = trace_messages[gated_assistant_idx]["content"]
                    prev_step_id, _ = _process_assistant_blocks(
                        gated_content, steps, prev_step_id,
                        is_hitl_gated=True,
                    )
                    # Remove leading thought steps (already in previous turn)
                    leading_count = 0
                    for s in steps:
                        if s.tool is None:
                            leading_count += 1
                        else:
                            break
                    if leading_count:
                        steps[:] = steps[leading_count:]
                        # Fix dangling parent_ids on the new first step
                        if steps:
                            steps[0].parent_ids = []

            # Process the turn: consume assistant messages, execution outputs
            # until we hit the next user message.
            j, last_assistant_step_start = _process_turn_messages(
                trace_messages, j, steps,
                prev_step_id, is_hitl_turn=is_hitl,
                tool_call_outputs_by_turn=tool_call_outputs_by_turn,
                tool_call_outputs_cursor=_tool_call_outputs_cursor,
            )
            # Update prev_step_id from last step
            if steps:
                prev_step_id = steps[-1].id

            # Determine the agent response: use the last assistant message's
            # trailing text (after its last code block).
            # If the turn ends at a HITL gate (next msg is HITL), show code preview.
            next_is_hitl = (
                j < len(trace_messages)
                and trace_messages[j]["role"] == "user"
                and trace_messages[j].get("metadata", {}).get("hitl", False)
            )

            last_assistant_idx = None
            for k in range(i + 1, j):
                if trace_messages[k]["role"] == "assistant":
                    last_assistant_idx = k

            if last_assistant_idx is not None:
                last_assistant_content = trace_messages[last_assistant_idx]["content"]
                groups, final_response = _extract_structured_blocks(last_assistant_content)

                if next_is_hitl and groups:
                    # Turn ends at HITL gate — do NOT trace the gated tool
                    # calls (they will appear in the next HITL turn once
                    # approved and executed). Remove gated steps but keep
                    # the leading thought (agent reasoning visible before gate).
                    gated_start_idx = last_assistant_step_start
                    pre_gated = steps[:gated_start_idx]
                    gated_section = steps[gated_start_idx:]
                    # Keep only leading thought step(s) before the first tool
                    leading_thoughts = []
                    for s in gated_section:
                        if s.tool is None:
                            leading_thoughts.append(s)
                        else:
                            break
                    steps[:] = pre_gated + leading_thoughts
                    # Show the full code preview as-is (what was shown to
                    # the user before the HITL gate). Use raw code blocks
                    # from the assistant content, not reconstructed tool calls,
                    # so that print(), comments, and logic lines are preserved.
                    raw_code_blocks = CODE_BLOCK_RE.findall(last_assistant_content)
                    code_preview = "\n\n".join(
                        block.strip() for block in raw_code_blocks if block.strip()
                    )

                    # Build the approval header with policy metadata if available
                    approval_header_parts = ["[Awaiting tool approval]"]
                    if hitl_approval_infos and _hitl_gate_idx < len(hitl_approval_infos):
                        info = hitl_approval_infos[_hitl_gate_idx]
                        approval_header_parts.append("")
                        approval_header_parts.append(
                            f"**Policy:** {info.policy_name}"
                        )
                        if info.approval_message:
                            approval_header_parts.append(info.approval_message)
                        if info.required_tools:
                            approval_header_parts.append(
                                f"**Required Tools:** {', '.join(info.required_tools)}"
                            )
                    _hitl_gate_idx += 1

                    approval_header = "\n".join(approval_header_parts)
                    agent_resp = AgentResponse(
                        response=f"{approval_header}\n```python\n{code_preview}\n```"
                    )
                else:
                    agent_resp = AgentResponse(response=final_response or last_assistant_content)

            # Advance index past all consumed messages
            i = j

            # If this HITL turn was denied (flagged via metadata.hitl_denied),
            # the proposed tool calls were never executed — clear them.
            if is_hitl and steps and last_assistant_idx is not None:
                denied = trace_messages[last_assistant_idx].get("metadata", {}).get("hitl_denied", False)
                if denied:
                    steps.clear()

            # Per-turn latency + token totals from the native TurnMetrics stream
            # event (positional: the k-th turn <-> the k-th metrics entry).
            # Missing/short list leaves the fields None (backward compatible).
            latency = None
            input_tokens = output_tokens = reasoning_tokens = total_tokens = None
            _metrics = _turn_metrics[_turn_idx] if _turn_idx < len(_turn_metrics) else None
            _turn_idx += 1
            if isinstance(_metrics, dict):
                latency = _metrics.get("latency_in_ms")
                input_tokens = _metrics.get("input_tokens")
                output_tokens = _metrics.get("output_tokens")
                reasoning_tokens = _metrics.get("reasoning_tokens")
                total_tokens = _metrics.get("total_tokens")

            # Convert load_skill tool calls into SkillCall steps
            _convert_load_skill_steps(steps)

            # Fix dangling parent_ids after all filtering/pruning.
            # Steps may reference IDs removed by _prune_unexecuted_steps or
            # HITL gating — rewire them to the preceding surviving step.
            if steps:
                valid_ids = {s.id for s in steps}
                for idx, step in enumerate(steps):
                    if step.parent_ids and any(
                        pid not in valid_ids for pid in step.parent_ids
                    ):
                        kept = [pid for pid in step.parent_ids if pid in valid_ids]
                        if not kept and idx > 0:
                            kept = [steps[idx - 1].id]
                        step.parent_ids = kept

            turn = TurnTrace(
                id=turn_id,
                agent_input=user_input,
                agent_response=agent_resp,
                steps=steps if steps else None,
                latency_in_ms=latency,
                input_token_consumption=input_tokens,
                output_token_consumption=output_tokens,
                reasoning_token_consumption=reasoning_tokens,
                total_token_consumption=total_tokens,
            )
            turns.append(turn)
        else:
            # Orphan assistant message without preceding user message
            # (shouldn't normally happen, but handle gracefully)
            i += 1

    # Normalize all tool_output to strings
    for turn in turns:
        if turn.steps:
            for step in turn.steps:
                step.tool_output = _stringify_tool_output(step.tool_output)

    return AgentDialogueTrace(turns=turns)


def print_trace_summary(trace: AgentDialogueTrace) -> None:
    """Print a human-readable summary of the converted trace."""
    if not trace.turns:
        print("No turns found.")
        return

    print(f"AgentDialogueTrace: {len(trace.turns)} turn(s)")
    print("=" * 70)

    for i, turn in enumerate(trace.turns):
        print(f"\n{'─' * 70}")
        print(f"Turn {i + 1} (id={turn.id})")
        print(f"  Input: {turn.agent_input[:100]}{'...' if len(turn.agent_input) > 100 else ''}")

        if turn.steps:
            print(f"  Steps ({len(turn.steps)}):")
            for step in turn.steps:
                if step.agent_thought:
                    thought_preview = step.agent_thought[:80].replace("\n", " ")
                    print(f"    [{step.id}] 💭 Thinking: {thought_preview}...")
                if step.tool:
                    args_preview = ""
                    if step.tool_input_args:
                        args_preview = ", ".join(
                            f"{p.name}={p.value}" for p in step.tool_input_args[:3]
                        )
                    has_output = "✓" if step.tool_output else "✗"
                    print(f"    [{step.id}] 🔧 {step.tool}({args_preview}) [output: {has_output}]")

        if turn.agent_response:
            resp = turn.agent_response.response
            if isinstance(resp, str):
                resp_preview = resp[:120].replace("\n", " ")
            else:
                resp_preview = str(resp)[:120]
            print(f"  Response: {resp_preview}...")

    print(f"\n{'=' * 70}")


# ─── DB mode ────────────────────────────────────────────────────────────────

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_DEFAULT_DB_PATH = os.path.join(_SCRIPT_DIR, "src", "cuga", "dbs", "cuga.db")
_DEFAULT_OUTPUT_DIR = os.path.join(_SCRIPT_DIR, "converted_traces")


def convert_trace_from_db(
    db_path: str = _DEFAULT_DB_PATH,
    output_path: Optional[str] = None,
    thread_id: Optional[str] = None,
) -> AgentDialogueTrace:
    """
    Read a conversation record from cuga.db and convert it to
    AgentDialogueTrace format.

    Also reads stream_events for the same thread to extract HITL approval
    metadata (policy name, approval message, required tools).

    Args:
        db_path: Path to the cuga.db SQLite database.
        output_path: Optional path to write the converted trace JSON.
            If None, a timestamped file is created in ./converted_traces/.
        thread_id: Optional thread_id to convert. If None, converts the
            most recently updated conversation.

    Returns:
        The converted AgentDialogueTrace object.
    """
    if not os.path.exists(db_path):
        raise FileNotFoundError(f"Database not found: {db_path}")

    conn = sqlite3.connect(db_path)
    try:
        if thread_id:
            cursor = conn.execute(
                "SELECT thread_id, agent_id, messages FROM conversation_history "
                "WHERE thread_id = ? ORDER BY updated_at DESC LIMIT 1",
                (thread_id,),
            )
        else:
            cursor = conn.execute(
                "SELECT thread_id, agent_id, messages FROM conversation_history "
                "ORDER BY updated_at DESC LIMIT 1"
            )
        row = cursor.fetchone()
        if row is None:
            raise ValueError(
                "No conversation records found in the database. "
                "The conversation_history table is empty."
            )
        thread_id, agent_id, messages_json = row

        # Extract HITL approval infos from stream_events (same thread)
        hitl_infos: List[HITLApprovalInfo] = []
        tool_call_outputs_by_turn: Optional[List[List[tuple]]] = None
        turn_metrics_by_turn: Optional[List[Optional[dict]]] = None
        try:
            se_cursor = conn.execute(
                "SELECT events FROM stream_events WHERE thread_id = ?",
                (thread_id,),
            )
            se_row = se_cursor.fetchone()
            if se_row:
                stream_events = json.loads(se_row[0])
                hitl_infos = _extract_hitl_approval_infos_from_stream(stream_events)
                # Extract per-execution ordered tool call outputs
                tool_call_outputs_by_turn = _extract_tool_call_outputs_from_stream(
                    stream_events
                )
                # Extract per-turn latency + token totals
                turn_metrics_by_turn = _extract_turn_metrics_from_stream(
                    stream_events
                )
        except Exception:
            pass  # stream_events may not exist or be empty

        # Fallback: if no stream_events, try agent_configs policy
        if not hitl_infos:
            hitl_infos = _extract_hitl_approval_infos_from_agent_config(
                db_path, agent_id or "cuga-default"
            )

        # stream_events may only store the latest graph invocation's events,
        # so not all HITL gates are covered. Count HITL gates in the trace
        # and fill any gaps by repeating the known policy info.
        trace_messages = json.loads(messages_json)
        hitl_gate_count = sum(
            1 for m in trace_messages
            if m["role"] == "user" and m.get("metadata", {}).get("hitl", False)
        )
        if hitl_infos and len(hitl_infos) < hitl_gate_count:
            # Use the first known info as template for remaining gates
            template = hitl_infos[0]
            while len(hitl_infos) < hitl_gate_count:
                hitl_infos.append(template)
    finally:
        conn.close()

    trace_messages = json.loads(messages_json)
    dialogue_trace = convert_trace_to_agent_dialogue(
        trace_messages, hitl_infos,
        tool_call_outputs_by_turn=tool_call_outputs_by_turn,
        turn_metrics_by_turn=turn_metrics_by_turn,
    )
    # Stamp the DB thread_id so the trace ties back to its conversation_history /
    # stream_events rows and its sandbox workspace (thread_id == workspace id).
    dialogue_trace.thread_id = thread_id

    # Determine output path
    if output_path is None:
        os.makedirs(_DEFAULT_OUTPUT_DIR, exist_ok=True)
        timestamp = datetime.now().strftime("%Y-%m-%dT%H-%M-%S")
        thread_prefix = thread_id if thread_id else "unknown"
        output_path = os.path.join(
            _DEFAULT_OUTPUT_DIR, f"trace_{timestamp}_{thread_prefix}.json"
        )

    with open(output_path, "w") as f:
        json.dump(asdict(dialogue_trace), f, indent=2, default=str)

    print(f"Converted trace written to: {output_path}")
    return dialogue_trace


def convert_all_traces_from_db(
    db_path: str = _DEFAULT_DB_PATH,
) -> List[AgentDialogueTrace]:
    """
    Convert the latest conversation for each unique thread_id in the database.

    Each trace is written to a separate file with a thread_id prefix:
        converted_traces/trace_<thread_id[:8]>_<timestamp>.json

    Args:
        db_path: Path to the cuga.db SQLite database.

    Returns:
        List of converted AgentDialogueTrace objects.
    """
    if not os.path.exists(db_path):
        raise FileNotFoundError(f"Database not found: {db_path}")

    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.execute(
            "SELECT DISTINCT thread_id FROM conversation_history"
        )
        thread_ids = [row[0] for row in cursor.fetchall()]
    finally:
        conn.close()

    if not thread_ids:
        raise ValueError("No conversation records found in the database.")

    print(f"Found {len(thread_ids)} unique thread(s) in database.")
    traces = []
    for tid in thread_ids:
        try:
            trace = convert_trace_from_db(db_path, thread_id=tid)
            traces.append(trace)
        except Exception as e:
            print(f"  [SKIP] thread {tid}: {e}")

    return traces


# ─── CLI entry point ─────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys

    # Check for --db-path override
    db_path = _DEFAULT_DB_PATH
    args = [a for a in sys.argv[1:] if a != "--db"]
    if "--db-path" in sys.argv:
        db_path_idx = sys.argv.index("--db-path") + 1
        if db_path_idx < len(sys.argv):
            db_path = sys.argv[db_path_idx]
            args = [a for a in args if a != "--db-path" and a != db_path]

    try:
        traces = convert_all_traces_from_db(db_path)
        for trace in traces:
            print_trace_summary(trace)
            print()
    except (FileNotFoundError, ValueError) as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
