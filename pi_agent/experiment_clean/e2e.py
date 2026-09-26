"""End-to-end runner: conversation phase → eval phase.

Usage:
    PYTHONPATH="agent-inspect/src:." python -m experiment_clean.e2e \\
        experiment_clean/test_cases/tau2retail \\
        --n-trials 5 --max-workers 5 \\
        --config experiment_clean/runner_config.yaml --base-url http://localhost:8000
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import shutil
import sys
from datetime import datetime
from pathlib import Path

from experiment_clean.config import (
    DEFAULT_OUTPUT_ROOT,
    DEFAULT_RUNNER_CONFIG,
    load_runner_config,
    user_proxy_config_from,
    judge_config_from,
    pi_config_from,
    skills_from,
)
from experiment_clean import pi_client
from experiment_clean.testcase import iter_case_files
from experiment_clean.conversation import (
    resolve_active_skills,
    run_all,
    save_runs_summary,
)
from experiment_clean.evaluate import (
    discover_trial_folders,
    run_eval_batch,
    save_results,
)

logger = logging.getLogger("experiment_clean.e2e")


def main() -> None:
    parser = argparse.ArgumentParser(description="Pi E2E: conversation + eval")
    parser.add_argument("path", nargs="*", help="YAML file(s) or directory")
    parser.add_argument("--n-trials", type=int, default=1)
    parser.add_argument("--max-workers", type=int, default=5)
    parser.add_argument("--config", default=DEFAULT_RUNNER_CONFIG)
    parser.add_argument("--base-url", default=None, help="Pi gateway URL (default from config/env)")
    parser.add_argument("--env-template", default=None, help="Workspace template dir")
    parser.add_argument("--workspace-root", default=None, help="Where per-trial workspaces are written")
    parser.add_argument("--ask-timeout", type=float, default=None, help="Per-turn agent timeout (s)")
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--resume", default=None,
                        help="Resume failed trials from a previous job dir, then re-eval")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(message)s",
        handlers=[logging.StreamHandler(sys.stdout)],
    )

    raw_cfg = load_runner_config(args.config)
    user_proxy_cfg = user_proxy_config_from(raw_cfg)
    judge_cfg = judge_config_from(raw_cfg)
    pi_cfg = pi_config_from(raw_cfg)

    base_url = args.base_url or pi_cfg.base_url
    env_template = args.env_template or pi_cfg.workspace_template
    workspace_root = args.workspace_root or pi_cfg.workspace_root
    ask_timeout = args.ask_timeout if args.ask_timeout is not None else pi_cfg.ask_timeout

    active_skills = resolve_active_skills(env_template, raw_cfg)

    # Preflight: fail fast if the gateway is down.
    try:
        pi_client.healthz(base_url)
    except pi_client.PiGatewayError as exc:
        logger.error("Pi gateway not reachable at %s: %s", base_url, exc)
        sys.exit(1)

    # Discover cases
    case_files = []
    default_dir = str(Path(__file__).parent / "test_cases")
    for p in args.path or [default_dir]:
        case_files.extend(iter_case_files(p))

    if args.resume:
        # ── Resume mode ──────────────────────────────────────────────────
        from experiment_clean.conversation import run_resume, merge_runs_summary
        job_dir = args.resume
        logger.info("RESUME mode: %s", job_dir)

        # Guard: skills must match the original run
        saved_skills = sorted(
            json.loads(Path(job_dir, "skills_used.json").read_text())["active_skills"]
        )
        assert saved_skills == sorted(active_skills), (
            f"Skill mismatch: original job {saved_skills} != current config {sorted(active_skills)}"
        )

        conv_results = asyncio.run(run_resume(
            job_dir, case_files, base_url, env_template, workspace_root, active_skills,
            user_proxy_cfg, args.n_trials, args.max_workers, ask_timeout,
        ))
        if conv_results:
            merge_runs_summary(job_dir, conv_results)
            ok = sum(1 for r in conv_results if r.status == "success")
            logger.info("Resume: %d/%d retried succeeded", ok, len(conv_results))
        else:
            logger.info("Nothing to resume.")

        output_dir = job_dir
    else:
        # ── Normal mode ──────────────────────────────────────────────────
        ts = datetime.now().strftime("%Y-%m-%d__%H-%M-%S")
        output_dir = os.path.join(args.output_dir, "jobs", ts)
        os.makedirs(output_dir, exist_ok=True)

        # Save metadata
        Path(output_dir, "skills_used.json").write_text(json.dumps({
            "active_skills": active_skills, "count": len(active_skills),
        }, indent=2))
        if os.path.exists(args.config):
            shutil.copy2(args.config, os.path.join(output_dir, "runner_config.yaml"))

        logger.info(
            "E2E: %d case(s) x %d trial(s) | workers=%d | skills=%s",
            len(case_files), args.n_trials, args.max_workers, active_skills,
        )

        # Phase 1: Conversations
        conv_results = asyncio.run(run_all(
            case_files, base_url, env_template, workspace_root, active_skills,
            user_proxy_cfg, output_dir, args.n_trials, args.max_workers, ask_timeout,
        ))
        save_runs_summary(conv_results, output_dir, args.n_trials)

        ok = sum(1 for r in conv_results if r.status == "success")
        logger.info("Conversation phase: %d/%d succeeded", ok, len(conv_results))
        for r in conv_results:
            if r.status == "failed":
                logger.info("  FAIL %s (trial %d) — %s", r.sample_id, r.trial_id, r.error)

        if ok == 0:
            logger.info("All conversations failed; skipping eval.")
            return

    # ── Phase 2: Evaluation ──────────────────────────────────────────────
    # known_skills for metric filtering comes from the YAML whitelist (source
    # of truth), not the filesystem result (active_skills).
    run_ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    job_dir = Path(output_dir)
    trial_folders = discover_trial_folders(job_dir)

    if not trial_folders:
        logger.info("No trial folders found; skipping eval.")
        return

    # No reconvert on the Pi path: Phase 1 wrote trace_<N>.json directly (there
    # is no DB to convert). latest_trace() picks it up.
    eval_results = asyncio.run(run_eval_batch(
        trial_folders, judge_cfg, args.n_trials,
        max_workers=args.max_workers,
        reconvert=False,
        known_skills=skills_from(raw_cfg),
        run_ts=run_ts,
    ))
    save_results(eval_results, args.n_trials, job_dir, run_ts)

    logger.info("E2E complete. Results in %s", output_dir)


if __name__ == "__main__":
    main()

