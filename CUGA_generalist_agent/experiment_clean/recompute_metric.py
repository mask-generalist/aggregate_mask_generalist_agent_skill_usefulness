"""Recompute specific metrics in-place (or to an output dir) without touching others.

Extracts the individual metric computation logic from evaluate.py so that only
the requested metrics are recomputed (avoiding unnecessary LLM judge calls).

Usage:
    # Recompute skill_recall and skill_precision in-place for a job
    PYTHONPATH="../agent-inspect/src:." python -m experiment_clean.recompute_metric \
        /path/to/experiment_results/jobs/<job>/ \
        --metrics skill_recall skill_precision --n-trials 5

    # Same but write to a new directory
    PYTHONPATH="../agent-inspect/src:." python -m experiment_clean.recompute_metric \
        /path/to/experiment_results/jobs/<job>/ \
        --metrics skill_recall skill_precision --n-trials 5 \
        --output-dir /tmp/patched_results

    # Recompute for multiple jobs at once
    PYTHONPATH="../agent-inspect/src:." python -m experiment_clean.recompute_metric \
        /path/to/experiment_results/jobs/<job1>/ \
        /path/to/experiment_results/jobs/<job2>/ \
        --metrics capability_score --n-trials 5
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional

from agent_inspect.metrics.validator import SubGoalCompletionValidator
from agent_inspect.metrics.scorer import ProgressScore
from agent_inspect.metrics.scorer.templates import (
    DEFAULT_MODEL_GRADED_FACT_DYNAMIC_SUMMARY_TEMPLATE_ONE_SUBGOAL,
)
from agent_inspect.metrics.scorer.skill_precision import SkillPrecisionMetric
from agent_inspect.metrics.scorer.skill_recall import SkillRecallMetric
from agent_inspect.metrics.validator.capability_call_completion import (
    CapabilityCompletionValidator,
)
from agent_inspect.metrics.constants import (
    INCLUDE_JUDGE_EXPLANATION,
    INCLUDE_VALIDATION_RESULTS,
    INCLUDE_PROMPT_SENT_TO_LLMJ,
    OPTIMIZE_JUDGE_TRIALS,
    TEMPLATE_SUBGOAL,
    NUM_JUDGE_TRIALS,
)
from agent_inspect.models.metrics import EvaluationSample
from agent_inspect.clients import LiteLLMClient

from experiment_clean.config import (
    DEFAULT_RUNNER_CONFIG,
    JudgeConfig,
    load_runner_config,
    judge_config_from,
    silence_litellm,
    skills_from,
)
from experiment_clean.evaluate import (
    TrialEvalResult,
    aggregate_metrics,
    discover_trial_folders,
    _fmt,
    _is_trial_folder,
)
from experiment_clean.testcase import parse_test_case
from experiment_clean.trace import convert_trace, latest_trace, load_trace

silence_litellm()

logger = logging.getLogger("experiment_clean.recompute_metric")

# Metrics stored in per-trial eval_results.json (the keys evaluate_trial() returns).
TRIAL_LEVEL_METRICS = {
    "progress_rates",
    "skill_precision",
    "skill_recall",
    "capability_score",
    "total_tokens",
    "total_latency_ms",
    "tool_call_count",
}

# When a metric is recomputed, its companion detail array is also replaced.
_METRIC_COMPANIONS = {
    "progress_rates": ["subgoal_validations"],
    "capability_score": ["capability_validations"],
}

# Metrics that require LLM judge calls.
_JUDGE_METRICS = {"progress_rates", "capability_score"}


# ── Helpers ─────────────────────────────────────────────────────────────────


def _find_latest_eval_dir(trial_folder: Path) -> Optional[Path]:
    """Return the most recent eval_results_<ts> directory inside a trial folder."""
    dirs = sorted(trial_folder.glob("eval_results_*"), key=lambda p: p.name)
    return dirs[-1] if dirs else None


def _find_job_eval_dir(job_folder: Path) -> Optional[Path]:
    """Return the most recent eval_results_<ts> directory at the job level."""
    dirs = sorted(job_folder.glob("eval_results_*"), key=lambda p: p.name)
    return dirs[-1] if dirs else None


def _load_trial_eval(trial_folder: Path) -> Optional[Dict[str, Any]]:
    """Load the latest per-trial eval_results.json, or None if missing."""
    eval_dir = _find_latest_eval_dir(trial_folder)
    if eval_dir is None:
        return None
    path = eval_dir / "eval_results.json"
    if not path.exists():
        return None
    return json.loads(path.read_text())


def _save_trial_eval(
    trial_folder: Path, data: Dict[str, Any], output_dir: Optional[Path],
) -> None:
    """Write patched eval_results.json back to the trial's eval dir.

    If output_dir is given, mirror the trial-relative path under it instead.
    """
    eval_dir = _find_latest_eval_dir(trial_folder)
    if eval_dir is None:
        raise FileNotFoundError(f"No eval_results_* dir in {trial_folder}")

    if output_dir is not None:
        # eval_dir is like .../jobs/<job>/tc_xxx/trial_N/eval_results_<ts>
        # Keep structure from tc_xxx onward.
        target = output_dir / eval_dir.relative_to(trial_folder.parent.parent)
    else:
        target = eval_dir

    target.mkdir(parents=True, exist_ok=True)
    (target / "eval_results.json").write_text(
        json.dumps(data, indent=2, default=str)
    )


def _load_trace_and_criteria(trial_folder: Path):
    """Load the trace and test case criteria for a trial folder."""
    trace_path = latest_trace(trial_folder)
    if not trace_path:
        trace_path = convert_trace(trial_folder)
    trace = load_trace(trace_path)

    yaml_files = sorted(trial_folder.glob("*.yaml"))
    if len(yaml_files) != 1:
        raise ValueError(
            f"Expected exactly 1 .yaml in {trial_folder}, found {len(yaml_files)}: {yaml_files}"
        )
    criteria = parse_test_case(str(yaml_files[0]))
    return trace, criteria


# ── Per-metric computation ─────────────────────────────────────────────────
# Each function mirrors the corresponding section in evaluate.evaluate_trial().


def _compute_trace_scalars(trace) -> Dict[str, Any]:
    """Compute total_tokens, total_latency_ms, tool_call_count from trace."""
    total_tokens = (trace.metadata or {}).get("total_token_consumption", 0)
    total_latency_ms = sum((t.latency_in_ms or 0) for t in trace.turns or [])
    tool_call_count = sum(
        1 for t in (trace.turns or []) for s in (t.steps or []) if s.tool
    )
    return {
        "total_tokens": total_tokens,
        "total_latency_ms": total_latency_ms,
        "tool_call_count": tool_call_count,
    }


def _compute_skill_metrics(
    trace, criteria, known_skills: Optional[List[str]],
) -> Dict[str, Any]:
    """Compute skill_precision and skill_recall.

    Logic mirrors the 4-branch if/elif/else in evaluate.evaluate_trial().
    """
    expected_skills = criteria.expected_skill_calls
    if known_skills is not None and expected_skills:
        expected_skills = [
            sc for sc in expected_skills if sc.skill_id in known_skills
        ]

    invoked_skills = any(
        s.skill_calls for t in (trace.turns or []) for s in (t.steps or [])
    )

    skill_precision = None
    skill_recall = None

    if expected_skills and invoked_skills:
        eval_sample = EvaluationSample(expected_skill_calls=expected_skills)
        try:
            skill_precision = SkillPrecisionMetric().evaluate(trace, eval_sample).score
        except Exception as exc:
            logger.warning("SkillPrecision failed: %s", exc)
        try:
            skill_recall = SkillRecallMetric().evaluate(trace, eval_sample).score
        except Exception as exc:
            logger.warning("SkillRecall failed: %s", exc)
    elif expected_skills and not invoked_skills:
        skill_precision = 0.0
        skill_recall = 0.0
    elif not expected_skills and invoked_skills:
        skill_precision = 0.0
        skill_recall = 0.0
    else:
        skill_precision = 1.0
        skill_recall = 1.0

    return {"skill_precision": skill_precision, "skill_recall": skill_recall}


async def _compute_progress(
    trace, criteria, judge: JudgeConfig,
) -> Dict[str, Any]:
    """Compute progress_rates and subgoal_validations (requires LLM judge)."""
    llm_client = LiteLLMClient(model=judge.model, max_tokens=judge.max_tokens)
    validator_config = {
        INCLUDE_VALIDATION_RESULTS: True,
        INCLUDE_JUDGE_EXPLANATION: True,
        INCLUDE_PROMPT_SENT_TO_LLMJ: True,
        OPTIMIZE_JUDGE_TRIALS: False,
        TEMPLATE_SUBGOAL: DEFAULT_MODEL_GRADED_FACT_DYNAMIC_SUMMARY_TEMPLATE_ONE_SUBGOAL,
        NUM_JUDGE_TRIALS: judge.num_judge_trials,
    }
    goal_validator = SubGoalCompletionValidator(
        llm_client=llm_client, config=validator_config,
    )
    validation_results = await asyncio.gather(*[
        goal_validator.validate_dynamic(
            turn_traces=trace.turns,
            sub_goal=sg,
            user_instruction=criteria.task_summary,
        )
        for sg in criteria.sub_goals
    ])
    progress_score = ProgressScore.get_progress_score_from_validation_results(
        list(validation_results)
    )
    return {
        "progress_rates": [progress_score.score],
        "subgoal_validations": [
            {
                "is_completed": v.is_completed,
                "details": v.sub_goal.details,
                "explanations": v.explanations,
            }
            for v in validation_results
        ],
    }


async def _compute_capability(
    trace, criteria, judge: JudgeConfig,
) -> Dict[str, Any]:
    """Compute capability_score and capability_validations (requires LLM judge)."""
    if not criteria.expected_capabilities:
        return {"capability_score": None, "capability_validations": []}

    llm_client = LiteLLMClient(model=judge.model, max_tokens=judge.max_tokens)
    cap_validator = CapabilityCompletionValidator(
        llm_client=llm_client,
        config={
            NUM_JUDGE_TRIALS: judge.num_judge_trials,
            INCLUDE_JUDGE_EXPLANATION: True,
        },
    )
    cap_results = await asyncio.gather(*[
        cap_validator.validate(trace.turns, cap)
        for cap in criteria.expected_capabilities
    ])
    capability_score = (
        sum(1 for r in cap_results if r.is_completed) / len(cap_results)
    )
    return {
        "capability_score": capability_score,
        "capability_validations": [
            {
                "is_completed": r.is_completed,
                "name": getattr(r.expected_capability, "capability_name", None)
                        or r.expected_capability.description,
                "explanations": r.explanations,
            }
            for r in cap_results
        ],
    }


# ── Core: selective recompute + patch ──────────────────────────────────────


async def recompute_trial(
    trial_folder: Path,
    metrics_to_recompute: set[str],
    judge: JudgeConfig,
    known_skills: Optional[List[str]],
) -> Optional[Dict[str, Any]]:
    """Recompute only the requested metrics for one trial, merge into existing.

    Returns the patched eval dict, or None if the trial has no prior results.
    Only invokes the LLM judge when the requested metrics actually need it.
    """
    existing = _load_trial_eval(trial_folder)
    if existing is None:
        logger.warning("No existing eval_results.json in %s — skipping", trial_folder)
        return None

    trace, criteria = _load_trace_and_criteria(trial_folder)
    fresh: Dict[str, Any] = {}

    # Trace-only scalars (no LLM calls).
    trace_scalars = metrics_to_recompute & {"total_tokens", "total_latency_ms", "tool_call_count"}
    if trace_scalars:
        fresh.update(_compute_trace_scalars(trace))

    # Skill precision / recall (no LLM calls).
    if metrics_to_recompute & {"skill_precision", "skill_recall"}:
        fresh.update(_compute_skill_metrics(trace, criteria, known_skills))

    # Progress rates (LLM judge).
    if "progress_rates" in metrics_to_recompute:
        fresh.update(await _compute_progress(trace, criteria, judge))

    # Capability score (LLM judge).
    if "capability_score" in metrics_to_recompute:
        fresh.update(await _compute_capability(trace, criteria, judge))

    # Patch only the requested metrics (and their companions) into existing.
    for metric in metrics_to_recompute:
        if metric in fresh:
            existing[metric] = fresh[metric]
        for companion in _METRIC_COMPANIONS.get(metric, []):
            if companion in fresh:
                existing[companion] = fresh[companion]

    return existing


# ── Job-level orchestration ────────────────────────────────────────────────


async def recompute_job(
    job_folder: Path,
    metrics_to_recompute: set[str],
    judge: JudgeConfig,
    n_trials: int,
    max_workers: int,
    known_skills: Optional[List[str]],
    output_dir: Optional[Path],
) -> None:
    """Recompute requested metrics for all trials in a job, then re-aggregate."""
    trial_folders = discover_trial_folders(job_folder)
    if not trial_folders:
        logger.error("No trial folders found under %s", job_folder)
        return

    logger.info(
        "Job %s: %d trial folder(s), recomputing %s",
        job_folder.name, len(trial_folders), sorted(metrics_to_recompute),
    )

    sem = asyncio.Semaphore(max_workers)

    async def _process(tf: Path) -> Optional[tuple[Path, Dict[str, Any]]]:
        async with sem:
            try:
                patched = await recompute_trial(
                    tf, metrics_to_recompute, judge, known_skills,
                )
            except Exception as exc:
                logger.error("Failed to recompute %s: %s", tf, exc)
                return None
            if patched is None:
                return None
            _save_trial_eval(tf, patched, output_dir)
            logger.info("  ✓ %s/%s", tf.parent.name, tf.name)
            return (tf, patched)

    raw_results = await asyncio.gather(*[_process(tf) for tf in trial_folders])
    successful = [r for r in raw_results if r is not None]

    if not successful:
        logger.error("No trials were successfully recomputed for %s", job_folder)
        return

    # ── Re-aggregate ────────────────────────────────────────────────────
    results: List[TrialEvalResult] = []
    for tf, patched_metrics in successful:
        try:
            trial_id = int(tf.name.split("_")[-1])
        except ValueError:
            trial_id = 1
        sample_id = tf.parent.name

        total_turns = 0
        conv = tf / "conversation.json"
        if conv.exists():
            total_turns = len(json.loads(conv.read_text()).get("conversations", []))

        results.append(TrialEvalResult(
            trial_id=trial_id,
            sample_id=sample_id,
            total_turns=total_turns,
            metrics=patched_metrics,
        ))

    agg = aggregate_metrics(results, n_trials)

    # ── Patch the job-level aggregate ───────────────────────────────────
    job_eval_dir = _find_job_eval_dir(job_folder)
    existing_agg_path = (
        (job_eval_dir / "aggregate_metrics_results.json") if job_eval_dir else None
    )
    existing_agg: Dict[str, Any] = {}
    if existing_agg_path and existing_agg_path.exists():
        existing_agg = json.loads(existing_agg_path.read_text())

    # Determine which aggregate-level keys to replace.
    agg_keys_to_replace = set(metrics_to_recompute)
    if "progress_rates" in metrics_to_recompute:
        # Progress changed → derived aggregates must also update.
        agg_keys_to_replace |= {
            "max_progress_rate", "mean_progress_rate", "pass@k", "pass^k",
        }
        agg_keys_to_replace.discard("progress_rates")  # Not an aggregate key

    existing_metrics = existing_agg.get("metrics", {})
    new_metrics = agg.get("metrics", {})
    for key in agg_keys_to_replace:
        if key in new_metrics:
            existing_metrics[key] = new_metrics[key]

    existing_agg["metrics"] = existing_metrics
    existing_agg["n_samples"] = agg["n_samples"]
    existing_agg["n_trials"] = agg["n_trials"]

    # Write the patched aggregate.
    # When no job-level eval dir exists yet, create one (e.g. data copied
    # without the top-level aggregate folder).
    if job_eval_dir is None:
        from datetime import datetime as _dt
        job_eval_dir = job_folder / f"eval_results_{_dt.now().strftime('%Y%m%d_%H%M%S')}"

    if output_dir is not None:
        dest_eval_dir = output_dir / job_eval_dir.relative_to(job_folder)
    else:
        dest_eval_dir = job_eval_dir

    dest_eval_dir.mkdir(parents=True, exist_ok=True)
    (dest_eval_dir / "aggregate_metrics_results.json").write_text(
        json.dumps(existing_agg, indent=2, default=str)
    )

    # Regenerate per-trial result files (trial_N_results.json).
    by_trial: Dict[int, List[TrialEvalResult]] = defaultdict(list)
    for r in results:
        by_trial[r.trial_id].append(r)
    for tid, trs in sorted(by_trial.items()):
        data = {
            "trial_id": tid,
            "total_samples": len(trs),
            "successful": sum(1 for r in trs if r.status == "success"),
            "samples": [r.to_dict() for r in trs],
        }
        (dest_eval_dir / f"trial_{tid}_results.json").write_text(
            json.dumps(data, indent=2, default=str)
        )

    # Print summary.
    m = existing_agg["metrics"]
    logger.info(
        "\n%s\nRecomputed metrics: %s\n%s"
        "\nMax progress rate  (avg): %s"
        "\nMean progress rate (avg): %s"
        "\nAvg skill_precision: %s"
        "\nAvg skill_recall:    %s"
        "\nAvg capability_score: %s"
        "\nResults written to: %s\n%s",
        "=" * 70, sorted(metrics_to_recompute), "=" * 70,
        _fmt((m.get("max_progress_rate") or {}).get("avg")),
        _fmt((m.get("mean_progress_rate") or {}).get("avg")),
        _fmt((m.get("skill_precision") or {}).get("avg")),
        _fmt((m.get("skill_recall") or {}).get("avg")),
        _fmt((m.get("capability_score") or {}).get("avg")),
        dest_eval_dir, "=" * 70,
    )


# ── CLI ─────────────────────────────────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Recompute specific metrics without touching others.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Available metrics:\n"
            "  skill_precision   skill_recall   capability_score\n"
            "  progress_rates    total_tokens   total_latency_ms   tool_call_count"
        ),
    )
    parser.add_argument(
        "path", nargs="+",
        help="Job folder(s) containing trial results",
    )
    parser.add_argument(
        "--metrics", nargs="+", required=True,
        choices=sorted(TRIAL_LEVEL_METRICS),
        help="Metric(s) to recompute",
    )
    parser.add_argument("--n-trials", type=int, required=True,
                        help="Number of trials (must match the original run)")
    parser.add_argument("--output-dir", type=str, default=None,
                        help="Write patched results here instead of in-place")
    parser.add_argument("--max-workers", type=int, default=4)
    parser.add_argument("--config", default=DEFAULT_RUNNER_CONFIG)
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(message)s",
        handlers=[logging.StreamHandler(sys.stdout)],
    )

    raw_cfg = load_runner_config(args.config)
    judge = judge_config_from(raw_cfg)
    known_skills = skills_from(raw_cfg)
    metrics_to_recompute = set(args.metrics)
    output_dir = Path(args.output_dir) if args.output_dir else None

    logger.info(
        "Recompute: metrics=%s  judge=%s  n_trials=%d  skills=%s  output_dir=%s",
        sorted(metrics_to_recompute), judge.model, args.n_trials,
        known_skills, output_dir or "(in-place)",
    )

    for p in args.path:
        job_folder = Path(p)
        if not job_folder.exists():
            logger.error("Path does not exist: %s", job_folder)
            continue

        if _is_trial_folder(job_folder):
            logger.error(
                "Please point at the job folder (parent of tc_*/trial_*), "
                "not a single trial: %s",
                job_folder,
            )
            continue

        # Guard: if the job recorded which skills were active, the current
        # config must match — otherwise precision/recall will be wrong.
        skills_file = job_folder / "skills_used.json"
        if skills_file.exists():
            saved_skills = sorted(
                json.loads(skills_file.read_text())["active_skills"]
            )
            assert saved_skills == sorted(known_skills or []), (
                f"Skill mismatch for {job_folder.name}: "
                f"original job {saved_skills} != current config {sorted(known_skills or [])}"
            )

        # Per-job output dir: output_dir/<job_name> when writing externally.
        job_output = None
        if output_dir is not None:
            job_output = output_dir / job_folder.name
            job_output.mkdir(parents=True, exist_ok=True)

        asyncio.run(recompute_job(
            job_folder=job_folder,
            metrics_to_recompute=metrics_to_recompute,
            judge=judge,
            n_trials=args.n_trials,
            max_workers=args.max_workers,
            known_skills=known_skills,
            output_dir=job_output,
        ))

    logger.info("Done.")


if __name__ == "__main__":
    main()
