"""Convert test_cases.json to individual YAML test case files."""

from __future__ import annotations

import argparse
import json
import re

from pathlib import Path

import yaml


def _slugify(text: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_]", "_", text).strip("_")


def _summarize_expected_output(expected_output: dict) -> str:
    """Produce a check string from expected_output, including real DB values."""
    if not expected_output:
        return ""
    return json.dumps(expected_output)


def convert(tc: dict) -> dict:
    skills_seen: list[str] = []
    cap_validations = []
    for cap in tc.get("expected_capabilities", []):
        skill = cap.get("skill", "")
        if skill and skill not in skills_seen:
            skills_seen.append(skill)

        entry: dict = {
            "name": cap["name"],
            "description": cap["description"],
        }
        expected_output = cap.get("expected_output")
        if expected_output:
            entry["output"] = {
                "check": _summarize_expected_output(expected_output)
            }
        cap_validations.append(entry)

    test_step = {
        "type": "dynamic_conversation",
        "user_agent": {
            "task_summary": tc["task_summary"],
        },
        "max_turns": 10,
        "skill_validations": {
            "expected_skill_invocations": [{"skill": s} for s in skills_seen],
        },
        "agent_response_validations": [
            {"check": sg["description"]} for sg in tc.get("subgoals", [])
        ],
        "capability_validations": {
            "expected_capabilities": cap_validations,
        },
    }

    return {
        "id": tc["id"],
        "description": tc["task_summary"],
        "test_steps": [test_step],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Convert test_cases.json to YAML files")
    parser.add_argument("--input", required=True, help="Path to test_cases.json")
    parser.add_argument("--out-dir", required=True, help="Output directory for YAML files")
    args = parser.parse_args()

    test_cases = json.loads(Path(args.input).read_text())
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    for tc in test_cases:
        converted = convert(tc)
        filename = out_dir / f"{tc['id']}.yaml"
        with open(filename, "w") as f:
            yaml.dump(converted, f, allow_unicode=True, sort_keys=False, default_flow_style=False)
        print(f"  wrote {filename}")

    print(f"\n{len(test_cases)} YAML files → {out_dir}")


if __name__ == "__main__":
    main()
