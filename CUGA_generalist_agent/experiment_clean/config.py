"""Centralised constants and typed configuration."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import yaml

# ── Paths ────────────────────────────────────────────────────────────────────

_REPO_ROOT = Path(__file__).resolve().parent.parent
SKILLS_FOLDER = str(_REPO_ROOT / ".cuga")
DEFAULT_ENV_TEMPLATE = str(_REPO_ROOT / ".cuga" / "env")
DEFAULT_DB_PATH = str(_REPO_ROOT / "src" / "cuga" / "dbs" / "cuga.db")
DEFAULT_OUTPUT_ROOT = str(Path(__file__).resolve().parent / "experiment_results")
DEFAULT_RUNNER_CONFIG = str(Path(__file__).resolve().parent / "runner_config.yaml")


# ── Dataclasses ──────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class UserProxyConfig:
    model: str = "azure/gpt-4.1"
    max_tokens: int = 4096
    use_expert_agent: bool = True


@dataclass(frozen=True)
class JudgeConfig:
    model: str = "azure/gpt-4.1"
    max_tokens: int = 4096
    num_judge_trials: int = 5


# ── Config loading ───────────────────────────────────────────────────────────

def load_runner_config(path: Optional[str] = None) -> dict:
    """Read runner_config.yaml. Returns empty dict if file is missing."""
    p = path or DEFAULT_RUNNER_CONFIG
    if not os.path.exists(p):
        return {}
    with open(p) as f:
        return yaml.safe_load(f) or {}


def user_proxy_config_from(raw: dict) -> UserProxyConfig:
    cfg = raw.get("user_proxy") or {}
    return UserProxyConfig(
        model=cfg.get("model", UserProxyConfig.model),
        max_tokens=cfg.get("max_tokens", UserProxyConfig.max_tokens),
        use_expert_agent=cfg.get("use_expert_agent", UserProxyConfig.use_expert_agent),
    )


def judge_config_from(raw: dict) -> JudgeConfig:
    cfg = raw.get("judge") or {}
    return JudgeConfig(
        model=cfg.get("model", JudgeConfig.model),
        max_tokens=cfg.get("max_tokens", JudgeConfig.max_tokens),
        num_judge_trials=cfg.get("num_judge_trials", JudgeConfig.num_judge_trials),
    )


def skills_from(raw: dict) -> Optional[list[str]]:
    """Read the skills whitelist from runner_config. Returns None if not set.

    Config format is a dict of ``name: true/false``::

        skills:
          tau2Airline: true
          OfficeBench: true
          state-travel: false   # disabled

    Returns the list of names whose value is truthy, or None when the
    ``skills`` key is absent (meaning "use all skills on disk").
    """
    toggles = raw.get("skills")
    if not toggles:
        return None
    return sorted(name for name, enabled in toggles.items() if enabled)


TRACE_CONVERTERS = ("stream", "legacy")


def trace_converter_from(raw: dict) -> str:
    """Read the trace-converter selector from runner_config.

    Config format (required — no default)::

        trace_converter: stream   # or: legacy

    - ``stream``: build the trace from the untruncated ``stream_events`` table via
      trace_converter_stream.convert_trace_from_stream.
    - ``legacy``: build from ``conversation_history`` via
      trace_converter.convert_trace_from_db (subject to sliding-window/summary
      truncation).

    Raises:
        ValueError: if the key is absent or the value is not one of
            ``TRACE_CONVERTERS`` — the caller must choose explicitly.
    """
    value = raw.get("trace_converter")
    if value is None:
        raise ValueError(
            "runner_config is missing required key 'trace_converter'. "
            f"Set it to one of {TRACE_CONVERTERS}."
        )
    value = str(value).strip().lower()
    if value not in TRACE_CONVERTERS:
        raise ValueError(
            f"Invalid trace_converter {value!r}; expected one of {TRACE_CONVERTERS}."
        )
    return value


def silence_litellm() -> None:
    """Suppress noisy litellm debug/info logging."""
    import litellm

    os.environ.setdefault("LITELLM_LOG", "ERROR")
    litellm.suppress_debug_info = True
    litellm.callbacks = []
    logging.getLogger("LiteLLM").setLevel(logging.ERROR)
    logging.getLogger("LiteLLM Router").setLevel(logging.ERROR)
