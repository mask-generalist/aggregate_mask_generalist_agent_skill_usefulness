"""Stdlib HTTP client for the Pi gateway (docker-pi/pi_server.py) + trace assembly.

CUGA-free by design: uses only urllib from the standard library (no aiohttp /
requests / httpx), so the eval pipeline runs in the base environment. The client
speaks the gateway's session protocol:

    POST   /sessions              {workspace?}       -> {session_id}
    POST   /sessions/{sid}/ask    {utterance, timeout} -> {answer, steps, usage, skill_calls, latency_in_ms}
    DELETE /sessions/{sid}                            -> {closed}
    GET    /healthz                                   -> {ok, sessions}

The trace helpers turn per-turn /ask responses into the exact JSON schema that
trace.load_trace reads, so we write trace_<N>.json directly with no CUGA DB.
"""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("experiment_clean.pi_client")


class PiGatewayError(Exception):
    """Raised when a request to the Pi gateway fails."""


# ── HTTP ─────────────────────────────────────────────────────────────────────

def _request(
    base_url: str,
    path: str,
    method: str = "GET",
    payload: Optional[dict] = None,
    timeout: float = 60.0,
) -> dict:
    """Issue a JSON request and parse the JSON response.

    Wraps urllib errors into PiGatewayError; includes the HTTP error body in the
    message so gateway 502s (agent errors) surface the underlying detail.
    """
    url = base_url.rstrip("/") + path
    data = None
    headers = {"Accept": "application/json"}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"

    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            detail = exc.read().decode("utf-8")
        except Exception:
            pass
        raise PiGatewayError(f"{method} {url} -> HTTP {exc.code}: {detail or exc.reason}") from exc
    except urllib.error.URLError as exc:
        raise PiGatewayError(f"{method} {url} -> {exc.reason}") from exc

    if not body:
        return {}
    try:
        return json.loads(body)
    except json.JSONDecodeError as exc:
        raise PiGatewayError(f"{method} {url} -> invalid JSON response: {body[:200]}") from exc


def healthz(base_url: str, timeout: float = 10.0) -> dict:
    """Ping the gateway; raises PiGatewayError if unreachable."""
    return _request(base_url, "/healthz", "GET", timeout=timeout)


def create_session(base_url: str, workspace: Optional[str] = None, timeout: float = 60.0) -> str:
    """Create a Pi session (container). Returns the session id."""
    payload: dict = {}
    if workspace:
        payload["workspace"] = workspace
    data = _request(base_url, "/sessions", "POST", payload=payload, timeout=timeout)
    sid = data.get("session_id")
    if not sid:
        raise PiGatewayError(f"create_session: no session_id in response: {data}")
    logger.info("[pi] session created: %s (workspace=%s)", sid, workspace or "none")
    return sid


def ask(base_url: str, sid: str, utterance: str, timeout: float = 600.0) -> dict:
    """Send one user utterance to a session; returns the raw /ask response dict.

    The HTTP read timeout is set above the agent-turn timeout so the client does
    not give up before the server's own deadline.
    """
    payload = {"utterance": utterance, "timeout": timeout}
    return _request(
        base_url, f"/sessions/{sid}/ask", "POST", payload=payload, timeout=timeout + 30.0
    )


def is_null_turn(ask_response: dict) -> bool:
    """True if a turn settled with no content at all: no answer, no steps, no tokens.

    This is the signature of a transient model-round stall (observed at ~22-56s
    latency): the turn settles cleanly (status 200) but the assistant emitted
    nothing. Distinct from a legitimate short reply, which carries tokens/steps.
    Such a turn fails the whole trial at eval time (agent-inspect 050008
    "Turn :N is missing agent response"), so callers retry it.
    """
    if (ask_response.get("answer") or "").strip():
        return False
    if ask_response.get("steps"):
        return False
    usage = ask_response.get("usage") or {}
    return not usage.get("total")


def delete_session(base_url: str, sid: str, timeout: float = 60.0) -> None:
    """Delete (tear down) a session. Missing sessions (404) are ignored."""
    try:
        _request(base_url, f"/sessions/{sid}", "DELETE", timeout=timeout)
    except PiGatewayError as exc:
        if "HTTP 404" in str(exc):
            return
        logger.warning("[pi] failed to delete session %s: %s", sid, exc)


# ── Trace assembly ─────────────────────────────────────────────────────────────
#
# Kept here (not in trace.py) so this module stays CUGA-free — trace.py pulls in
# the CUGA-side converter modules. The output schema matches trace.load_trace
# exactly: each turn is {id, from_id, agent_input, agent_response, steps,
# latency_in_ms, *_token_consumption}.

def next_trace_path(trial_folder: Path) -> Path:
    """Return a versioned trace_<N>_<ts>.json path (matches trace.next_trace_path)."""
    n = len(list(trial_folder.glob("trace_*.json"))) + 1
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    return trial_folder / f"trace_{n}_{ts}.json"


def _normalize_skill_ids(steps: List[dict]) -> List[dict]:
    """Strip the gateway's ``skill:`` prefix from each step's skill_call ids.

    The Pi gateway (docker-pi/spawn_pi.py) emits skill_calls as
    ``{"skill_id": "skill:<name>", "skill_name": "<name>"}``, but the test-case
    YAMLs (and thus the ground-truth SkillCall.skill_id used by
    SkillPrecision/SkillRecall) use the bare ``<name>``. The library matches
    skill_id by case-sensitive exact string equality, so the ``skill:`` prefix
    would make every expected-skill case score 0. Normalize to the bare name so
    invoked and expected skill_ids match.
    """
    for step in steps:
        for sc in (step.get("skill_calls") or []):
            sid = sc.get("skill_id")
            if isinstance(sid, str) and sid.startswith("skill:"):
                sc["skill_id"] = sid[len("skill:"):]
    return steps


def turn_to_trace_dict(
    index: int,
    utterance: str,
    ask_response: dict,
    prev_id: Optional[str],
) -> dict:
    """Convert one /ask response into a load_trace turn dict.

    - steps pass through with one normalization: skill_call ids are stripped of
      the gateway's ``skill:`` prefix (see _normalize_skill_ids) so they match
      the bare-name ground truth. Other Pi step field names (id, parent_ids,
      tool, tool_input_args:[{name,value}], tool_output, agent_thought,
      skill_calls:[{skill_id,skill_name}]) match what load_trace reads; extra
      keys (is_error/status/error/text/…) are ignored on load.
    - "" is a valid answer; load_trace only treats None as missing.
    """
    usage = ask_response.get("usage") or {}
    return {
        "id": str(index),
        "from_id": prev_id,
        "agent_input": utterance,
        "agent_response": {
            "response": ask_response.get("answer", ""),
            "status_code": 200,
        },
        "steps": _normalize_skill_ids(ask_response.get("steps") or []),
        "latency_in_ms": ask_response.get("latency_in_ms"),
        "input_token_consumption": usage.get("input", 0),
        "output_token_consumption": usage.get("output", 0),
        "reasoning_token_consumption": 0,
        "total_token_consumption": usage.get("total", 0),
    }


def write_trace(trial_folder: Path, turns: List[Dict[str, Any]]) -> Path:
    """Write accumulated turn dicts to a versioned trace file. Returns its path."""
    out = next_trace_path(trial_folder)
    out.write_text(json.dumps({"turns": turns}, indent=2, default=str))
    logger.info("[pi] wrote trace (%d turn(s)) -> %s", len(turns), out)
    return out
