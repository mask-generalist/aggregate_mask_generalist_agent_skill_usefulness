#!/usr/bin/env python3
"""
Convert CUGA agent trace (flat chat messages) to OpenTelemetry span format.

Usage:
    python convert_trace_to_otel.py input.json [output.json]

If output path is not specified, writes to <input_stem>_otel.json.
"""

import argparse
import json
import re
import uuid
import os
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional


def generate_trace_id() -> str:
    """Generate a 32-character hex trace ID."""
    return uuid.uuid4().hex


def generate_span_id() -> str:
    """Generate a 16-character hex span ID."""
    return uuid.uuid4().hex[:16]


def timestamp_to_nanos(ts_str: str) -> int:
    """Convert ISO 8601 timestamp string to Unix nanoseconds."""
    dt = datetime.fromisoformat(ts_str)
    return int(dt.timestamp() * 1_000_000_000)


def parse_code_blocks(content: str) -> List[Dict]:
    """
    Extract ```python code blocks from assistant content.
    Returns list of dicts with 'code' and 'tool_name' and 'tool_args'.
    """
    pattern = r"```python\n(.*?)```"
    blocks = re.findall(pattern, content, re.DOTALL)

    results = []
    for block in blocks:
        tool_info = extract_tool_call(block)
        results.append({
            "code": block.strip(),
            "tool_name": tool_info["name"],
            "tool_args": tool_info["args"],
        })
    return results


def extract_tool_call(code_block: str) -> dict:
    """
    Extract the tool name and arguments from an await call in a code block.
    Matches patterns like: await load_skill("acme_vendor_onboarding")
    or: result = await run_command(...)
    """
    # Match await function_name(...)
    pattern = r"await\s+(\w+)\((.*?)\)"
    matches = re.findall(pattern, code_block, re.DOTALL)

    if matches:
        # Take the first await call as the primary tool
        name, args = matches[0]
        # Clean up args
        args = args.strip()
        return {"name": name, "args": args}

    # Fallback: look for any function call pattern that isn't a builtin
    skip = {"print", "format", "str", "int", "float", "len", "range",
            "enumerate", "zip", "list", "dict", "set", "tuple",
            "append", "extend", "get", "items", "keys", "values",
            "lower", "upper", "strip", "split", "join", "replace",
            "round", "abs", "max", "min", "sorted", "filter", "map",
            "isinstance", "type", "hasattr", "getattr", "setattr",
            "open", "close", "read", "write", "seek", "flush",
            "add", "remove", "pop", "clear", "copy", "update",
            "startswith", "endswith", "find", "index", "count",
            "encode", "decode", "insert", "break",
            "loads", "dumps", "load", "dump", "json"}
    pattern = r"(\w+)\((.*?)\)"
    matches = re.findall(pattern, code_block, re.DOTALL)
    if matches:
        for name, args in matches:
            if name not in skip and not name.startswith("_"):
                return {"name": name, "args": args.strip()}

    # If no meaningful function call found, label it as python_exec
    return {"name": "python_exec", "args": ""}


def extract_reasoning(content: str) -> str:
    """Extract the non-code-block text from assistant content as reasoning."""
    # Remove code blocks
    cleaned = re.sub(r"```python\n.*?```", "", content, flags=re.DOTALL)
    # Clean up excess whitespace
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()
    return cleaned


def split_execution_output(content: str) -> list[str]:
    """
    Split a user message containing execution outputs into individual results.
    Handles cases where output is prefixed with 'Execution output:' or similar markers.
    """
    if not content:
        return []

    # Check if it starts with "Execution output:"
    if content.startswith("Execution output:"):
        content = content[len("Execution output:"):].strip()

    # Try to split on common separators between tool outputs
    # Look for patterns like "---" or double newlines followed by result markers
    parts = re.split(r"\n---+\n", content)
    if len(parts) > 1:
        return [p.strip() for p in parts if p.strip()]

    # If no clear separators, return the whole thing as one result
    return [content]


def estimate_tokens(text: str) -> int:
    """Rough token estimate (1 token ≈ 4 characters)."""
    return max(1, len(text) // 4)


def convert_trace(input_path: str, output_path: Optional[str] = None) -> str:
    """
    Convert a CUGA agent trace file to OTel span format.

    Args:
        input_path: Path to the source trace JSON file
        output_path: Path for the output file. If None, derives from input_path.

    Returns:
        Path to the output file.
    """
    with open(input_path, "r") as f:
        messages = json.load(f)

    if output_path is None:
        stem = Path(input_path).stem
        output_path = str(Path(input_path).parent / f"{stem}_otel.json")

    # Generate trace-wide identifiers
    trace_id = generate_trace_id()
    conversation_id = str(uuid.uuid4())
    root_span_id = generate_span_id()

    # Determine time boundaries from message timestamps
    timestamps = [timestamp_to_nanos(m["timestamp"]) for m in messages]
    trace_start = min(timestamps)
    trace_end = max(timestamps)

    # If timestamps are too close together (< 1 second total), spread them out
    # to create a realistic-looking timeline
    total_duration_ns = trace_end - trace_start
    if total_duration_ns < 1_000_000_000:  # less than 1 second
        # Spread across 10 seconds
        total_duration_ns = 10_000_000_000
        trace_end = trace_start + total_duration_ns

    # Extract metadata from source
    metadata = messages[0].get("metadata", {}) if messages else {}
    message_type = metadata.get("message_type", "chat_messages")

    # Collect all spans
    spans = []

    # --- Root span: invoke_agent ---
    root_span = {
        "traceId": trace_id,
        "spanId": root_span_id,
        "parentSpanId": None,
        "name": "invoke_agent",
        "kind": "SPAN_KIND_INTERNAL",
        "startTimeUnixNano": trace_start,
        "endTimeUnixNano": trace_end,
        "durationMs": round(total_duration_ns / 1_000_000, 6),
        "status": {"code": "STATUS_CODE_UNSET", "message": ""},
        "scope": "cuga-agent",
        "resource": {"service.name": "cuga-agent-service"},
        "attributes": {
            "gen_ai.operation.name": "invoke_agent",
            "gen_ai.agent.name": "invoke_agent",
            "gen_ai.conversation.id": conversation_id,
            "cuga.message_type": message_type,
        },
        "events": [],
    }
    spans.append(root_span)

    # Process messages in pairs/groups
    # Track assistant messages and their corresponding execution outputs
    assistant_messages = []
    iteration = 0
    time_cursor = trace_start

    # Calculate time budget per message pair
    num_assistant_msgs = sum(1 for m in messages if m["role"] == "assistant")
    time_per_step_ns = total_duration_ns // max(num_assistant_msgs, 1)

    # Build conversation history for input_messages tracking
    conversation_history = []

    for i, msg in enumerate(messages):
        if msg["role"] == "user":
            # Add to conversation history
            conversation_history.append({
                "role": "user",
                "content": msg["content"],
            })

            # Check if this user message follows an assistant message
            # (making it an execution output)
            if i > 0 and messages[i - 1]["role"] == "assistant":
                # This is a tool result / execution output
                # Already handled when processing the assistant message
                pass
            continue

        if msg["role"] == "assistant":
            iteration += 1
            content = msg["content"]

            # Parse code blocks as tool calls
            code_blocks = parse_code_blocks(content)
            reasoning = extract_reasoning(content)
            has_tool_calls = len(code_blocks) > 0

            # Determine if this is the final answer
            is_final = True
            for j in range(i + 1, len(messages)):
                if messages[j]["role"] == "assistant":
                    is_final = False
                    break

            # Time allocation for this step
            step_start = time_cursor
            step_end = step_start + time_per_step_ns
            time_cursor = step_end

            # --- agent_step span ---
            step_span_id = generate_span_id()
            step_span = {
                "traceId": trace_id,
                "spanId": step_span_id,
                "parentSpanId": root_span_id,
                "name": "agent_step",
                "kind": "SPAN_KIND_INTERNAL",
                "startTimeUnixNano": step_start,
                "endTimeUnixNano": step_end,
                "durationMs": round(time_per_step_ns / 1_000_000, 6),
                "status": {"code": "STATUS_CODE_UNSET", "message": ""},
                "scope": "cuga-agent",
                "resource": {"service.name": "cuga-agent-service"},
                "attributes": {
                    "gen_ai.operation.name": "agent_step",
                    "cuga.agent.iteration": iteration,
                    "cuga.agent.tool_calls_requested": len(code_blocks),
                    "cuga.agent.reasoning": reasoning,
                    "cuga.agent.has_final_answer": is_final,
                },
                "events": [],
            }
            spans.append(step_span)

            # --- chat span (LLM call) ---
            chat_start = step_start + (time_per_step_ns // 10)
            chat_end = step_end - (time_per_step_ns // 10)
            chat_duration_ns = chat_end - chat_start

            input_messages_json = json.dumps(conversation_history)
            finish_reason = "tool_calls" if has_tool_calls else "stop"

            chat_span = {
                "traceId": trace_id,
                "spanId": generate_span_id(),
                "parentSpanId": step_span_id,
                "name": "chat cuga-agent",
                "kind": "SPAN_KIND_CLIENT",
                "startTimeUnixNano": chat_start,
                "endTimeUnixNano": chat_end,
                "durationMs": round(chat_duration_ns / 1_000_000, 6),
                "status": {"code": "STATUS_CODE_UNSET", "message": ""},
                "scope": "cuga-agent",
                "resource": {"service.name": "cuga-agent-service"},
                "attributes": {
                    "gen_ai.operation.name": "chat",
                    "gen_ai.system": "cuga-agent",
                    "gen_ai.request.model": "cuga-agent",
                    "gen_ai.input.messages": input_messages_json,
                    "gen_ai.output.messages": content,
                    "gen_ai.response.finish_reasons": finish_reason,
                    "gen_ai.usage.input_tokens": estimate_tokens(input_messages_json),
                    "gen_ai.usage.output_tokens": estimate_tokens(content),
                    "gen_ai.response.choice.count": 1,
                },
                "events": [],
            }
            if has_tool_calls:
                chat_span["attributes"]["gen_ai.response.tool_call_count"] = len(code_blocks)
            spans.append(chat_span)

            # Add assistant message to conversation history
            conversation_history.append({
                "role": "assistant",
                "content": content,
            })

            # --- execute_tool spans ---
            # Get the next user message as execution output (if exists)
            next_user_content = ""
            if i + 1 < len(messages) and messages[i + 1]["role"] == "user":
                next_user_content = messages[i + 1]["content"]

            # Split execution output across tool calls
            tool_results = split_execution_output(next_user_content)

            for block_idx, block in enumerate(code_blocks):
                tool_start = step_end + (block_idx * (time_per_step_ns // (len(code_blocks) + 1) // 2))
                tool_duration_ns = time_per_step_ns // (len(code_blocks) + 1) // 3
                tool_end_time = tool_start + tool_duration_ns

                # Get matching result
                result = ""
                if block_idx < len(tool_results):
                    result = tool_results[block_idx]

                tool_call_id = f"cuga_{uuid.uuid4().hex[:24]}"

                tool_attributes = {
                    "gen_ai.operation.name": "execute_tool",
                    "gen_ai.tool.name": block["tool_name"],
                    "gen_ai.tool.call.id": tool_call_id,
                    "gen_ai.tool.call.arguments": json.dumps({"code": block["code"]}),
                    "gen_ai.tool.call.result": result,
                }

                # If this is a load_skill call, extract and surface the skill name
                if block["tool_name"] == "load_skill":
                    skill_match = re.search(
                        r'load_skill\(\s*["\']([^"\']+)["\']\s*\)', block["code"]
                    )
                    if skill_match:
                        tool_attributes["cuga.skill.name"] = skill_match.group(1)

                tool_span = {
                    "traceId": trace_id,
                    "spanId": generate_span_id(),
                    "parentSpanId": root_span_id,
                    "name": f"execute_tool {block['tool_name']}",
                    "kind": "SPAN_KIND_INTERNAL",
                    "startTimeUnixNano": tool_start,
                    "endTimeUnixNano": tool_end_time,
                    "durationMs": round(tool_duration_ns / 1_000_000, 6),
                    "status": {"code": "STATUS_CODE_UNSET", "message": ""},
                    "scope": "cuga-agent",
                    "resource": {"service.name": "cuga-agent-service"},
                    "attributes": tool_attributes,
                    "events": [],
                }
                spans.append(tool_span)

    # Update the root span end time to cover all child spans
    max_end = max(s["endTimeUnixNano"] for s in spans)
    spans[0]["endTimeUnixNano"] = max_end
    spans[0]["durationMs"] = round((max_end - spans[0]["startTimeUnixNano"]) / 1_000_000, 6)

    # Write output
    with open(output_path, "w") as f:
        json.dump(spans, f, indent=2)

    return output_path


def main():
    parser = argparse.ArgumentParser(
        description="Convert CUGA agent trace to OpenTelemetry span format"
    )
    parser.add_argument("input", help="Path to the source CUGA trace JSON file")
    parser.add_argument(
        "output",
        nargs="?",
        default=None,
        help="Path for the output OTel JSON file (default: <input_stem>_otel.json)",
    )
    args = parser.parse_args()

    if not os.path.exists(args.input):
        print(f"Error: Input file not found: {args.input}")
        return 1

    output_path = convert_trace(args.input, args.output)
    print(f"Converted trace written to: {output_path}")

    # Print summary
    with open(output_path) as f:
        spans = json.load(f)
    print(f"  Total spans: {len(spans)}")
    print(f"  Span types: {[s['name'] for s in spans]}")

    # Validate hierarchy
    span_ids = {s["spanId"] for s in spans}
    for s in spans:
        if s["parentSpanId"] is not None and s["parentSpanId"] not in span_ids:
            print(f"  WARNING: orphan span {s['name']} references missing parent {s['parentSpanId']}")

    return 0


if __name__ == "__main__":
    exit(main())
