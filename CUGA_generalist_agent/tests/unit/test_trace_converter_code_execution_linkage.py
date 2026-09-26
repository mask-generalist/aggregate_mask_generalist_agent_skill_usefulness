"""Verify code_execution / named-tool output linkage in trace_converter.

Covers the fix where the runtime records an ordered, interleaved timeline of
``(tool_name, output)`` entries in ``_tool_call_outputs`` — including
``("code_execution", stdout_segment)`` entries for the pure-code stdout between
tool calls. Strategy 0 in ``_assign_execution_outputs`` must match NAMED tools
positionally while never consuming code_execution entries (which don't line up
1:1 with code_execution steps), leaving code_execution steps to the raw-text
gap-filler.

Regression targets:
  * Bug A — a leading/interleaved code_execution entry must not strand a named
    tool (it previously early-stopped the scan via ``future_tool_names``).
  * Bug B — surplus in-block code_execution entries must not be grabbed by a
    later code_execution step, nor corrupt a named tool.
  * Old-format rows (named-only outputs, no code_execution entries) still link.
"""

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from trace_converter import Step, _assign_execution_outputs


def _step(step_id: str, tool: str) -> Step:
    return Step(id=step_id, parent_ids=[], tool=tool)


def test_named_tool_links_despite_leading_code_execution_entry():
    """Bug A: a code_execution entry before the named tool output must not
    strand the named tool step."""
    steps = [_step("s1", "get_x")]
    # Runtime timeline: prints happened before the tool call in the same block,
    # then the tool ran.
    tool_call_outputs = [
        ("code_execution", "starting up\n"),
        ("get_x", {"value": 42}),
    ]
    _assign_execution_outputs(
        output_content="",
        steps=steps,
        step_var_map={},
        step_internal_vars={},
        stream_variables=None,
        tool_call_outputs=tool_call_outputs,
    )
    assert steps[0].tool_output == {"value": 42}


def test_named_tool_links_with_interleaved_code_execution_entries():
    """Bug A variant: [named tool step] with code_execution entries on BOTH
    sides of the tool output; the named tool must still get its own output."""
    steps = [_step("s1", "get_x")]
    tool_call_outputs = [
        ("code_execution", "before\n"),
        ("get_x", {"value": 1}),
        ("code_execution", "after\n"),
    ]
    _assign_execution_outputs(
        output_content="",
        steps=steps,
        step_var_map={},
        step_internal_vars={},
        stream_variables=None,
        tool_call_outputs=tool_call_outputs,
    )
    assert steps[0].tool_output == {"value": 1}


def test_two_named_tools_link_in_order_with_code_segments_between():
    """Named tools separated by code_execution entries still map in order."""
    steps = [_step("s1", "get_a"), _step("s2", "get_b")]
    tool_call_outputs = [
        ("get_a", {"a": 1}),
        ("code_execution", "intermediate print\n"),
        ("get_b", {"b": 2}),
    ]
    _assign_execution_outputs(
        output_content="",
        steps=steps,
        step_var_map={},
        step_internal_vars={},
        stream_variables=None,
        tool_call_outputs=tool_call_outputs,
    )
    assert steps[0].tool_output == {"a": 1}
    assert steps[1].tool_output == {"b": 2}


def test_surplus_in_block_code_execution_does_not_corrupt_named_tool():
    """Bug B: a surplus code_execution entry from a tool's own block (no
    corresponding step) must not be assigned to a named tool step, and must not
    displace the real named-tool output."""
    # Steps: get_x, then a trailing pure-logic block (code_execution step).
    steps = [_step("s1", "get_x"), _step("s2", "code_execution")]
    tool_call_outputs = [
        ("get_x", {"value": 7}),
        ("code_execution", "in-block print from get_x's block\n"),
        ("code_execution", "trailing pure-logic output\n"),
    ]
    _assign_execution_outputs(
        output_content="",
        steps=steps,
        step_var_map={},
        step_internal_vars={},
        stream_variables=None,
        tool_call_outputs=tool_call_outputs,
    )
    # Named tool keeps its own output.
    assert steps[0].tool_output == {"value": 7}
    # code_execution step is NOT positionally assigned a code_execution entry by
    # Strategy 0 (that is unsafe); it flows to the raw-text gap-filler. With no
    # raw text here it simply stays unmatched — the point is it must never grab
    # a code_execution entry as if it were a native tool_output object.
    assert steps[1].tool_output != "in-block print from get_x's block\n"


def test_old_format_named_only_outputs_still_link():
    """Backward compat: rows recorded before the interleaving change contain
    only named-tool entries and must still link 1:1."""
    steps = [_step("s1", "get_a"), _step("s2", "get_b")]
    tool_call_outputs = [
        ("get_a", {"a": 1}),
        ("get_b", {"b": 2}),
    ]
    _assign_execution_outputs(
        output_content="",
        steps=steps,
        step_var_map={},
        step_internal_vars={},
        stream_variables=None,
        tool_call_outputs=tool_call_outputs,
    )
    assert steps[0].tool_output == {"a": 1}
    assert steps[1].tool_output == {"b": 2}


def test_code_execution_step_filled_from_raw_text_gap():
    """End-to-end for a single pure-logic block: the code_execution step should
    receive its stdout via the raw-text fallback anchored on the named tool."""
    steps = [_step("s1", "get_x"), _step("s2", "code_execution")]
    # get_x prints its dict output, then the pure-logic block prints a line.
    output_content = (
        "Execution output:\n"
        "{'value': 99}\n"
        "computed summary line\n"
    )
    tool_call_outputs = [
        ("get_x", {"value": 99}),
        ("code_execution", "computed summary line\n"),
    ]
    _assign_execution_outputs(
        output_content=output_content,
        steps=steps,
        step_var_map={},
        step_internal_vars={},
        stream_variables=None,
        tool_call_outputs=tool_call_outputs,
    )
    assert steps[0].tool_output == {"value": 99}
    # The code_execution step should be filled from the gap after the anchor.
    assert steps[1].tool_output is not None
    assert "computed summary line" in str(steps[1].tool_output)