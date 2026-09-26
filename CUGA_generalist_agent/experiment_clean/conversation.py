"""Conversation runner: drive CUGA conversations and save raw artifacts.

Usage (conversation only):
    PYTHONPATH="agent-inspect/src:." python -m experiment_clean.conversation \\
        experiment_clean/test_cases/tau2retail --n-trials 5 --max-workers 5 \\
        --config experiment_clean/runner_config.yaml
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
import sqlite3
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional
from uuid import uuid4

# ── CUGA env (must precede cuga imports) ─────────────────────────────────────
os.environ.setdefault("DYNACONF_SKILLS__ENABLED", "true")
os.environ.setdefault("DYNACONF_ADVANCED_FEATURES__ENABLE_SHELL_TOOL", "true")
os.environ.setdefault("DYNACONF_ADVANCED_FEATURES__ENABLE_FILESYSTEM_TOOLS", "true")
os.environ.setdefault("DYNACONF_ADVANCED_FEATURES__REFLECTION_ENABLED", "true")
os.environ.setdefault("DYNACONF_ADVANCED_FEATURES__SANDBOX_MODE", "opensandbox")
os.environ.setdefault("DYNACONF_ADVANCED_FEATURES__OPENSANDBOX_SANDBOX", "true")
os.environ.setdefault("DYNACONF_STORAGE__PRESERVE_CONFIGS_ON_STARTUP", "local")

from cuga.sdk import CugaAgent
from cuga.backend.cuga_graph.nodes.cuga_lite.executors.code_executor import CodeExecutor
from cuga.backend.cuga_graph.nodes.human_in_the_loop.followup_model import (
    ActionResponse,
    ActionType,
)
from cuga.backend.server.demo_manage_setup import setup_demo_manage_config
from cuga_cli import _run_turn_with_stream, _save_to_db, _seed_policies

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

from experiment_clean.config import (
    DEFAULT_DB_PATH,
    DEFAULT_ENV_TEMPLATE,
    DEFAULT_OUTPUT_ROOT,
    DEFAULT_RUNNER_CONFIG,
    SKILLS_FOLDER,
    UserProxyConfig,
    load_runner_config,
    silence_litellm,
    user_proxy_config_from,
    skills_from,
)
from experiment_clean.testcase import TestCaseCriteria, parse_test_case, iter_case_files

logger = logging.getLogger("experiment_clean.conversation")
silence_litellm()


# ── Result dataclass ─────────────────────────────────────────────────────────

@dataclass
class TrialResult:
    trial_id: int
    sample_id: str
    run_id: str
    thread_id: Optional[str] = None
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

def _make_resume(thread_id: str, text: str) -> ActionResponse:
    return ActionResponse(
        action_id="tool_approval",
        response_type=ActionType.CONFIRMATION,
        text_response=text,
        timestamp=_dt.datetime.now().isoformat(),
        user_id=thread_id,
        session_id=thread_id,
    )


def _seed_env(thread_id: str, env_template_dir: str) -> int:
    """Copy env template files into the sandbox workspace for this thread."""
    from cuga.backend.cuga_graph.nodes.cuga_lite.executors.filesystem.paths import (
        thread_workspace_root,
    )
    src = Path(env_template_dir)
    if not src.is_dir():
        return 0
    dest = thread_workspace_root(thread_id)
    dest.mkdir(parents=True, exist_ok=True)
    copied = 0
    for item in src.iterdir():
        target = dest / item.name
        if item.is_dir():
            shutil.copytree(item, target, dirs_exist_ok=True)
        else:
            shutil.copy2(item, target)
        copied += 1
    if copied:
        logger.info("[env] seeded %d item(s) into %s", copied, dest)
    return copied


def _backup_db(db_path: str, thread_ids: List[str], dest_path: str) -> None:
    """Write a filtered SQLite backup containing only this trial's data.

    Why not shutil.copy2: CUGA uses a single shared database (cuga.db) for
    all threads. A full copy would include every other trial's data and grow
    large. Instead we create a fresh database and selectively copy:

      - Thread-scoped tables (conversation_history, stream_events): only rows
        matching the given thread_ids.
      - All other regular tables: copied in full (config, metadata, etc.).
      - Virtual tables (e.g. sqlite-vec): copied only if the sqlite_vec
        extension is available, since they require it to be created.
      - Shadow tables (internal backing tables for virtual tables, named
        "<virtual_table>_*"): skipped — they are auto-managed by SQLite
        when the virtual table is populated.
      - Indexes: recreated; failures silently ignored (index may reference
        a skipped virtual table).
    """
    thread_ids = sorted({t for t in thread_ids if t})
    if os.path.exists(dest_path):
        os.remove(dest_path)
    dst = sqlite3.connect(dest_path)
    try:
        has_vec = False
        try:
            import sqlite_vec
            dst.enable_load_extension(True)
            sqlite_vec.load(dst)
            has_vec = True
        except Exception:
            pass
        dst.execute("ATTACH DATABASE ? AS src", (db_path,))
        objs = dst.execute(
            "SELECT name, type, sql FROM src.sqlite_master "
            "WHERE name NOT LIKE 'sqlite_%' AND sql IS NOT NULL"
        ).fetchall()
        tables = [(n, sql) for (n, typ, sql) in objs if typ == "table"]
        indexes = [(n, sql) for (n, typ, sql) in objs if typ == "index"]
        virtual = [n for (n, sql) in tables if "CREATE VIRTUAL TABLE" in sql.upper()]
        shadow = {
            n for (n, _) in tables for v in virtual
            if n != v and n not in virtual and n.startswith(v + "_")
        }
        thread_tables = {"conversation_history", "stream_events"}
        ph = ",".join("?" * len(thread_ids)) if thread_ids else ""
        for name, sql in tables:
            if name in shadow:
                continue
            if name in virtual and not has_vec:
                continue
            dst.execute(sql)
            if name in virtual:
                cols = [r[1] for r in dst.execute(f'PRAGMA table_info("{name}")')]
                collist = ", ".join(["rowid"] + cols)
                dst.execute(f'INSERT INTO main."{name}" ({collist}) SELECT {collist} FROM src."{name}"')
            elif name in thread_tables:
                if thread_ids:
                    dst.execute(
                        f'INSERT INTO main."{name}" SELECT * FROM src."{name}" '
                        f"WHERE thread_id IN ({ph})", thread_ids,
                    )
            else:
                dst.execute(f'INSERT INTO main."{name}" SELECT * FROM src."{name}"')
        for name, sql in indexes:
            try:
                dst.execute(sql)
            except sqlite3.OperationalError:
                pass
        dst.commit()
    finally:
        try:
            dst.execute("DETACH DATABASE src")
        except Exception:
            pass
        dst.close()


def setup_skills(skills_folder: str, skill_names: List[str]) -> List[str]:
    """Enable whitelisted skills, disable the rest via SKILL.md rename.

    Non-destructive: disabled skills get SKILL.md → SKILL.md.off.
    CUGA discovers skills via rglob("SKILL.md") so .off files are invisible.
    Returns list of enabled skill names.
    """
    skills_dir = Path(skills_folder) / "skills"
    if not skills_dir.is_dir():
        return []

    enabled, disabled = [], []
    for skill_dir in sorted(skills_dir.iterdir()):
        if not skill_dir.is_dir():
            continue
        md = skill_dir / "SKILL.md"
        off = skill_dir / "SKILL.md.off"
        if skill_dir.name in skill_names:
            if off.exists() and not md.exists():
                off.rename(md)
            if md.exists():
                enabled.append(skill_dir.name)
        else:
            if md.exists():
                md.rename(off)
            disabled.append(skill_dir.name)

    logger.info("Skills: enabled=%s disabled=%s", enabled, disabled)
    return enabled


def resolve_active_skills(skills_folder: str, raw_cfg: dict) -> List[str]:
    """Apply the skills whitelist from config, or discover all skills on disk.

    Used by both conversation.py and e2e.py so the logic stays in one place.
    """
    skill_list = skills_from(raw_cfg)
    if skill_list is not None:
        return setup_skills(skills_folder, skill_list)
    skills_dir = Path(skills_folder) / "skills"
    if skills_dir.is_dir():
        return [d.name for d in skills_dir.iterdir() if d.is_dir()]
    return []


# ── Conversation loop ────────────────────────────────────────────────────────

async def run_conversation(
    criteria: TestCaseCriteria,
    user_proxy_cfg: UserProxyConfig,
    cuga_agent: CugaAgent,
    thread_id: str,
    case_id: str,
    trial_label: str,
) -> ChatHistory:
    """Drive a UserProxy <-> CUGA conversation. Returns the full chat history."""
    llm_client = LiteLLMClient(model=user_proxy_cfg.model, max_tokens=user_proxy_cfg.max_tokens)
    user_proxy = UserProxyAgent(
        llm_client=llm_client,
        task_summary=criteria.task_summary,
        terminating_conditions=[TerminatingCondition()],
        config={USE_EXPERT_AGENT: user_proxy_cfg.use_expert_agent},
    )
    chat = ChatHistory(id=thread_id, conversations=[])
    loop = asyncio.get_event_loop()

    max_turns = criteria.max_turns

    logger.info("=" * 70)
    logger.info("%s | thread=%s  max_turns=%d", trial_label, thread_id, max_turns)
    logger.info("task: %s", criteria.task_summary)
    logger.info("=" * 70)

    conv_turn = 0
    while conv_turn < max_turns:
        conv_turn += 1
        logger.info("\n====== %s | turn %d/%d ======", trial_label, conv_turn, max_turns)

        # Generate user message.
        #
        # UserProxyAgent.generate_message_from_chat_history() is async but
        # internally uses synchronous HTTP calls (LiteLLM). Calling it
        # directly on the event loop would block the loop and starve
        # concurrent trials. The workaround:
        #   1. run_in_executor → moves execution to a thread-pool thread
        #   2. run_coroutine_threadsafe → schedules the coroutine back on
        #      the main event loop (required because the method is async)
        #   3. .result() → blocks the thread until the coroutine completes
        # Net effect: the event loop stays free while the blocking call runs.
        user_message = None
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

        logger.info("[user] %s", user_message.message_str)

        # Run CUGA turn
        agent_text, interrupted = await _run_turn_with_stream(
            cuga_agent, thread_id, user_message.message_str
        )

        # Handle HITL: pass agent's approval request to UserProxy for a
        # contextual response. CUGA interprets the dynamic text_response via LLM.
        while interrupted and conv_turn < max_turns:
            # Record the interrupted turn so UserProxy sees the full history
            chat.conversations.append(ConversationTurn(
                id=str(uuid4()),
                user_message=user_message,
                agent_responses=[ResponseFromAgent(response_str=agent_text)],
            ))
            conv_turn += 1
            logger.info("\n====== %s | turn %d/%d (HITL) ======", trial_label, conv_turn, max_turns)

            # Let UserProxy generate a response to the HITL message
            hitl_message = await loop.run_in_executor(
                None,
                lambda: asyncio.run_coroutine_threadsafe(
                    user_proxy.generate_message_from_chat_history(chat), loop
                ).result(),
            )
            if hitl_message is None:
                raise RuntimeError("UserProxy returned None during HITL")

            logger.info("[user (HITL)] %s", hitl_message.message_str)

            agent_text, interrupted = await _run_turn_with_stream(
                cuga_agent, thread_id, None,
                resume=_make_resume(thread_id, hitl_message.message_str),
            )
            user_message = hitl_message

        # Always append the final turn — whether the inner loop ran or not.
        chat.conversations.append(ConversationTurn(
            id=str(uuid4()),
            user_message=user_message,
            agent_responses=[ResponseFromAgent(response_str=agent_text)],
        ))

        if user_message.check is not None:
            logger.info("Terminating condition met: %s", user_message.check)
            break
    else:
        logger.info("Reached max_turns (%d).", max_turns)

    logger.info("Conversation done. %d turn(s).", len(chat.conversations))
    return chat


# ── Single trial ─────────────────────────────────────────────────────────────

async def run_single_trial(
    test_case_path: str,
    db_path: str,
    skills_folder: str,
    env_template_dir: str,
    user_proxy_cfg: UserProxyConfig,
    output_dir: str,
    trial_id: int,
    n_trials: int,
) -> TrialResult:
    """Run one conversation trial: sandbox setup → conversation → save artifacts."""
    criteria = parse_test_case(test_case_path)
    case_id = criteria.case_id
    run_id = str(uuid4())
    thread_id = str(uuid4())
    trial_label = f"{case_id} | trial {trial_id}/{n_trials}"

    logger.info("[%s] starting (run=%s thread=%s)", trial_label, run_id, thread_id)

    cuga_agent = CugaAgent(enable_skills=True, skills_folder=skills_folder)
    executor = CodeExecutor._get_opensandbox_executor()
    case_dir = os.path.join(output_dir, case_id, f"trial_{trial_id}")

    try:
        await executor.get_interpreter_for_thread(thread_id)
        logger.info("[%s] sandbox ready", trial_label)

        _seed_env(thread_id, env_template_dir)

        chat = await run_conversation(
            criteria, user_proxy_cfg, cuga_agent, thread_id, case_id, trial_label,
        )

        await _save_to_db(cuga_agent, thread_id)

        # Save artifacts
        os.makedirs(case_dir, exist_ok=True)
        Path(case_dir, "conversation.json").write_text(json.dumps({
            "thread_id": thread_id,
            "conversations": [dataclasses.asdict(c) for c in chat.conversations],
        }, indent=2, default=str))
        Path(case_dir, "thread_id.txt").write_text(thread_id)
        shutil.copy2(test_case_path, os.path.join(case_dir, os.path.basename(test_case_path)))

        db_dest = os.path.join(case_dir, f"{case_id}_trial_{trial_id}_cuga_db.db")
        try:
            _backup_db(db_path, [thread_id], db_dest)
        except Exception as exc:
            logger.warning("DB backup failed: %s", exc)

        return TrialResult(
            trial_id=trial_id, sample_id=case_id, run_id=run_id,
            thread_id=thread_id, total_turns=len(chat.conversations), case_dir=case_dir,
        )

    except Exception as exc:
        logger.error("[%s] failed: %s", trial_label, exc)
        return TrialResult(
            trial_id=trial_id, sample_id=case_id, run_id=run_id,
            thread_id=thread_id, status="failed", error=str(exc),
        )
    finally:
        try:
            await executor.release_sandbox(thread_id)
            logger.info("[%s] sandbox released", trial_label)
        except Exception:
            pass


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
    db_path: str,
    skills_folder: str,
    env_template_dir: str,
    user_proxy_cfg: UserProxyConfig,
    n_trials: int,
    max_workers: int,
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
                cf, db_path, skills_folder, env_template_dir,
                user_proxy_cfg, job_dir, tid, n_trials,
            )

    results = list(await asyncio.gather(*[_run(e) for e in failed]))
    return results


def merge_runs_summary(job_dir: str, new_results: List[TrialResult]) -> None:
    """Merge new results into existing runs_summary.json.

    For each (sample_id, trial_id) in new_results, replace the old entry.
    """
    summary_path = os.path.join(job_dir, "runs_summary.json")
    data = json.loads(Path(summary_path).read_text())
    old_results = data.get("results", [])

    # Build key set of new results for replacement
    new_keys = {(r.sample_id, r.trial_id) for r in new_results}

    # Keep old results that are not being replaced
    merged = [r for r in old_results if (r["sample_id"], r["trial_id"]) not in new_keys]
    # Add new results
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
    db_path: str,
    skills_folder: str,
    env_template_dir: str,
    user_proxy_cfg: UserProxyConfig,
    output_dir: str,
    n_trials: int,
    max_workers: int,
) -> List[TrialResult]:
    """Run all cases x trials with bounded concurrency."""
    sem = asyncio.Semaphore(max_workers)

    async def _run(path: str, trial: int) -> TrialResult:
        async with sem:
            return await run_single_trial(
                path, db_path, skills_folder, env_template_dir,
                user_proxy_cfg, output_dir, trial, n_trials,
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
    parser = argparse.ArgumentParser(description="CUGA conversation runner")
    parser.add_argument("path", nargs="*", help="YAML file(s) or directory")
    parser.add_argument("--n-trials", type=int, default=1)
    parser.add_argument("--max-workers", type=int, default=5)
    parser.add_argument("--config", default=DEFAULT_RUNNER_CONFIG)
    parser.add_argument("--db-path", default=DEFAULT_DB_PATH)
    parser.add_argument("--skills-folder", default=SKILLS_FOLDER)
    parser.add_argument("--env-template", default=DEFAULT_ENV_TEMPLATE)
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
    active = resolve_active_skills(args.skills_folder, raw_cfg)

    setup_demo_manage_config("demo_skills")
    asyncio.run(_seed_policies())

    # Gather case files
    case_files = []
    for p in args.path or [str(Path(__file__).parent / "test_cases")]:
        case_files.extend(iter_case_files(p))

    if args.resume:
        # ── Resume mode: re-run only failed trials ───────────────────────
        job_dir = args.resume
        logger.info("RESUME mode: re-running failed trials from %s", job_dir)

        results = asyncio.run(run_resume(
            job_dir, case_files, args.db_path, args.skills_folder,
            args.env_template, user_proxy_cfg, args.n_trials, args.max_workers,
        ))
        if results:
            merge_runs_summary(job_dir, results)
            ok = sum(1 for r in results if r.status == "success")
            logger.info("Resume done — %d/%d retried succeeded", ok, len(results))
        else:
            logger.info("Nothing to resume.")
    else:
        # ── Normal mode ──────────────────────────────────────────────────
        ts = _dt.datetime.now().strftime("%Y-%m-%d__%H-%M-%S")
        output_dir = os.path.join(args.output_dir, "jobs", ts)
        os.makedirs(output_dir, exist_ok=True)

        Path(output_dir, "skills_used.json").write_text(json.dumps({
            "active_skills": active, "count": len(active),
        }, indent=2))

        logger.info("Running %d case(s) x %d trial(s) | workers=%d | skills=%s",
                    len(case_files), args.n_trials, args.max_workers, active)

        results = asyncio.run(run_all(
            case_files, args.db_path, args.skills_folder, args.env_template,
            user_proxy_cfg, output_dir, args.n_trials, args.max_workers,
        ))
        save_runs_summary(results, output_dir, args.n_trials)

        ok = sum(1 for r in results if r.status == "success")
        logger.info("All runs done — %d/%d succeeded", ok, len(results))
        for r in results:
            if r.status == "failed":
                logger.info("  FAIL %s (trial %d) — %s", r.sample_id, r.trial_id, r.error)


if __name__ == "__main__":
    main()
