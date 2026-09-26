"""Eval runner: convert traces and evaluate metrics for trials or jobs.

Pure evaluation — no CUGA imports. Reads artifacts produced by conversation.py.

Usage:
    # Single trial
    PYTHONPATH="agent-inspect/src:." python -m experiment_clean.evaluate \\
        experiment_clean/experiment_results/jobs/<job>/tc_foo/trial_1/

    # Whole job
    PYTHONPATH="agent-inspect/src:." python -m experiment_clean.evaluate \\
        experiment_clean/experiment_results/jobs/<job>/ --n-trials 5
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import statistics
import sys
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from agent_inspect.metrics.validator import SubGoalCompletionValidator
from agent_inspect.metrics.scorer import ProgressScore, SuccessBasedMetric
from agent_inspect.metrics.scorer.templates import (
    DEFAULT_MODEL_GRADED_FACT_DYNAMIC_SUMMARY_TEMPLATE_ONE_SUBGOAL,
)
from agent_inspect.metrics.scorer.skill_precision import SkillPrecisionMetric
from agent_inspect.metrics.scorer.skill_recall import SkillRecallMetric
from agent_inspect.metrics.validator.capability_call_completion import (
    CapabilityCompletionValidator,
)
from agent_inspect.metrics.multi_samples import PassAtK, PassHatK
from agent_inspect.metrics.constants import (
    INCLUDE_JUDGE_EXPLANATION,
    INCLUDE_VALIDATION_RESULTS,
    INCLUDE_PROMPT_SENT_TO_LLMJ,
    OPTIMIZE_JUDGE_TRIALS,
    TEMPLATE_SUBGOAL,
    NUM_JUDGE_TRIALS,
    K_VALUE,
    NO_OF_TRIALS,
)
from agent_inspect.models.metrics import EvaluationSample, NumericalScore
from agent_inspect.clients import LiteLLMClient

from experiment_clean.config import (
    DEFAULT_RUNNER_CONFIG,
    JudgeConfig,
    load_runner_config,
    judge_config_from,
    silence_litellm,
    skills_from,
)
from experiment_clean.testcase import parse_test_case
from experiment_clean.trace import convert_trace, latest_trace, load_trace

silence_litellm()

logger = logging.getLogger("experiment_clean.evaluate")


# ── Result dataclass ─────────────────────────────────────────────────────────

@dataclass
class TrialEvalResult:
    trial_id: int
    sample_id: str
    status: str = "success"
    error: Optional[str] = None
    total_turns: int = 0
    metrics: Optional[Dict[str, Any]] = None

    @property
    def final_progress(self) -> Optional[float]:
        rates = (self.metrics or {}).get("progress_rates", [])
        return rates[-1] if rates else None

    def to_dict(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {
            "trial_id": self.trial_id,
            "sample_id": self.sample_id,
            "status": self.status,
            "total_turns": self.total_turns,
        }
        if self.error:
            out["error"] = self.error
        if self.metrics:
            out["metrics"] = self.metrics
        return out


# ── Folder detection ─────────────────────────────────────────────────────────

def discover_trial_folders(root: Path) -> List[Path]:
    """Find all trial folders (contain thread_id.txt) under root."""
    return sorted(p.parent for p in root.rglob("thread_id.txt"))


def _is_trial_folder(path: Path) -> bool:
    return (path / "thread_id.txt").exists()


# ── Core evaluation ──────────────────────────────────────────────────────────

async def evaluate_trial(
    trial_folder: Path,
    judge: JudgeConfig,
    known_skills: Optional[List[str]] = None,
) -> dict:
    """Run all metrics on a single trial. Returns metrics dict."""
    trial_folder = Path(trial_folder)

    # Get or convert trace
    trace_path = latest_trace(trial_folder)
    if not trace_path:
        trace_path = convert_trace(trial_folder)
    trace = load_trace(trace_path)

    # Parse test case — exactly one YAML per trial folder
    yaml_files = sorted(trial_folder.glob("*.yaml"))
    if len(yaml_files) != 1:
        raise ValueError(
            f"Expected exactly 1 .yaml in {trial_folder}, found {len(yaml_files)}: {yaml_files}"
        )
    criteria = parse_test_case(str(yaml_files[0]))

    llm_client = LiteLLMClient(model=judge.model, max_tokens=judge.max_tokens)

    # ── Subgoal progress ─────────────────────────────────────────────────
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

    # ── Token / latency / tool counts ────────────────────────────────────
    total_tokens = (trace.metadata or {}).get("total_token_consumption", 0)
    total_latency_ms = sum((t.latency_in_ms or 0) for t in trace.turns or [])
    tool_call_count = sum(
        1 for t in (trace.turns or []) for s in (t.steps or []) if s.tool
    )

    # ── Skill precision / recall ─────────────────────────────────────────
    skill_precision = None
    skill_recall = None

    # Filter expected skills against known_skills if provided.
    expected_skills = criteria.expected_skill_calls
    if known_skills is not None and expected_skills:
        expected_skills = [
            sc for sc in expected_skills if sc.skill_id in known_skills
        ]

    invoked_skills = any(
        s.skill_calls for t in (trace.turns or []) for s in (t.steps or [])
    )

    if expected_skills and invoked_skills:
        # Normal case: both expected and invoked — let the library compute.
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
        # Expected skills but agent invoked none.
        skill_precision = 0.0
        skill_recall = 0.0
    elif not expected_skills and invoked_skills:
        # No expected skills but agent invoked some (false positives).
        skill_precision = 0.0
        skill_recall = 0.0
    else:
        # No expected skills and agent invoked none — perfect match.
        skill_precision = 1.0
        skill_recall = 1.0

    # ── Capability completion ────────────────────────────────────────────
    capability_score = None
    cap_results = []
    if criteria.expected_capabilities:
        try:
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
        except Exception as exc:
            logger.warning("CapabilityCompletion failed: %s", exc)

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
        "total_tokens": total_tokens,
        "total_latency_ms": total_latency_ms,
        "tool_call_count": tool_call_count,
        "skill_precision": skill_precision,
        "skill_recall": skill_recall,
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


# ── Aggregation ──────────────────────────────────────────────────────────────

def aggregate_metrics(
    results: List[TrialEvalResult],
    n_trials: int,
) -> Dict[str, Any]:
    """Aggregate per-trial metrics into job-level summary."""
    by_sample: Dict[str, List[TrialEvalResult]] = defaultdict(list)
    for r in results:
        if r.status == "success" and r.metrics:
            by_sample[r.sample_id].append(r)

    metrics: Dict[str, Any] = {}

    # Progress rate
    max_pr, mean_pr = {}, {}
    for sid, trs in by_sample.items():
        finals = [t.final_progress for t in trs if t.final_progress is not None]
        max_pr[sid] = max(finals) if finals else None
        mean_pr[sid] = statistics.mean(finals) if finals else None
    valid_max = [v for v in max_pr.values() if v is not None]
    valid_mean = [v for v in mean_pr.values() if v is not None]
    metrics["max_progress_rate"] = {
        "per_sample": max_pr,
        "avg": statistics.mean(valid_max) if valid_max else None,
    }
    metrics["mean_progress_rate"] = {
        "per_sample": mean_pr,
        "avg": statistics.mean(valid_mean) if valid_mean else None,
    }

    # Scalar metrics
    for field in ("total_tokens", "total_latency_ms", "tool_call_count",
                  "skill_precision", "skill_recall", "capability_score"):
        avg_per_sample = {}
        for sid, trs in by_sample.items():
            vals = [
                t.metrics.get(field)
                for t in trs
                if t.metrics and t.metrics.get(field) is not None
            ]
            avg_per_sample[sid] = statistics.mean(vals) if vals else None
        valid = [v for v in avg_per_sample.values() if v is not None]
        metrics[field] = {
            "per_sample": avg_per_sample,
            "avg": statistics.mean(valid) if valid else None,
        }

    # Pass@k / Pass^k — failed trials count as score=0 (unsuccessful), not excluded.
    all_by_sample: Dict[str, List[TrialEvalResult]] = defaultdict(list)
    for r in results:
        all_by_sample[r.sample_id].append(r)

    pass_at_k = PassAtK(config={K_VALUE: n_trials, NO_OF_TRIALS: n_trials})
    pass_hat_k = PassHatK(config={K_VALUE: n_trials, NO_OF_TRIALS: n_trials})
    pak, phk = {}, {}
    for sid, trs in all_by_sample.items():
        scores = []
        for t in trs:
            fp = t.final_progress
            if fp is not None:
                scores.append(SuccessBasedMetric.get_success_score_from_progress_score(
                    NumericalScore(score=fp)
                ))
            else:
                # Failed trial or missing progress → unsuccessful
                scores.append(NumericalScore(score=0))
        try:
            pak[sid] = pass_at_k.compute(scores).score if scores else None
        except Exception as exc:
            logger.warning("pass@k skipped for %s: %s", sid, exc)
            pak[sid] = None
        try:
            phk[sid] = pass_hat_k.compute(scores).score if scores else None
        except Exception as exc:
            logger.warning("pass^k skipped for %s: %s", sid, exc)
            phk[sid] = None

    valid_pak = [v for v in pak.values() if v is not None]
    valid_phk = [v for v in phk.values() if v is not None]
    metrics["pass@k"] = {
        "k": n_trials, "per_sample": pak,
        "avg": statistics.mean(valid_pak) if valid_pak else None,
    }
    metrics["pass^k"] = {
        "k": n_trials, "per_sample": phk,
        "avg": statistics.mean(valid_phk) if valid_phk else None,
    }

    return {"n_samples": len(all_by_sample), "n_trials": n_trials, "metrics": metrics}


# ── Batch eval ───────────────────────────────────────────────────────────────

async def run_eval_batch(
    trial_folders: List[Path],
    judge: JudgeConfig,
    n_trials: int,
    max_workers: int = 4,
    reconvert: bool = False,
    known_skills: Optional[List[str]] = None,
    run_ts: Optional[str] = None,
) -> List[TrialEvalResult]:
    """Evaluate all trial folders concurrently."""
    sem = asyncio.Semaphore(max_workers)
    if run_ts is None:
        run_ts = datetime.now().strftime("%Y%m%d_%H%M%S")

    async def _eval_one(tf: Path) -> TrialEvalResult:
        try:
            trial_id = int(tf.name.split("_")[-1])
        except ValueError:
            trial_id = 1
        sample_id = tf.parent.name

        if reconvert:
            try:
                convert_trace(tf)
            except Exception as exc:
                logger.warning("Trace conversion failed for %s: %s", tf, exc)

        async with sem:
            try:
                metrics = await evaluate_trial(tf, judge, known_skills)
                total_turns = 0
                conv = tf / "conversation.json"
                if conv.exists():
                    total_turns = len(
                        json.loads(conv.read_text()).get("conversations", [])
                    )
                r = TrialEvalResult(
                    trial_id=trial_id, sample_id=sample_id,
                    total_turns=total_turns, metrics=metrics,
                )
                # Print summary
                rates = metrics["progress_rates"]
                logger.info(
                    "\n%s\nCase: %s/%s\nProgress: %.4f\n%s",
                    "=" * 60, sample_id, tf.name,
                    rates[-1] if rates else 0, "=" * 60,
                )
                # Save per-trial eval
                eval_dir = tf / f"eval_results_{run_ts}"
                eval_dir.mkdir(exist_ok=True)
                (eval_dir / "eval_results.json").write_text(
                    json.dumps(metrics, indent=2, default=str)
                )
            except Exception as exc:
                logger.error("Eval failed for %s: %s", tf, exc)
                r = TrialEvalResult(
                    trial_id=trial_id, sample_id=sample_id,
                    status="failed", error=str(exc),
                )
        return r

    return list(await asyncio.gather(*[_eval_one(tf) for tf in trial_folders]))


def save_results(
    results: List[TrialEvalResult],
    n_trials: int,
    output_dir: Path,
    run_ts: str,
) -> None:
    """Save per-trial and aggregate results."""
    eval_dir = output_dir / f"eval_results_{run_ts}"
    eval_dir.mkdir(exist_ok=True)

    # Per-trial files
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
        (eval_dir / f"trial_{tid}_results.json").write_text(
            json.dumps(data, indent=2, default=str)
        )

    # Aggregate
    agg = aggregate_metrics(results, n_trials)
    n_samples = agg["n_samples"]
    ok = [r for r in results if r.status == "success"]
    fail = [r for r in results if r.status == "failed"]
    expected_runs = n_samples * n_trials
    missing = expected_runs - len(results)
    summary = {
        "n_samples": n_samples,
        "n_trials": n_trials,
        "expected_runs": expected_runs,
        "successful": len(ok),
        "failed": len(fail),
        "missing": missing,
        "avg_turns": (sum(r.total_turns for r in ok) / len(ok)) if ok else 0,
    }
    output = {"timestamp": datetime.now().isoformat(), "summary": summary, **agg}
    (eval_dir / "aggregate_metrics_results.json").write_text(
        json.dumps(output, indent=2, default=str)
    )

    # Print summary
    m = agg["metrics"]
    logger.info(
        "\n%s\n%d sample(s) x %d trial(s) = %d expected | %d successful, %d failed, %d missing\n%s"
        "\nMax progress rate  (avg): %s"
        "\nMean progress rate (avg): %s"
        "\nPass@%d (avg): %s"
        "\nPass^%d (avg): %s"
        "\nAvg skill_precision: %s"
        "\nAvg skill_recall:    %s"
        "\nAvg capability_score: %s",
        "=" * 70, n_samples, n_trials, expected_runs,
        len(ok), len(fail), missing, "=" * 70,
        _fmt(m["max_progress_rate"]["avg"]),
        _fmt(m["mean_progress_rate"]["avg"]),
        n_trials, _fmt(m["pass@k"]["avg"]),
        n_trials, _fmt(m["pass^k"]["avg"]),
        _fmt((m.get("skill_precision") or {}).get("avg")),
        _fmt((m.get("skill_recall") or {}).get("avg")),
        _fmt((m.get("capability_score") or {}).get("avg")),
    )
    for r in fail:
        logger.info("  FAILED %s (trial %d): %s", r.sample_id, r.trial_id, r.error)


def _fmt(v) -> str:
    return f"{v:.4f}" if isinstance(v, (int, float)) else "n/a"


# ── CLI ──────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="CUGA eval runner")
    parser.add_argument("path", nargs="+",
                        help="Trial/case/job folder(s) — multiple paths are aggregated together")
    parser.add_argument("--n-trials", type=int, required=True,
                        help="Number of trials (must match conversation run)")
    parser.add_argument("--max-workers", type=int, default=4)
    parser.add_argument("--reconvert", action="store_true")
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
    run_ts = datetime.now().strftime("%Y%m%d_%H%M%S")

    # Skills from config
    known_skills = skills_from(raw_cfg)

    logger.info(
        "Judge: model=%s  max_tokens=%d  trials=%d  skills=%s",
        judge.model, judge.max_tokens, judge.num_judge_trials, known_skills,
    )

    # Discover trial folders across all input paths
    trial_folders = []
    for p in args.path:
        root = Path(p)
        if not root.exists():
            print(f"Warning: {root} does not exist, skipping", file=sys.stderr)
            continue
        if _is_trial_folder(root):
            trial_folders.append(root)
        else:
            trial_folders.extend(discover_trial_folders(root))

    if not trial_folders:
        print(f"No trial folders found under {args.path}", file=sys.stderr)
        sys.exit(1)

    logger.info("Found %d trial folder(s) across %d path(s)", len(trial_folders), len(args.path))

    results = asyncio.run(run_eval_batch(
        trial_folders, judge, args.n_trials,
        max_workers=args.max_workers,
        reconvert=args.reconvert,
        known_skills=known_skills,
        run_ts=run_ts,
    ))

    # Save aggregate results to the first path
    output_root = Path(args.path[0])
    save_results(results, args.n_trials, output_root, run_ts)


if __name__ == "__main__":
    main()
