"""Parse YAML test cases into typed criteria for conversation and evaluation."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any

import yaml

from agent_inspect.models.metrics.agent_data_sample import SubGoal, SubGoalCategory
from agent_inspect.models.metrics.skill_data_sample import SkillCall
from agent_inspect.models.metrics.capability_data_sample import (
    ExpectedCapability,
    CapabilityOutput,
)


@dataclass
class TestCaseCriteria:
    case_id: str
    task_summary: str
    max_turns: int
    sub_goals: list[SubGoal] = field(default_factory=list)
    expected_skill_calls: list[SkillCall] = field(default_factory=list)
    expected_capabilities: list[ExpectedCapability] = field(default_factory=list)


# ── Internal helpers ─────────────────────────────────────────────────────────

def _find_dynamic_step(case: dict[str, Any]) -> dict[str, Any]:
    for step in case.get("test_steps", []):
        if step.get("type") == "dynamic_conversation":
            return step
    raise ValueError("No dynamic_conversation step found in test case")


# skill0_artifacts is the base agent (no skill) — always strip it.
_IGNORED_SKILLS = {"skill0_artifacts"}


def _parse_skills(step: dict[str, Any]) -> list[SkillCall]:
    skill_val = step.get("skill_validations") or {}
    return [
        SkillCall(skill_id=s["skill"], skill_name=s["skill"])
        for s in (skill_val.get("expected_skill_invocations") or [])
        if s.get("skill") and s["skill"] not in _IGNORED_SKILLS
    ]


def _parse_capabilities(step: dict[str, Any]) -> list[ExpectedCapability]:
    cap_val = step.get("capability_validations") or {}
    caps = []
    for c in cap_val.get("expected_capabilities") or []:
        desc = c.get("description")
        if not desc:
            raise ValueError(f"Expected capability missing 'description': {c}")
        raw_out = c.get("output")
        cap_out = CapabilityOutput(check=raw_out["check"]) if raw_out and raw_out.get("check") else None
        caps.append(ExpectedCapability(
            capability_name=c.get("name", None),
            description=desc,
            expected_output=cap_out,
        ))
    return caps


# ── Public API ───────────────────────────────────────────────────────────────

def parse_test_case(path: str) -> TestCaseCriteria:
    """Load a YAML test case and return typed criteria."""
    with open(path, "r", encoding="utf-8") as f:
        case = yaml.safe_load(f)

    case_id = str(case.get("id", os.path.splitext(os.path.basename(path))[0]))
    step = _find_dynamic_step(case)

    sub_goals = [
        SubGoal(details=v["check"], category=SubGoalCategory.OUTPUT_RULE)
        for v in (step.get("agent_response_validations") or [])
        if v.get("check")
    ]

    return TestCaseCriteria(
        case_id=case_id,
        task_summary=(step.get("user_agent") or {}).get("task_summary", ""),
        max_turns=step.get("max_turns", 10),
        sub_goals=sub_goals,
        expected_skill_calls=_parse_skills(step),
        expected_capabilities=_parse_capabilities(step),
    )


def _is_case_file(path: str) -> bool:
    """True if the YAML has a dynamic_conversation test step (a real test case).

    Skips sidecar YAMLs like skills_config.yaml that live in the same directory.
    """
    try:
        with open(path, "r", encoding="utf-8") as f:
            case = yaml.safe_load(f)
    except (yaml.YAMLError, OSError):
        return False
    if not isinstance(case, dict):
        return False
    return any(
        step.get("type") == "dynamic_conversation"
        for step in case.get("test_steps", [])
        if isinstance(step, dict)
    )


def iter_case_files(path: str) -> list[str]:
    """Return YAML case files for a single file, or all under a directory (recursive)."""
    if os.path.isfile(path):
        return [path]
    if os.path.isdir(path):
        found = []
        for root, _dirs, files in os.walk(path):
            for f in files:
                if f.endswith((".yaml", ".yml")):
                    full = os.path.join(root, f)
                    if _is_case_file(full):
                        found.append(full)
        if not found:
            raise ValueError(f"No test-case .yaml files found under {path}")
        return sorted(found)
    raise FileNotFoundError(f"Not a file or directory: {path}")
