#!/usr/bin/env python3
"""Spawn N headless Pi coding-agent containers and drive each over RPC (JSON on stdio).

Pi is one-session-per-process by design, so parallelism = one container per Pi instance.
Each ``PiContainer`` owns a ``docker run -i`` subprocess, writes JSON commands to the
container's stdin, and reads JSON events/responses from its stdout (LF-framed, one per line;
see packages/coding-agent/docs/rpc.md).

Requires: Docker on PATH, an image built from this directory's Dockerfile (default tag
``pi-sandbox``), and ``AZURE_API_KEY`` in the environment (forwarded into each container).

CLI:
    export AZURE_API_KEY=...
    # one-shot: same prompt to N containers, then exit
    python spawn_pi.py --n 4 --image pi-sandbox --prompt "say hi in 3 words"
    # long-lived: open one instance, feed utterances on stdin (one per line), Ctrl-D to close
    python spawn_pi.py --serve --image pi-sandbox

Library:
    from spawn_pi import PiInstance, PiPool, PiContainer, spawn_n

    # long-lived managed instance your runner pings across turns
    with PiInstance("pi-sandbox") as inst:
        print(inst.ask("what is 2+2?"))
        print(inst.ask("multiply that by 10"))   # same conversation
        print(inst.stats())

    # N managed instances, pinged by index
    with PiPool(4, image="pi-sandbox") as pool:
        print(pool.ask(0, "hello"))
        print(pool.ask(1, "separate conversation"))
"""

from __future__ import annotations

import argparse
import json
import os
import queue
import re
import subprocess
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable, Optional

# Event emitted when an agent run is fully settled: no automatic retry, compaction retry,
# or queued continuation remains. This is the correct "turn is done" signal (agent_end may
# still be followed by retries/continuations). See rpc.md event table.
SETTLED_EVENT = "agent_settled"

DEFAULT_IMAGE = "pi-sandbox"
DEFAULT_PROMPT_TIMEOUT = 600.0  # seconds to wait for a prompt to settle
DEFAULT_REQUEST_TIMEOUT = 30.0  # seconds to wait for a command response
DEFAULT_PROMPT_RETRIES = 1  # extra attempts if a turn fails to settle (abort + resend)

# Per-container logs are written under here, one subdir per container (keyed by
# its name, which carries the session id). Currently captures the container's
# stderr — Pi's own error/warning output, otherwise piped but discarded.
DEFAULT_LOG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "container_logs")


class PiError(RuntimeError):
    """Raised on RPC-level failures (rejected command, timeout, container exit)."""


def _content_text(content: Any) -> str:
    """Flatten an RPC content field (string or list of {type,text} blocks) to text."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            b.get("text", "") for b in content
            if isinstance(b, dict) and b.get("type") == "text"
        )
    return ""


def _skill_from_utterance(utterance: str) -> list[dict]:
    """Skill calls invoked explicitly via `/skill:name` in the utterance.

    `/skill:name` is expanded into the prompt *before* the turn runs (rpc.md "Input expansion"),
    so the utterance is the only place this invocation mode is observable.
    """
    calls = []
    for m in re.finditer(r"/skill:([A-Za-z0-9._-]+)", utterance or ""):
        name = m.group(1)
        calls.append({"skill_id": f"skill:{name}", "skill_name": name})
    return calls


# A skill's SKILL.md path, e.g. ".../skills/brave-search/SKILL.md" -> "brave-search".
# Pi lists each skill's SKILL.md path in the system prompt; the model loads a skill by reading
# that file (skills.md "How Skills Work"), so a model-driven invocation surfaces as a read/bash
# tool step whose argument contains the SKILL.md path. This recovers that (otherwise invisible)
# case from the tool steps we already capture.
_SKILL_PATH_RE = re.compile(r"/skills/([A-Za-z0-9._-]+)/SKILL\.md\b")


def _skill_from_tool_step(step: dict) -> list[dict]:
    """Skill calls detected from a read/bash tool step that loads a SKILL.md."""
    if step.get("tool") not in ("read", "bash"):
        return []
    haystack = " ".join(str(a.get("value", "")) for a in step.get("tool_input_args") or [])
    calls = []
    for m in _SKILL_PATH_RE.finditer(haystack):
        name = m.group(1)
        calls.append({"skill_id": f"skill:{name}", "skill_name": name})
    return calls


def _build_turn(events: list[dict], utterance: str = "") -> dict:
    """Reconstruct structured steps + usage from one turn's captured event stream.

    Emits building blocks the runner reconstructs an agent-inspect TurnTrace from; it does not
    assemble the TurnTrace itself. Each step carries:
      - id            : stable per-turn step id (tool step -> toolCallId; else synthetic sN)
      - parent_ids    : [previous step's id] — a linear chain in emission order
      - tool / tool_input_args / tool_output : from tool_execution_start/end
      - is_error / status ("OK"|"ERROR") / error : tool failure, split out from output
      - agent_thought / text : from turn_end assistant content blocks
      - skill_calls   : skill invocations — from `/skill:name` in the utterance AND from
                        read/bash steps that load a `.../skills/<name>/SKILL.md`
      - latency_in_ms : wall-clock for tool steps (end arrival - start arrival)
    Tokens stay at turn level (Pi reports usage per message, not per step).
    """
    steps: list[dict] = []
    tool_index: dict[str, dict] = {}   # toolCallId -> step (to attach the matching end)
    usage = {"input": 0, "output": 0, "total": 0, "cost": 0.0}
    event_skill_calls: list[dict] = []   # from the harness `skill_invocation` event (authoritative)
    counter = 0

    def new_step(step_id: Optional[str] = None) -> dict:
        nonlocal counter
        counter += 1
        sid = step_id or f"s{counter}"
        step = {
            "id": sid,
            "parent_ids": [steps[-1]["id"]] if steps else [],
            "tool": None,
            "tool_input_args": [],
            "tool_output": None,
            "is_error": None,
            "status": None,
            "error": None,
            "agent_thought": None,
            "text": None,
            "skill_calls": [],
            "latency_in_ms": None,
        }
        steps.append(step)
        return step

    for ev in events:
        et = ev.get("type")

        if et == "tool_execution_start":
            args = ev.get("args") or {}
            step = new_step(ev.get("toolCallId"))
            step["tool"] = ev.get("toolName")
            step["tool_input_args"] = [{"name": k, "value": v} for k, v in args.items()]
            step["_start_ts"] = ev.get("_ts")
            if ev.get("toolCallId"):
                tool_index[ev["toolCallId"]] = step

        elif et == "tool_execution_end":
            step = tool_index.get(ev.get("toolCallId"))
            if step is not None:
                output = _content_text((ev.get("result") or {}).get("content"))
                step["tool_output"] = output
                is_error = bool(ev.get("isError"))
                step["is_error"] = is_error
                step["status"] = "ERROR" if is_error else "OK"
                if is_error:
                    step["error"] = output
                start_ts = step.pop("_start_ts", None)
                if start_ts is not None and ev.get("_ts") is not None:
                    step["latency_in_ms"] = (ev["_ts"] - start_ts) * 1000.0

        elif et == "skill_invocation":
            # Authoritative signal emitted by the Pi harness at the real invocation point
            # (both /skill:name expansion and model-driven SKILL.md loads). Preferred over
            # the client-side heuristics below. Attach to the most recent step if any.
            name = ev.get("skillName")
            if name:
                call = {"skill_id": f"skill:{name}", "skill_name": name,
                        "trigger": ev.get("trigger")}
                event_skill_calls.append(call)
                if steps:
                    steps[-1]["skill_calls"] = steps[-1]["skill_calls"] + [call]

        elif et in ("turn_end", "message_end"):
            msg = ev.get("message") or {}
            if msg.get("role") == "assistant":
                content = msg.get("content")
                if isinstance(content, list):
                    for block in content:
                        if not isinstance(block, dict):
                            continue
                        bt = block.get("type")
                        if bt == "thinking":
                            new_step()["agent_thought"] = block.get("thinking")
                        elif bt == "text":
                            new_step()["text"] = block.get("text")
                u = msg.get("usage") or {}
                usage["input"] += u.get("input") or 0
                usage["output"] += u.get("output") or 0
                cost = (u.get("cost") or {}).get("total")
                if cost:
                    usage["cost"] += cost

    # Aggregate skill invocations to the turn level (deduped by skill_id).
    #
    # Preferred source: the harness `skill_invocation` events captured above — authoritative,
    # covering both /skill:name expansion and model-driven SKILL.md loads, emitted at the real
    # invocation point. If the running Pi image predates that event, fall back to client-side
    # heuristics: /skill:name in the utterance, and read/bash steps that load a SKILL.md path.
    for step in steps:
        step.pop("_start_ts", None)   # drop timing scratch field

    turn_skill_calls: list[dict] = []
    seen: set[str] = set()

    def _add(calls: list[dict]) -> None:
        for c in calls:
            if c["skill_id"] not in seen:
                seen.add(c["skill_id"])
                turn_skill_calls.append(c)

    if event_skill_calls:
        # Harness told us directly; steps already carry their per-step attribution.
        _add(event_skill_calls)
    else:
        # Fallback heuristics (older Pi image with no skill_invocation event).
        utterance_calls = _skill_from_utterance(utterance)
        if utterance_calls and steps:
            steps[0]["skill_calls"] = utterance_calls
        _add(utterance_calls)
        for step in steps:
            tool_calls = _skill_from_tool_step(step)
            if tool_calls:
                # merge with any already on this step (e.g. first step also had an utterance call)
                step["skill_calls"] = step["skill_calls"] + tool_calls
                _add(tool_calls)

    usage["total"] = usage["input"] + usage["output"]
    return {"steps": steps, "usage": usage, "skill_calls": turn_skill_calls}


class PiContainer:
    """One headless Pi RPC instance running in its own Docker container.

    Usage as a context manager guarantees the container is torn down::

        with PiContainer("pi-sandbox") as pi:
            answer = pi.prompt("...")
    """

    def __init__(
        self,
        image: str = DEFAULT_IMAGE,
        *,
        model: Optional[str] = None,
        workspace: Optional[str] = None,
        env_keys: tuple[str, ...] = ("AZURE_API_KEY",),
        name: Optional[str] = None,
        extra_args: Optional[list[str]] = None,
        log_dir: Optional[str] = DEFAULT_LOG_DIR,
    ) -> None:
        self.image = image
        self.model = model
        self.workspace = workspace
        self.env_keys = env_keys
        self.name = name or f"pi-{uuid.uuid4().hex[:12]}"
        self.extra_args = extra_args or []

        # Per-container log directory (keyed by name). None disables logging.
        self.log_dir: Optional[str] = (
            os.path.join(log_dir, self.name) if log_dir else None
        )
        self._stderr_path: Optional[str] = (
            os.path.join(self.log_dir, "stderr.log") if self.log_dir else None
        )
        self._stderr_fh = None  # opened in start()

        self._proc: Optional[subprocess.Popen] = None
        self._reader: Optional[threading.Thread] = None
        self._stderr_reader: Optional[threading.Thread] = None
        # Correlate responses by their `id`; each waiter gets its own single-slot queue.
        self._pending: dict[str, queue.Queue] = {}
        # A monotonically-served stream of settle events for prompt() to consume.
        self._settled: queue.Queue = queue.Queue()
        # Per-turn capture: when recording, every non-response event is appended here so a
        # turn can be reconstructed into structured steps (tool calls, thinking, text).
        self._recording = False
        self._turn_events: list[dict] = []
        self._lock = threading.Lock()
        self._closed = False

    # -- lifecycle ---------------------------------------------------------

    def _build_cmd(self) -> list[str]:
        cmd = ["docker", "run", "--rm", "-i", "--name", self.name]
        for key in self.env_keys:
            # Forward the host value explicitly (-e KEY=VALUE) so it is present even if the
            # daemon environment differs from this process.
            if key in os.environ:
                cmd += ["-e", f"{key}={os.environ[key]}"]
        if self.workspace:
            cmd += ["-v", f"{os.path.abspath(self.workspace)}:/workspace"]
        cmd.append(self.image)
        # Args after the image are passed to the `pi` ENTRYPOINT, overriding the image CMD.
        pi_args = ["--mode", "rpc", "--no-extensions", "--no-session"]
        if self.model:
            pi_args += ["--model", self.model]
        pi_args += self.extra_args
        # If no model override is given, fall back to the image's baked-in CMD by passing
        # nothing extra beyond the rpc flags we always want.
        return cmd + pi_args

    def start(self) -> "PiContainer":
        if self._proc is not None:
            raise PiError("container already started")
        self._proc = subprocess.Popen(
            self._build_cmd(),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,  # line-buffered
        )
        self._reader = threading.Thread(target=self._read_loop, daemon=True)
        self._reader.start()
        # Drain the container's stderr to a per-session log file. This both
        # preserves Pi's own error/warning output (otherwise discarded) and
        # prevents the stderr pipe buffer from filling and stalling the process.
        if self._stderr_path:
            try:
                os.makedirs(self.log_dir, exist_ok=True)
                self._stderr_fh = open(self._stderr_path, "a", encoding="utf-8", buffering=1)
            except OSError:
                self._stderr_fh = None  # logging must never break the container
        self._stderr_reader = threading.Thread(target=self._read_stderr_loop, daemon=True)
        self._stderr_reader.start()
        return self

    def _read_loop(self) -> None:
        assert self._proc is not None and self._proc.stdout is not None
        for line in self._proc.stdout:
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                # Non-JSON stdout (shouldn't happen in rpc mode) — ignore.
                continue
            self._dispatch(msg)
        # stdout closed: unblock any waiters so they don't hang forever.
        with self._lock:
            for q in self._pending.values():
                q.put(PiError("container stdout closed before response"))
        self._settled.put(PiError("container exited"))

    def _read_stderr_loop(self) -> None:
        """Drain the container's stderr line-by-line into the per-session log.

        Runs on its own daemon thread. Guards every write so a logging failure
        can never crash the thread or affect the turn in progress.
        """
        if self._proc is None or self._proc.stderr is None:
            return
        for line in self._proc.stderr:
            fh = self._stderr_fh
            if fh is None:
                continue
            try:
                fh.write(line if line.endswith("\n") else line + "\n")
            except (OSError, ValueError):
                # ValueError if the handle was closed mid-write during teardown.
                pass

    def _dispatch(self, msg: dict) -> None:
        mtype = msg.get("type")
        if mtype == "response":
            rid = msg.get("id")
            if rid is not None:
                with self._lock:
                    q = self._pending.pop(rid, None)
                if q is not None:
                    q.put(msg)
            return
        # Buffer everything else while a turn is being recorded (for structured steps).
        # Stamp arrival time (events carry no clock) so we can derive per-step latency.
        if self._recording:
            msg = {**msg, "_ts": time.monotonic()}
            self._turn_events.append(msg)
        if mtype == SETTLED_EVENT:
            self._settled.put(msg)

    # -- low-level RPC -----------------------------------------------------

    def send(self, command: dict) -> None:
        """Write one JSON command to the container's stdin (LF-framed)."""
        if self._proc is None or self._proc.stdin is None:
            raise PiError("container not started")
        self._proc.stdin.write(json.dumps(command) + "\n")
        self._proc.stdin.flush()

    def request(self, command: dict, timeout: float = DEFAULT_REQUEST_TIMEOUT) -> dict:
        """Send a command with a correlation id and block for its matching response."""
        rid = command.get("id") or f"req-{uuid.uuid4().hex[:8]}"
        command = {**command, "id": rid}
        slot: queue.Queue = queue.Queue(maxsize=1)
        with self._lock:
            self._pending[rid] = slot
        self.send(command)
        try:
            result = slot.get(timeout=timeout)
        except queue.Empty:
            with self._lock:
                self._pending.pop(rid, None)
            raise PiError(f"timeout waiting for response to {command.get('type')!r}")
        if isinstance(result, Exception):
            raise result
        if not result.get("success", False):
            raise PiError(f"command {command.get('type')!r} failed: {result}")
        return result

    # -- high-level helpers ------------------------------------------------

    def _drain_settled(self) -> None:
        """Discard any stale settle events left from a previous turn."""
        while not self._settled.empty():
            try:
                self._settled.get_nowait()
            except queue.Empty:
                break

    def _abort_quietly(self) -> None:
        """Best-effort abort of an in-flight turn so the session returns to idle.

        Called between retry attempts: after a settle-timeout the previous prompt
        may still be running in the container, so we must interrupt it before
        resending — otherwise the resend races a live turn. We clear the queue
        first (per rpc.md, `abort` alone continues queued messages) so no stale
        message survives into the retry. Swallows errors so a failed abort never
        masks the original timeout.
        """
        try:
            self.request({"type": "clear_queue"})
        except Exception:
            pass
        try:
            self.request({"type": "abort"})
        except Exception:
            pass
        self._drain_settled()

    def prompt(self, text: str, timeout: float = DEFAULT_PROMPT_TIMEOUT,
               retries: int = DEFAULT_PROMPT_RETRIES) -> str:
        """Send a user prompt, wait for the run to settle, return the assistant text.

        On a settle-timeout the in-flight turn is aborted and the prompt resent,
        up to ``retries`` extra times, before raising PiError.
        """
        last_exc: Optional[Exception] = None
        for attempt in range(retries + 1):
            self._drain_settled()
            self.request({"type": "prompt", "message": text})
            try:
                settled = self._settled.get(timeout=timeout)
            except queue.Empty:
                last_exc = PiError(
                    f"prompt did not settle within {timeout}s "
                    f"(attempt {attempt + 1}/{retries + 1})"
                )
                self._abort_quietly()
                continue
            if isinstance(settled, Exception):
                raise settled
            resp = self.request({"type": "get_last_assistant_text"})
            return resp.get("data", {}).get("text") or ""
        raise last_exc  # type: ignore[misc]

    def prompt_detailed(self, text: str, timeout: float = DEFAULT_PROMPT_TIMEOUT,
                        retries: int = DEFAULT_PROMPT_RETRIES) -> dict:
        """Send a prompt and return structured per-turn data.

        Returns a dict::

            {
              "answer": "<final assistant text>",
              "steps": [ {step}, ... ],   # tool calls + thinking/text, in order
              "usage": {"input":.., "output":.., "total":.., "cost":..},  # this turn
              "skill_calls": [ {skill_id, skill_name}, ... ],  # detected on the utterance
              "latency_in_ms": <whole-turn wall clock>,
            }

        Each step is shaped toward agent-inspect's ``Step`` (building blocks only — the runner
        assembles the TurnTrace)::

            {"id", "parent_ids", "tool", "tool_input_args": [{"name","value"}], "tool_output",
             "is_error", "status", "error", "agent_thought", "text", "skill_calls",
             "latency_in_ms"}

        Reconstructed from the ``tool_execution_start/end`` events (tool calls) and the
        ``turn_end`` assistant message content blocks (thinking/text/toolCall), which are
        captured on the reader thread between the prompt and ``agent_settled``.

        On a settle-timeout the in-flight turn is aborted and the prompt resent,
        up to ``retries`` extra times, before raising PiError.
        """
        last_exc: Optional[Exception] = None
        for attempt in range(retries + 1):
            with self._lock:
                self._turn_events = []
                self._recording = True
            self._drain_settled()
            t0 = time.monotonic()
            timed_out = False
            try:
                self.request({"type": "prompt", "message": text})
                try:
                    settled = self._settled.get(timeout=timeout)
                except queue.Empty:
                    timed_out = True
                    last_exc = PiError(
                        f"prompt did not settle within {timeout}s "
                        f"(attempt {attempt + 1}/{retries + 1})"
                    )
                else:
                    if isinstance(settled, Exception):
                        raise settled
                    with self._lock:
                        events = list(self._turn_events)
            finally:
                with self._lock:
                    self._recording = False
                    self._turn_events = []
            if timed_out:
                self._abort_quietly()
                continue
            latency_ms = (time.monotonic() - t0) * 1000.0
            answer = self.request({"type": "get_last_assistant_text"}).get("data", {}).get("text") or ""
            return {"answer": answer, "latency_in_ms": latency_ms, **_build_turn(events, text)}
        raise last_exc  # type: ignore[misc]

    def stats(self) -> dict:
        """Return token usage / cost / tool-call counts for the session."""
        return self.request({"type": "get_session_stats"}).get("data", {})

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self._proc is not None:
            try:
                if self._proc.stdin:
                    self._proc.stdin.close()
            except Exception:
                pass
            try:
                self._proc.terminate()
                self._proc.wait(timeout=10)
            except Exception:
                self._proc.kill()
        # Belt-and-suspenders: ensure the named container is gone even if --rm lagged.
        subprocess.run(
            ["docker", "rm", "-f", self.name],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        # Close the stderr log handle after the process is gone (the reader
        # thread has hit EOF on the closed pipe by now).
        if self._stderr_fh is not None:
            try:
                self._stderr_fh.close()
            except Exception:
                pass
            self._stderr_fh = None

    def __enter__(self) -> "PiContainer":
        return self.start()

    def __exit__(self, *exc) -> None:
        self.close()


Task = Callable[[PiContainer], Any]


def spawn_n(
    n: int,
    image: str = DEFAULT_IMAGE,
    *,
    task: Optional[Task] = None,
    prompt: Optional[str] = None,
    max_workers: Optional[int] = None,
    **container_kwargs: Any,
) -> list[Any]:
    """Spawn ``n`` Pi containers concurrently and run a task in each.

    Provide either ``task`` (a callable given the started ``PiContainer``) or ``prompt``
    (a string sent to every container). Results are returned in worker order (0..n-1).
    Each worker owns exactly one container and tears it down in a ``finally``.
    """
    if (task is None) == (prompt is None):
        raise ValueError("provide exactly one of `task` or `prompt`")
    if task is None:
        def task(pi: PiContainer) -> dict:  # type: ignore[misc]
            return {"answer": pi.prompt(prompt), "stats": pi.stats()}

    def worker(index: int) -> Any:
        with PiContainer(image, name=f"pi-{index}-{uuid.uuid4().hex[:8]}", **container_kwargs) as pi:
            return task(pi)

    with ThreadPoolExecutor(max_workers=max_workers or n) as pool:
        return list(pool.map(worker, range(n)))


class PiInstance:
    """A long-lived, managed Pi instance your agent runner holds onto.

    Lifecycle: construct -> ``open()`` (starts the container) -> ``ask(utterance)`` any number
    of times (each continues the same in-memory conversation) -> ``close()`` (stops it).
    Also usable as a context manager.

    ``ask`` is serialized with a lock so it is safe to call from multiple threads, though a
    single instance processes one turn at a time (Pi is single-session). For concurrency,
    use one ``PiInstance`` per conversation (see ``PiPool``).
    """

    def __init__(self, image: str = DEFAULT_IMAGE, **container_kwargs: Any) -> None:
        self._pi = PiContainer(image, **container_kwargs)
        self._turn_lock = threading.Lock()
        self._opened = False

    @property
    def name(self) -> str:
        return self._pi.name

    def open(self) -> "PiInstance":
        if not self._opened:
            self._pi.start()
            self._opened = True
        return self

    def ask(self, utterance: str, timeout: float = DEFAULT_PROMPT_TIMEOUT) -> str:
        """Send one user utterance, block until the turn settles, return the reply text."""
        if not self._opened:
            raise PiError("instance not open(); call open() first")
        with self._turn_lock:
            return self._pi.prompt(utterance, timeout=timeout)

    def ask_detailed(self, utterance: str, timeout: float = DEFAULT_PROMPT_TIMEOUT) -> dict:
        """Like ask(), but return {answer, steps, usage} with structured per-turn steps."""
        if not self._opened:
            raise PiError("instance not open(); call open() first")
        with self._turn_lock:
            return self._pi.prompt_detailed(utterance, timeout=timeout)

    def stats(self) -> dict:
        return self._pi.stats()

    def abort(self) -> None:
        """Interrupt the in-flight turn (if any) and wait for the session to go idle."""
        self._pi.request({"type": "abort"})

    def close(self) -> None:
        self._pi.close()
        self._opened = False

    def __enter__(self) -> "PiInstance":
        return self.open()

    def __exit__(self, *exc) -> None:
        self.close()


class PiPool:
    """A pool of N long-lived ``PiInstance``s your runner can ping by index.

    Open once, dispatch utterances to any instance across many turns, close all at the end::

        with PiPool(4, image="pi-sandbox") as pool:
            print(pool.ask(0, "hello"))
            print(pool.ask(1, "different conversation"))
            print(pool.ask(0, "continue the first one"))   # same session as instance 0
    """

    def __init__(self, n: int, image: str = DEFAULT_IMAGE, **container_kwargs: Any) -> None:
        self.instances = [
            PiInstance(image, name=f"pi-{i}-{uuid.uuid4().hex[:8]}", **container_kwargs)
            for i in range(n)
        ]

    def open(self) -> "PiPool":
        # Start all containers concurrently (container boot is the slow part).
        with ThreadPoolExecutor(max_workers=len(self.instances) or 1) as pool:
            list(pool.map(lambda inst: inst.open(), self.instances))
        return self

    def ask(self, index: int, utterance: str, timeout: float = DEFAULT_PROMPT_TIMEOUT) -> str:
        return self.instances[index].ask(utterance, timeout=timeout)

    def close(self) -> None:
        with ThreadPoolExecutor(max_workers=len(self.instances) or 1) as pool:
            list(pool.map(lambda inst: inst.close(), self.instances))

    def __len__(self) -> int:
        return len(self.instances)

    def __getitem__(self, i: int) -> PiInstance:
        return self.instances[i]

    def __enter__(self) -> "PiPool":
        return self.open()

    def __exit__(self, *exc) -> None:
        self.close()


def _main() -> None:
    parser = argparse.ArgumentParser(description="Spawn N Pi containers and drive them over RPC.")
    parser.add_argument("--n", type=int, default=1, help="number of containers to spawn")
    parser.add_argument("--image", default=DEFAULT_IMAGE, help="Docker image tag")
    parser.add_argument("--prompt", help="one-shot: prompt sent to every container, then exit")
    parser.add_argument("--serve", action="store_true",
                        help="long-lived: open a PiInstance and read utterances from stdin "
                             "(one per line) until EOF, then close")
    parser.add_argument("--model", default=None, help="override model (default: image CMD)")
    parser.add_argument("--max-workers", type=int, default=None, help="concurrency cap")
    parser.add_argument("--timeout", type=float, default=DEFAULT_PROMPT_TIMEOUT,
                        help="per-prompt settle timeout (s)")
    args = parser.parse_args()

    if "AZURE_API_KEY" not in os.environ:
        parser.error("AZURE_API_KEY is not set in the environment")
    if args.serve == bool(args.prompt):
        parser.error("provide exactly one of --prompt (one-shot) or --serve (long-lived)")

    if args.serve:
        # Long-lived instance: your runner pings it with utterances, one per stdin line.
        import sys
        with PiInstance(args.image, model=args.model) as inst:
            print(f"[pi instance {inst.name} ready — type an utterance, Ctrl-D to close]",
                  flush=True)
            for line in sys.stdin:
                utterance = line.strip()
                if not utterance:
                    continue
                answer = inst.ask(utterance, timeout=args.timeout)
                print(answer.strip(), flush=True)
            stats = inst.stats()
            print(f"[closing — tokens={stats.get('tokens', {}).get('total')} "
                  f"cost=${stats.get('cost')}]", flush=True)
        return

    def task(pi: PiContainer) -> dict:
        return {"answer": pi.prompt(args.prompt, timeout=args.timeout), "stats": pi.stats()}

    results = spawn_n(
        args.n,
        image=args.image,
        task=task,
        max_workers=args.max_workers,
        model=args.model,
    )
    for i, r in enumerate(results):
        stats = r.get("stats", {})
        tokens = stats.get("tokens", {})
        print(f"\n=== container {i} ===")
        print(r.get("answer", "").strip())
        print(f"[tokens: total={tokens.get('total')} "
              f"in={tokens.get('input')} out={tokens.get('output')} "
              f"cost=${stats.get('cost')}]")


if __name__ == "__main__":
    _main()
