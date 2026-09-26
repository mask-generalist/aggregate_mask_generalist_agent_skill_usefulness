"""Conversation runner: drive Pi coding-agent conversations via the HTTP gateway.

The gateway (docker-pi/pi_server.py) manages Pi container lifecycle. This module
talks to it over HTTP (see experiment_clean.pi_client): create a session, send
each user turn, delete the session. Each /ask response is accumulated in memory
and written straight to trace_<N>.json — no CUGA, no SQLite.

Usage (conversation only):
    PYTHONPATH="agent-inspect/src:." python -m experiment_clean.conversation \\
        experiment_clean/test_cases/tau2retail --n-trials 5 --max-workers 5 \\
        --config experiment_clean/runner_config.yaml --base-url http://localhost:8000
"""

from __future__ import annotations

import argparse
import asyncio
import dataclasses
import datetime as _dt
import json
import logging
import os
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional
from uuid import uuid4

from agent_inspect.user_proxy import UserProxyAgent
from agent_inspect.user_proxy.constants import USE_EXPERT_AGENT
from agent_inspect.models.user_proxy import (
    ChatHistory,
    ConversationTurn,
    ResponseFromAgent,
    TerminatingCondition,
    UserProxyMessage,
)
from agent_inspect.clients import LiteLLMClient

from experiment_clean import pi_client
from experiment_clean.config import (
    DEFAULT_ASK_TIMEOUT,
    DEFAULT_ENV_TEMPLATE,
    DEFAULT_OUTPUT_ROOT,
    DEFAULT_RUNNER_CONFIG,
    DEFAULT_WORKSPACE_ROOT,
    UserProxyConfig,
    load_runner_config,
    pi_config_from,
    silence_litellm,
    user_proxy_config_from,
    skills_from,
)
from experiment_clean.testcase import TestCaseCriteria, parse_test_case, iter_case_files

logger = logging.getLogger("experiment_clean.conversation")
silence_litellm()

# Placeholder recorded when the UserProxy's terminating turn (check set, e.g.
# "END_CONVERSATION") gets an empty agent reply. The agent has nothing to say to
# a control token, but an empty agent_response fails the trial at eval time
# (agent-inspect 050008), so we substitute a benign non-empty string.
_TERMINATION_PLACEHOLDER = "[conversation ended]"


# ── Result dataclass ─────────────────────────────────────────────────────────

@dataclass
class TrialResult:
    trial_id: int
    sample_id: str
    run_id: str
    session_id: Optional[str] = None
    status: str = "success"
    error: Optional[str] = None
    total_turns: int = 0
    case_dir: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {
            "trial_id": self.trial_id,
            "sample_id": self.sample_id,
            "run_id": self.run_id,
            "status": self.status,
            "total_turns": self.total_turns,
            "case_dir": self.case_dir,
        }
        if self.error is not None:
            out["error"] = self.error
        return out


# ── Helpers ──────────────────────────────────────────────────────────────────

def _seed_workspace(host_workspace: Path, env_template: str, active_skills: List[str]) -> None:
    """Clone the env template into a fresh per-trial workspace, pruning skills.

    Copies the whole materialized template (experiment_clean/env/): world.db,
    testbed/, data/, docs/, config/, scripts/, and the Pi-ready .pi/skills/ tree.
    If a whitelist is given, remove any skill directory not in it (from both
    .pi/skills/ — which Pi discovers at /workspace/.pi/skills — and the duplicate
    skills/ tree). The host workspace is bind-mounted into the Pi container.
    """
    src = Path(env_template)
    if not src.is_dir():
        raise FileNotFoundError(f"Workspace template not found: {src}")
    # Start pristine: the trial path is deterministic (case_id/trial_N), so a
    # prior run's leftover files would otherwise merge in under dirs_exist_ok.
    # Clearing first guarantees each trial sees only the template (matches the
    # CUGA runner, whose per-trial uuid workspace was always brand-new).
    if host_workspace.exists():
        shutil.rmtree(host_workspace)
    host_workspace.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(src, host_workspace)

    if active_skills is None:
        return
    keep = set(active_skills)
    for skills_dir in (host_workspace / ".pi" / "skills", host_workspace / "skills"):
        if not skills_dir.is_dir():
            continue
        for skill_dir in skills_dir.iterdir():
            if skill_dir.is_dir() and skill_dir.name not in keep:
                shutil.rmtree(skill_dir, ignore_errors=True)


def resolve_active_skills(env_template: str, raw_cfg: dict) -> List[str]:
    """Resolve which skills to keep: the config whitelist, or all in the template.

    Pure resolution (no filesystem mutation). Used by both conversation.py and
    e2e.py so the logic stays in one place. Skill names are returned verbatim to
    match the SKILL.md ``name:`` frontmatter and the whitelist.
    """
    skill_list = skills_from(raw_cfg)
    if skill_list is not None:
        return skill_list
    skills_dir = Path(env_template) / ".pi" / "skills"
    if skills_dir.is_dir():
        return sorted(d.name for d in skills_dir.iterdir() if d.is_dir())
    return []


# ── Conversation loop ────────────────────────────────────────────────────────

async def run_conversation(
    criteria: TestCaseCriteria,
    user_proxy_cfg: UserProxyConfig,
    base_url: str,
    session_id: str,
    case_id: str,
    trial_label: str,
    ask_timeout: float = DEFAULT_ASK_TIMEOUT,
    new_session: Optional[Callable[[], str]] = None,
    drop_session: Optional[Callable[[str], None]] = None,
    max_turn_retries: int = 1,
) -> tuple[ChatHistory, list[dict], str]:
    """Drive a UserProxy <-> Pi conversation.

    Returns (chat history, trace turns, final session id). The trace turns are
    load_trace-schema dicts accumulated from each /ask response, ready to write
    directly. The final session id may differ from ``session_id`` if a null turn
    triggered a fresh-session retry; the caller should tear down the returned id.

    On a null turn (see pi_client.is_null_turn) — a transient model stall that
    settles with no answer/steps/tokens and would fail the whole trial at eval
    time — a fresh session is created on the same workspace via ``new_session``,
    prior user turns are replayed to rebuild the model's chat history, the old
    session is dropped via ``drop_session``, and the stalled turn is retried
    (up to ``max_turn_retries`` times). If ``new_session`` is not provided, the
    turn is recorded as-is (no retry).
    """
    llm_client = LiteLLMClient(model=user_proxy_cfg.model, max_tokens=user_proxy_cfg.max_tokens)
    user_proxy = UserProxyAgent(
        llm_client=llm_client,
        task_summary=criteria.task_summary,
        terminating_conditions=[TerminatingCondition()],
        config={USE_EXPERT_AGENT: user_proxy_cfg.use_expert_agent},
    )
    chat = ChatHistory(id=session_id, conversations=[])
    turns: list[dict] = []
    prev_id: Optional[str] = None
    loop = asyncio.get_event_loop()

    sid = session_id  # mutable: a null-turn retry may swap in a fresh session

    async def _ask(target_sid: str, utterance: str) -> dict:
        return await loop.run_in_executor(
            None, lambda: pi_client.ask(base_url, target_sid, utterance, ask_timeout)
        )

    max_turns = criteria.max_turns

    logger.info("=" * 70)
    logger.info("%s | session=%s  max_turns=%d", trial_label, session_id, max_turns)
    logger.info("task: %s", criteria.task_summary)
    logger.info("=" * 70)

    conv_turn = 0
    while conv_turn < max_turns:
        conv_turn += 1
        logger.info("\n====== %s | turn %d/%d ======", trial_label, conv_turn, max_turns)

        # Generate user message.
        #
        # UserProxyAgent.generate_message_from_chat_history() is async but
        # internally uses synchronous HTTP calls (LiteLLM). Calling it directly
        # on the event loop would block the loop and starve concurrent trials.
        # The workaround: run_in_executor moves it to a thread-pool thread, and
        # run_coroutine_threadsafe schedules the coroutine back on the main loop.
        user_message: Optional[UserProxyMessage] = None
        for attempt in range(3):
            try:
                user_message = await loop.run_in_executor(
                    None,
                    lambda: asyncio.run_coroutine_threadsafe(
                        user_proxy.generate_message_from_chat_history(chat), loop
                    ).result(),
                )
                break
            except Exception as exc:
                is_transient = "060011" in str(exc) or "empty user proxy" in str(exc).lower()
                if is_transient and attempt < 2:
                    await asyncio.sleep(2 ** attempt)
                else:
                    logger.info("User proxy ended: %s", exc)
                    break
        if user_message is None:
            break

        if user_message.check and not user_message.message_str:
            logger.info("Terminating (empty message with check): %s", user_message.check)
            break

        logger.info("[user] %s", user_message.message_str)

        # Run one Pi turn over HTTP (offloaded so the event loop stays free).
        resp = await _ask(sid, user_message.message_str)

        # Null turn (transient stall): retry on a fresh session, replaying prior
        # user turns to rebuild context. Workspace state is preserved (same
        # bind mount); only the model's in-memory chat history is rebuilt.
        if pi_client.is_null_turn(resp) and new_session is not None:
            for r in range(max_turn_retries):
                logger.warning(
                    "[%s] null turn (0 steps / 0 tokens, %sms) — fresh-session retry %d/%d",
                    trial_label, resp.get("latency_in_ms"), r + 1, max_turn_retries,
                )
                new_sid = await loop.run_in_executor(None, new_session)
                # Replay prior user messages so the fresh session has context.
                # Replay output is discarded; a replay stall is tolerated.
                for past in chat.conversations:
                    try:
                        await _ask(new_sid, past.user_message.message_str)
                    except Exception as exc:
                        logger.warning("[%s] replay turn failed (ignored): %s", trial_label, exc)
                if drop_session is not None:
                    await loop.run_in_executor(None, lambda s=sid: drop_session(s))
                sid = new_sid
                resp = await _ask(sid, user_message.message_str)
                if not pi_client.is_null_turn(resp):
                    logger.info("[%s] fresh-session retry recovered the turn", trial_label)
                    break
            else:
                logger.warning(
                    "[%s] turn still null after %d retr%s; recording as-is",
                    trial_label, max_turn_retries, "y" if max_turn_retries == 1 else "ies",
                )

        agent_text = resp.get("answer", "")
        usage = resp.get("usage") or {}

        # Terminating turn (check set, e.g. "END_CONVERSATION") with an empty
        # reply: substitute a placeholder so this turn isn't recorded with an
        # empty agent_response (which fails the trial at eval time). Applied ONLY
        # to the terminating turn — real turns keep their (possibly empty) answer.
        if user_message.check is not None and not agent_text.strip():
            agent_text = _TERMINATION_PLACEHOLDER
            resp["answer"] = _TERMINATION_PLACEHOLDER

        logger.info("[agent] %s", agent_text[:200])
        logger.info("[stats] tokens=%s cost=%s latency=%sms",
                    usage.get("total"), usage.get("cost"), resp.get("latency_in_ms"))

        chat.conversations.append(ConversationTurn(
            id=str(uuid4()),
            user_message=user_message,
            agent_responses=[ResponseFromAgent(response_str=agent_text)],
        ))
        turns.append(pi_client.turn_to_trace_dict(len(turns), user_message.message_str, resp, prev_id))
        prev_id = str(len(turns) - 1)

        if user_message.check is not None:
            logger.info("Terminating condition met: %s", user_message.check)
            break
    else:
        logger.info("Reached max_turns (%d).", max_turns)

    logger.info("Conversation done. %d turn(s).", len(chat.conversations))
    return chat, turns, sid


# ── Single trial ─────────────────────────────────────────────────────────────

async def run_single_trial(
    test_case_path: str,
    base_url: str,
    env_template: str,
    workspace_root: str,
    active_skills: List[str],
    user_proxy_cfg: UserProxyConfig,
    output_dir: str,
    trial_id: int,
    n_trials: int,
    ask_timeout: float = DEFAULT_ASK_TIMEOUT,
) -> TrialResult:
    """Run one conversation trial: workspace seed → session → conversation → artifacts."""
    criteria = parse_test_case(test_case_path)
    case_id = criteria.case_id
    run_id = str(uuid4())
    trial_label = f"{case_id} | trial {trial_id}/{n_trials}"
    loop = asyncio.get_event_loop()

    case_dir = os.path.join(output_dir, case_id, f"trial_{trial_id}")
    host_ws = Path(workspace_root) / case_id / f"trial_{trial_id}" / "workspace"

    logger.info("[%s] starting (run=%s)", trial_label, run_id)

    sid: Optional[str] = None
    try:
        # Seed the workspace BEFORE creating the session: the gateway bind-mounts
        # this directory into the container at `docker run` time.
        await loop.run_in_executor(None, lambda: _seed_workspace(host_ws, env_template, active_skills))
        sid = await loop.run_in_executor(
            None, lambda: pi_client.create_session(base_url, str(host_ws.resolve()))
        )
        logger.info("[%s] session ready: %s", trial_label, sid)

        # Callbacks so run_conversation can swap in a fresh session on a null turn
        # (same workspace). run_single_trial retains ownership: the returned final
        # sid is what the finally-block tears down.
        mk_session = lambda: pi_client.create_session(base_url, str(host_ws.resolve()))
        rm_session = lambda s: pi_client.delete_session(base_url, s)

        chat, turns, sid = await run_conversation(
            criteria, user_proxy_cfg, base_url, sid, case_id, trial_label, ask_timeout,
            new_session=mk_session, drop_session=rm_session,
        )

        # Save artifacts (no DB — trace comes straight from the in-memory turns).
        os.makedirs(case_dir, exist_ok=True)
        Path(case_dir, "conversation.json").write_text(json.dumps({
            "run_id": run_id,
            "session_id": sid,
            "conversations": [dataclasses.asdict(c) for c in chat.conversations],
        }, indent=2, default=str))
        shutil.copy2(test_case_path, os.path.join(case_dir, os.path.basename(test_case_path)))
        pi_client.write_trace(Path(case_dir), turns)

        return TrialResult(
            trial_id=trial_id, sample_id=case_id, run_id=run_id,
            session_id=sid, total_turns=len(chat.conversations), case_dir=case_dir,
        )

    except Exception as exc:
        logger.error("[%s] failed: %s", trial_label, exc, exc_info=True)
        return TrialResult(
            trial_id=trial_id, sample_id=case_id, run_id=run_id,
            session_id=sid, status="failed", error=str(exc),
        )
    finally:
        if sid:
            await loop.run_in_executor(None, lambda: pi_client.delete_session(base_url, sid))
            logger.info("[%s] session deleted", trial_label)


# ── Resume helpers ───────────────────────────────────────────────────────────

def _load_failed_trials(job_dir: str) -> List[Dict[str, Any]]:
    """Read runs_summary.json and return the list of failed run entries."""
    summary_path = os.path.join(job_dir, "runs_summary.json")
    if not os.path.exists(summary_path):
        raise FileNotFoundError(f"No runs_summary.json in {job_dir}")
    data = json.loads(Path(summary_path).read_text())
    return [r for r in data.get("results", []) if r.get("status") == "failed"]


def _match_case_file(sample_id: str, case_files: List[str]) -> Optional[str]:
    """Find the case file whose parsed case_id matches sample_id."""
    for cf in case_files:
        criteria = parse_test_case(cf)
        if criteria.case_id == sample_id:
            return cf
    return None


async def run_resume(
    job_dir: str,
    case_files: List[str],
    base_url: str,
    env_template: str,
    workspace_root: str,
    active_skills: List[str],
    user_proxy_cfg: UserProxyConfig,
    n_trials: int,
    max_workers: int,
    ask_timeout: float = DEFAULT_ASK_TIMEOUT,
) -> List[TrialResult]:
    """Re-run only the failed trials from a previous job. Results go to same job dir."""
    failed = _load_failed_trials(job_dir)
    if not failed:
        logger.info("No failed trials found — nothing to resume.")
        return []

    logger.info("Resuming %d failed trial(s) from %s", len(failed), job_dir)

    sem = asyncio.Semaphore(max_workers)

    async def _run(entry: Dict[str, Any]) -> TrialResult:
        sid = entry["sample_id"]
        tid = entry["trial_id"]
        cf = _match_case_file(sid, case_files)
        if cf is None:
            logger.error("Cannot find test case for %s — skipping", sid)
            return TrialResult(
                trial_id=tid, sample_id=sid, run_id="",
                status="failed", error=f"Test case YAML not found for {sid}",
            )
        async with sem:
            return await run_single_trial(
                cf, base_url, env_template, workspace_root, active_skills,
                user_proxy_cfg, job_dir, tid, n_trials, ask_timeout,
            )

    return list(await asyncio.gather(*[_run(e) for e in failed]))


def merge_runs_summary(job_dir: str, new_results: List[TrialResult]) -> None:
    """Merge new results into existing runs_summary.json.

    For each (sample_id, trial_id) in new_results, replace the old entry.
    """
    summary_path = os.path.join(job_dir, "runs_summary.json")
    data = json.loads(Path(summary_path).read_text())
    old_results = data.get("results", [])

    new_keys = {(r.sample_id, r.trial_id) for r in new_results}
    merged = [r for r in old_results if (r["sample_id"], r["trial_id"]) not in new_keys]
    merged.extend(r.to_dict() for r in new_results)

    ok = sum(1 for r in merged if r.get("status") == "success")
    fail = sum(1 for r in merged if r.get("status") == "failed")
    data = {
        "total": len(merged),
        "successful": ok,
        "failed": fail,
        "results": merged,
    }
    Path(summary_path).write_text(json.dumps(data, indent=2, default=str))
    logger.info("Updated runs_summary.json: %d/%d succeeded", ok, len(merged))


# ── Batch execution ──────────────────────────────────────────────────────────

async def run_all(
    case_files: List[str],
    base_url: str,
    env_template: str,
    workspace_root: str,
    active_skills: List[str],
    user_proxy_cfg: UserProxyConfig,
    output_dir: str,
    n_trials: int,
    max_workers: int,
    ask_timeout: float = DEFAULT_ASK_TIMEOUT,
) -> List[TrialResult]:
    """Run all cases x trials with bounded concurrency."""
    sem = asyncio.Semaphore(max_workers)

    async def _run(path: str, trial: int) -> TrialResult:
        async with sem:
            return await run_single_trial(
                path, base_url, env_template, workspace_root, active_skills,
                user_proxy_cfg, output_dir, trial, n_trials, ask_timeout,
            )

    tasks = [_run(p, t) for p in case_files for t in range(1, n_trials + 1)]
    return list(await asyncio.gather(*tasks))


def save_runs_summary(results: List[TrialResult], output_dir: str, n_trials: int = 0) -> None:
    """Write runs_summary.json to the output directory."""
    ok = [r for r in results if r.status == "success"]
    fail = [r for r in results if r.status == "failed"]
    n_samples = len(set(r.sample_id for r in results))
    expected = n_samples * n_trials if n_trials else len(results)
    data = {
        "n_samples": n_samples,
        "n_trials": n_trials,
        "expected_runs": expected,
        "successful": len(ok),
        "failed": len(fail),
        "results": [r.to_dict() for r in results],
    }
    path = os.path.join(output_dir, "runs_summary.json")
    Path(path).write_text(json.dumps(data, indent=2, default=str))
    logger.info("Saved runs summary -> %s", path)


# ── CLI ──────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Pi conversation runner")
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
                        help="Resume failed trials from a previous job dir")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(message)s",
        handlers=[logging.StreamHandler(sys.stdout)],
    )

    raw_cfg = load_runner_config(args.config)
    user_proxy_cfg = user_proxy_config_from(raw_cfg)
    pi_cfg = pi_config_from(raw_cfg)

    base_url = args.base_url or pi_cfg.base_url
    env_template = args.env_template or pi_cfg.workspace_template
    workspace_root = args.workspace_root or pi_cfg.workspace_root
    ask_timeout = args.ask_timeout if args.ask_timeout is not None else pi_cfg.ask_timeout

    active = resolve_active_skills(env_template, raw_cfg)

    # Preflight: fail fast with a clear message if the gateway is unreachable.
    try:
        pi_client.healthz(base_url)
    except pi_client.PiGatewayError as exc:
        logger.error("Pi gateway not reachable at %s: %s", base_url, exc)
        sys.exit(1)

    case_files = []
    for p in args.path or [str(Path(__file__).parent / "test_cases")]:
        case_files.extend(iter_case_files(p))

    if args.resume:
        job_dir = args.resume
        logger.info("RESUME mode: re-running failed trials from %s", job_dir)
        results = asyncio.run(run_resume(
            job_dir, case_files, base_url, env_template, workspace_root, active,
            user_proxy_cfg, args.n_trials, args.max_workers, ask_timeout,
        ))
        if results:
            merge_runs_summary(job_dir, results)
            ok = sum(1 for r in results if r.status == "success")
            logger.info("Resume done — %d/%d retried succeeded", ok, len(results))
        else:
            logger.info("Nothing to resume.")
    else:
        ts = _dt.datetime.now().strftime("%Y-%m-%d__%H-%M-%S")
        output_dir = os.path.join(args.output_dir, "jobs", ts)
        os.makedirs(output_dir, exist_ok=True)

        Path(output_dir, "skills_used.json").write_text(json.dumps({
            "active_skills": active, "count": len(active),
        }, indent=2))

        logger.info("Running %d case(s) x %d trial(s) | workers=%d | skills=%s",
                    len(case_files), args.n_trials, args.max_workers, active)

        results = asyncio.run(run_all(
            case_files, base_url, env_template, workspace_root, active,
            user_proxy_cfg, output_dir, args.n_trials, args.max_workers, ask_timeout,
        ))
        save_runs_summary(results, output_dir, args.n_trials)

        ok = sum(1 for r in results if r.status == "success")
        logger.info("All runs done — %d/%d succeeded", ok, len(results))
        for r in results:
            if r.status == "failed":
                logger.info("  FAIL %s (trial %d) — %s", r.sample_id, r.trial_id, r.error)


if __name__ == "__main__":
    main()
