"""Evaluate raw trace JSONs using the agent-inspect subgoal validator.

Produces an output JSON that mirrors the input samples file structure,
keeping: model, n_samples, samples (trial, capability, is_completed,
trace_path, testcase_path) and adding judge_explanations per sample.

Usage:
    PYTHONPATH="agent_quality_inspect/src:pi_agent:." python rebuttal/evaluate_traces_v2.py \
        --samples-json rebuttal/sampled_traces_testcases/sample_fuzzy_traces_pi_opus4_6.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

import yaml

from agent_inspect.metrics.validator import SubGoalCompletionValidator
from agent_inspect.metrics.scorer.templates import (
    DEFAULT_MODEL_GRADED_FACT_DYNAMIC_SUMMARY_TEMPLATE_ONE_SUBGOAL,
)
from agent_inspect.metrics.constants import (
    INCLUDE_JUDGE_EXPLANATION,
    INCLUDE_VALIDATION_RESULTS,
    INCLUDE_PROMPT_SENT_TO_LLMJ,
    OPTIMIZE_JUDGE_TRIALS,
    TEMPLATE_SUBGOAL,
    NUM_JUDGE_TRIALS,
)
from agent_inspect.models.metrics.agent_data_sample import SubGoal
from agent_inspect.models.metrics.agent_trace import (
    AgentDialogueTrace,
    AgentResponse,
    Step,
    TurnTrace,
)
from agent_inspect.models.metrics.agent_data_sample import ToolInputParameter
from agent_inspect.models.metrics.skill_data_sample import SkillCall
from agent_inspect.clients import LiteLLMClient

logger = logging.getLogger("rebuttal.evaluate_traces_v2")


# ── Sample entry ─────────────────────────────────────────────────────────────

@dataclass
class SampleEntry:
    trace_path: Path
    testcase_path: Path
    capability: str
    setting: str
    system: str
    task_id: str
    trial: str
    grade: str
    is_completed: bool


def load_samples(samples_json: Path, base_dir: Path) -> tuple[Dict[str, Any], List[SampleEntry]]:
    """Load samples from a sampled_traces_testcases JSON file.

    Returns the raw top-level dict (for model/n_samples metadata) and parsed SampleEntry list.
    """
    raw = json.loads(samples_json.read_text())

    samples_raw = raw.get("samples")
    if not samples_raw:
        raise ValueError(f"No 'samples' array in {samples_json}")

    samples = []
    for i, s in enumerate(samples_raw):
        for field in ("trace_path", "testcase_path", "capability",
                      "setting", "system", "task_id", "trial", "grade"):
            if field not in s:
                raise ValueError(f"Sample {i} missing required field '{field}'")

        trace_path = base_dir / s["trace_path"]
        if not trace_path.exists():
            raise FileNotFoundError(f"Trace file not found: {trace_path}")

        testcase_path = base_dir / s["testcase_path"]
        if not testcase_path.exists():
            raise FileNotFoundError(f"Testcase YAML not found: {testcase_path}")

        samples.append(SampleEntry(
            trace_path=trace_path,
            testcase_path=testcase_path,
            capability=s["capability"],
            setting=s["setting"],
            system=s["system"],
            task_id=s["task_id"],
            trial=s["trial"],
            grade=s["grade"],
            is_completed=s.get("is_completed", False),
        ))

    return raw, samples


# ── Trace loading ────────────────────────────────────────────────────────────

def load_trace_from_json(path: Path) -> AgentDialogueTrace:
    """Deserialize a trace JSON file into an AgentDialogueTrace dataclass."""
    raw = json.loads(path.read_text())
    token_keys = (
        "input_token_consumption", "output_token_consumption",
        "reasoning_token_consumption", "total_token_consumption",
    )
    totals = {k: 0 for k in token_keys}

    raw_turns = raw.get("turns")
    if not raw_turns:
        raise ValueError(f"Trace file {path} has no 'turns'")

    turns = []
    for t in raw_turns:
        for k in token_keys:
            totals[k] += t.get(k) or 0

        if "id" not in t:
            raise ValueError(f"Turn missing 'id' in {path}")
        if "agent_input" not in t:
            raise ValueError(f"Turn {t['id']} missing 'agent_input' in {path}")

        steps = []
        for s in t.get("steps") or []:
            if "id" not in s:
                raise ValueError(f"Step missing 'id' in turn {t['id']} of {path}")
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
        agent_response = (
            AgentResponse(response=resp["response"], status_code=resp.get("status_code"))
            if resp.get("response") is not None
            else None
        )

        turns.append(TurnTrace(
            id=t["id"],
            agent_input=t["agent_input"],
            agent_response=agent_response,
            from_id=t.get("from_id"),
            steps=steps,
            latency_in_ms=t.get("latency_in_ms"),
        ))

    return AgentDialogueTrace(turns=turns, metadata=totals)


# ── Subgoal derivation from YAML expected_capabilities ───────────────────────

def capability_to_subgoal(cap: Dict[str, Any]) -> SubGoal:
    """Turn a single expected_capabilities entry into a SubGoal."""
    name = cap.get("name")
    if not name:
        raise ValueError(f"Capability entry missing 'name': {cap}")
    description = cap.get("description")
    if not description:
        raise ValueError(f"Capability '{name}' missing 'description': {cap}")

    output_block = cap.get("output")
    if not output_block or "check" not in output_block:
        raise ValueError(f"Capability '{name}' missing 'output.check': {cap}")
    output_check = output_block["check"]

    details = f"The agent should use the '{name}' capability to {description}"
    if not details.endswith("."):
        details += "."
    details += f" The output contain: {output_check}"

    return SubGoal(details=details)


def parse_yaml(yaml_path: Path) -> tuple[List[Dict[str, Any]], str]:
    """Parse a tc_*.yaml and return (capabilities_list, user_instruction)."""
    raw = yaml.safe_load(yaml_path.read_text())

    test_steps = raw.get("test_steps")
    if not test_steps:
        raise ValueError(f"YAML {yaml_path} has no 'test_steps'")

    user_instruction = None
    for step in test_steps:
        ua = step.get("user_agent") or {}
        if ua.get("task_summary"):
            user_instruction = ua["task_summary"]
            break
    if not user_instruction:
        raise ValueError(
            f"YAML {yaml_path} has no 'task_summary' in any test_step's user_agent"
        )

    capabilities: List[Dict[str, Any]] = []
    for step in test_steps:
        caps_block = step.get("capability_validations") or {}
        capabilities.extend(caps_block.get("expected_capabilities") or [])

    if not capabilities:
        raise ValueError(f"No expected_capabilities found in {yaml_path}")

    return capabilities, user_instruction


def subgoal_for_capability(
    yaml_path: Path, capability_name: str,
) -> tuple[SubGoal, str]:
    """Extract a single capability by name from a YAML and return (subgoal, user_instruction)."""
    capabilities, user_instruction = parse_yaml(yaml_path)

    matching = [c for c in capabilities if c.get("name") == capability_name]
    if not matching:
        available = [c.get("name") for c in capabilities]
        raise ValueError(
            f"Capability '{capability_name}' not found in {yaml_path}. "
            f"Available: {available}"
        )

    return capability_to_subgoal(matching[0]), user_instruction


# ── Evaluation ───────────────────────────────────────────────────────────────

async def evaluate_trace(
    trace: AgentDialogueTrace,
    sub_goal: SubGoal,
    user_instruction: str,
    llm_client: LiteLLMClient,
    num_judge_trials: int,
) -> Dict[str, Any]:
    """Run subgoal validation on a single trace. Returns is_completed + explanations."""
    validator_config = {
        INCLUDE_VALIDATION_RESULTS: True,
        INCLUDE_JUDGE_EXPLANATION: True,
        INCLUDE_PROMPT_SENT_TO_LLMJ: True,
        OPTIMIZE_JUDGE_TRIALS: False,
        TEMPLATE_SUBGOAL: DEFAULT_MODEL_GRADED_FACT_DYNAMIC_SUMMARY_TEMPLATE_ONE_SUBGOAL,
        NUM_JUDGE_TRIALS: num_judge_trials,
    }
    goal_validator = SubGoalCompletionValidator(
        llm_client=llm_client, config=validator_config,
    )

    result = await goal_validator.validate_dynamic(
        turn_traces=trace.turns,
        sub_goal=sub_goal,
        user_instruction=user_instruction,
    )

    return {
        "is_completed": result.is_completed,
        "details": result.sub_goal.details,
        "explanations": result.explanations,
    }


async def run_evaluation(
    samples: List[SampleEntry],
    judge_model: str,
    judge_max_tokens: int,
    num_judge_trials: int,
    max_workers: int,
) -> List[Dict[str, Any]]:
    """Evaluate all samples concurrently. Returns per-sample result dicts."""
    sem = asyncio.Semaphore(max_workers)
    llm_client = LiteLLMClient(model=judge_model, max_tokens=judge_max_tokens)

    async def _eval_one(sample: SampleEntry) -> Dict[str, Any]:
        async with sem:
            sub_goal, user_instruction = subgoal_for_capability(
                sample.testcase_path, sample.capability,
            )
            logger.info(
                "  [%s/%s] %s/%s  capability=%s",
                sample.setting, sample.system, sample.task_id,
                sample.trial, sample.capability,
            )

            trace = load_trace_from_json(sample.trace_path)
            result = await evaluate_trace(
                trace, sub_goal, user_instruction, llm_client, num_judge_trials,
            )
            logger.info(
                "    -> is_completed=%s", result["is_completed"],
            )
            return {
                "trial": sample.trial,
                "capability": sample.capability,
                "is_completed": result["is_completed"],
                "trace_path": str(sample.trace_path),
                "testcase_path": str(sample.testcase_path),
                "judge_explanations": result["explanations"],
            }

    return list(await asyncio.gather(*[_eval_one(s) for s in samples]))


# ── CLI ──────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Evaluate trace JSONs using agent-inspect subgoal validator (v2 — structured output)"
    )
    parser.add_argument(
        "--samples-json", required=True,
        help="Samples JSON file (from sampled_traces_testcases/). "
             "Each sample specifies trace_path, testcase_path, and capability.",
    )
    parser.add_argument(
        "--base-dir", default=".",
        help="Base directory for resolving relative paths in samples JSON (default: cwd)",
    )
    parser.add_argument("--judge-model", default="azure/gpt-5.4")
    parser.add_argument("--judge-max-tokens", type=int, default=4096)
    parser.add_argument("--num-judge-trials", type=int, default=5)
    parser.add_argument("--max-workers", type=int, default=4)
    parser.add_argument("--output", "-o", default=None, help="Output JSON path")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(message)s",
        handlers=[logging.StreamHandler(sys.stdout)],
    )

    samples_path = Path(args.samples_json)
    if not samples_path.exists():
        raise FileNotFoundError(f"Samples JSON not found: {samples_path}")

    base_dir = Path(args.base_dir).resolve()
    raw_input, samples = load_samples(samples_path, base_dir)
    logger.info("Loaded %d sample(s) from %s", len(samples), samples_path.name)

    logger.info(
        "Judge: model=%s  max_tokens=%d  trials=%d",
        args.judge_model, args.judge_max_tokens, args.num_judge_trials,
    )

    results = asyncio.run(run_evaluation(
        samples=samples,
        judge_model=args.judge_model,
        judge_max_tokens=args.judge_max_tokens,
        num_judge_trials=args.num_judge_trials,
        max_workers=args.max_workers,
    ))

    # Summary
    completed = sum(1 for r in results if r["is_completed"])
    logger.info("\n%s", "=" * 60)
    logger.info("%d evaluated | %d completed | %d not completed",
                len(results), completed, len(results) - completed)
    logger.info("=" * 60)

    output_doc = {
        "model": raw_input.get("model"),
        "n_samples": raw_input.get("n_samples"),
        "judge_model": args.judge_model,
        "judge_max_tokens": args.judge_max_tokens,
        "num_judge_trials": args.num_judge_trials,
        "samples": results,
    }

    model_tag = raw_input.get("model", "unknown")
    output_path = args.output or f"rebuttal/rebuttal_eval_{model_tag}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    Path(output_path).write_text(json.dumps(output_doc, indent=2, default=str))
    logger.info("Results saved to %s", output_path)


if __name__ == "__main__":
    main()
