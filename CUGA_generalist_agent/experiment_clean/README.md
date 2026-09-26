# experiment_clean

Evaluation pipeline for CUGA. Runs automated conversations, then evaluates them with LLM-judged and deterministic metrics.

## Prerequisites

- Python 3.12 (must match CUGA's venv)
- Docker — for OpenSandbox containers (one per conversation)
- CUGA venv (with `opensandbox` extra) — use the `.venv` in `CUGA_generalist_agent/`
- `agent_quality_inspect` on PYTHONPATH (installed in the venv or at `../agent_quality_inspect/src`)
- Azure credentials in `.env`

### Docker setup

1. Pull the sandbox image and init config:
   ```bash
   docker pull opensandbox/code-interpreter:v1.0.2
   uvx opensandbox-server init-config ~/.sandbox.toml --example docker
   ```

2. Edit `~/.sandbox.toml`:
   ```toml
   [storage]
   allowed_host_paths = ["/abs/path/to/CUGA_generalist_agent/cuga_workspace"]
   ```

3. In the CUGA venv:
   ```bash
   uv sync --extra opensandbox
   ```

4. Start the sandbox server:
   ```bash
   OPENSANDBOX_INSECURE_SERVER=YES uvx opensandbox-server@0.2.3
   ```

### Install extra dependencies

From the CUGA repo root, with the venv active:

```bash
uv pip install mlflow-skinny==3.13.0 openai==2.29.0 backoff==2.2.1 litellm pyyaml httpx networkx numpy

# install agent_quality_inspect from the local repo folder
uv pip install -e ../agent_quality_inspect
```

### Environment variables

Set credentials for CUGA
```bash
export AZURE_ANTHROPIC_OPENAI_ENDPOINT=".../anthropic"
export AGENT_SETTING_CONFIG="settings.azure.toml"
export AZURE_OPENAI_API_KEY="..."
export AZURE_OPENAI_ENDPOINT="..."
export OPENAI_API_VERSION="..."
```

Set credentials for the user proxy and judge which are used in Agent Inspect:

```bash
export AZURE_API_BASE="..."
export AZURE_API_VERSION="..."
export AZURE_API_KEY="..."
```

For CUGA's own LLM, ensure the usual CUGA env vars are set in `.env`.

## Quick Start

```bash
cd CUGA_generalist_agent

# Activate the CUGA venv first (this is where `cuga` and its deps are installed).
source .venv/bin/activate

# Full pipeline: conversation + evaluation
PYTHONPATH="../agent_quality_inspect/src:." python -m experiment_clean.e2e path/to/test_cases/ \
    --n-trials 3 --max-workers 5 --config experiment_clean/runner_config.yaml
```
Results go to `experiment_clean/experiment_results/jobs/<timestamp>/`.

## Entry Points

| Command | What it does |
|---------|-------------|
| `python -m experiment_clean.e2e` | Full pipeline: conversations → evaluation |
| `python -m experiment_clean.conversation` | Conversations only (no eval) |
| `python -m experiment_clean.evaluate` | Evaluation only (on existing job folder) |
| `python -m experiment_clean.recompute_metric` | Recompute specific metrics on existing results |
| `python -m experiment_clean.aggregate_by_type` | Compare two systems across sample-type groups |

### CLI flags

**`e2e` and `conversation`:**

| Flag | Default | Description |
|------|---------|-------------|
| `path` | *(required)* | YAML file(s) or directory (searched recursively) |
| `--n-trials` | `1` | Trials per test case |
| `--max-workers` | `5` | Max concurrent conversations |
| `--max-turns` | from YAML | Override per-case `max_turns` |
| `--config` | — | Path to `runner_config.yaml` |
| `--output-dir` | `experiment_clean/experiment_results/` | Results root |
| `--resume` | — | Resume from a previous job folder |
| `-v` | off | Debug logging |

**`evaluate`:**

| Flag | Default | Description |
|------|---------|-------------|
| `path` | *(required)* | Job folder(s) to evaluate |
| `--n-trials` | `1` | Number of trials |
| `--max-workers` | `4` | Max concurrent trial evaluations |
| `--config` | — | Path to `runner_config.yaml` |
| `-v` | off | Debug logging |

### Conversation only

```bash
PYTHONPATH="../agent_quality_inspect/src:." python -m experiment_clean.conversation path/to/test_cases/ \
    --n-trials 5 --max-workers 5 --config experiment_clean/runner_config.yaml
```

### Evaluation only

```bash
PYTHONPATH="../agent_quality_inspect/src:." python -m experiment_clean.evaluate path/to/job_folder/ \
    --n-trials 5 --config experiment_clean/runner_config.yaml
```

Accepts multiple paths — metrics are aggregated across all of them:

```bash
PYTHONPATH="../agent_quality_inspect/src:." python -m experiment_clean.evaluate job1/ job2/ --n-trials 5
```

### Recompute specific metrics

Selectively recompute one or more metrics on existing eval results without re-running the full evaluation. Non-requested metrics are left untouched.

```bash
# Recompute skill_precision and skill_recall in-place (fast, no LLM calls)
PYTHONPATH="../agent_quality_inspect/src:." python -m experiment_clean.recompute_metric path/to/job_folder/ \
    --metrics skill_precision skill_recall --n-trials 5

# Write to a separate directory instead of overwriting
PYTHONPATH="../agent_quality_inspect/src:." python -m experiment_clean.recompute_metric path/to/job_folder/ \
    --metrics skill_precision skill_recall --n-trials 5 \
    --output-dir /tmp/patched

# Multiple jobs at once
PYTHONPATH="../agent_quality_inspect/src:." python -m experiment_clean.recompute_metric job1/ job2/ \
    --metrics skill_recall --n-trials 5

# Use a specific config (for skills whitelist / judge settings)
PYTHONPATH="../agent_quality_inspect/src:." python -m experiment_clean.recompute_metric path/to/job_folder/ \
    --metrics capability_score --n-trials 5 --config path/to/runner_config.yaml
```

**Available metrics:** `skill_precision`, `skill_recall`, `capability_score`, `progress_rates`, `total_tokens`, `total_latency_ms`, `tool_call_count`

**Things to know:**
- `skill_precision`, `skill_recall`, `total_tokens`, `total_latency_ms`, `tool_call_count` are computed from the trace — fast, no LLM calls.
- `progress_rates` and `capability_score` invoke the LLM judge (slow, costs money).
- When `progress_rates` is recomputed, derived aggregate metrics (`max_progress_rate`, `mean_progress_rate`, `pass@k`, `pass^k`) are also updated.
- The `--config` flag controls the skills whitelist (affects which expected skills are considered for precision/recall) and judge model/settings.
- Without `--output-dir`, files are updated in-place. Per-trial `eval_results.json`, job-level `trial_N_results.json`, and `aggregate_metrics_results.json` are all patched.
- The job folder can be a standard `jobs/<timestamp>/` directory or any folder containing `tc_*/trial_*/` structure.

### Resume failed trials

```bash
PYTHONPATH="../agent_quality_inspect/src:." python -m experiment_clean.e2e path/to/test_cases/ \
    --resume path/to/previous_job/ --n-trials 5 --max-workers 5
```

Re-runs only the failed `(sample_id, trial_id)` pairs, merges results into the existing job, then re-evaluates.

### Aggregate by type (2×2 comparison)

Compares two systems (old vs new) across T_old / T_new sample-type groups, producing a 2×2 metrics report.

```bash
python -m experiment_clean.aggregate_by_type \
    --system-old path/to/old_system_job/ \
    --system-new path/to/new_system_job/ \
    --sample-types experiment_clean/sample_types.yaml \
    --groups experiment_clean/groups.yaml
```

| Flag | Required | Default | Description |
|------|----------|---------|-------------|
| `--system-old` | Yes | — | Old system job dir or parent (recursive discovery) |
| `--system-new` | Yes | — | New system job dir or parent (recursive discovery) |
| `--sample-types` | No | `experiment_clean/sample_types.yaml` | Sample type definitions YAML |
| `--groups` | Yes | — | T_old / T_new group assignments YAML |

Each `--system-*` path can be a single job directory or a parent directory containing multiple jobs (discovered recursively). When both systems share a subset of samples, only the common samples are kept (with a warning about dropped ones).

**Output** (to `experiment_results/agg/system_old_<name>_vs_system_new_<name>_agg_<timestamp>/`):

- 4 aggregate JSONs — `aggregate_metrics_results_{system_old,system_new}_{T_old,T_new}.json`
- 4 filtered trial dirs — `{system_old,system_new}_{T_old,T_new}/trial_N_results.json`
- `sample_classification.json` — shared classification (asserted identical across systems)
- `print_results.log` — command args, source aggregate paths, and 2×2 tables for all 10 metrics

**Config files:**

`sample_types.yaml` — each type is identified by its set of expected skills, matching the `expected_skill_invocations` in test case YAMLs. Order doesn't matter — skills are matched as a set (e.g. `{OfficeBench, skill0_artifacts}` == `{skill0_artifacts, OfficeBench}`). Add new types here as new skill combinations appear.

```yaml
sample_types:
  general:                        # only skill0_artifacts
    expected_skills:
      - skill0_artifacts
  single_domain_office:           # only OfficeBench
    expected_skills:
      - OfficeBench
  cross_domain_office_general:    # both skills
    expected_skills:
      - OfficeBench
      - skill0_artifacts
```

`groups.yaml` — assigns sample types to T_old / T_new groups. Each entry references a type name from `sample_types.yaml`.

```yaml
T_old:                            # baseline task types
  - general
T_new:                            # new task types to compare
  - single_domain_office
```

## Configuration

`runner_config.yaml` controls three things:

```yaml
judge:
  model: azure/gpt-5.4
  max_tokens: 4096
  num_judge_trials: 5      # how many times the LLM judge scores each subgoal

user_proxy:
  model: azure/gpt-4.1
  max_tokens: 4096
  use_expert_agent: true    # UserProxy generates contextual responses (not just "Approved")

skills:
  tau2Airline: true
  OfficeBench: true
  state-travel: false     # set to false to disable
```

**Skills whitelist** controls:
- Which skills CUGA sees during conversation (others disabled via `SKILL.md` → `SKILL.md.off` rename — non-destructive, reversible)
- Which expected skills count for precision/recall during evaluation (others filtered out)

Set a skill to `false` to disable it. Remove the `skills:` section entirely to use all skills in `.cuga/skills/`.

## Test Cases

Test cases are YAML files with this structure:

```yaml
id: tc_example
test_steps:
  - type: dynamic_conversation
    user_agent:
      task_summary: "You are [persona]. You want to [task]."
    max_turns: 35
    skill_validations:
      expected_skill_invocations:
        - skill: tau2Airline
    agent_response_validations:
      - check: "The agent does X."
    capability_validations:
      expected_capabilities:
        - name: tool_name
          description: "What the tool does."
          output:
            check: '{"expected": "output"}'
```

Point to a single file or a directory (recursively finds all `.yaml` files):

```bash
.venv/bin/python -m experiment_clean.e2e path/to/test_case.yaml --n-trials 3
.venv/bin/python -m experiment_clean.e2e path/to/test_cases_dir/ --n-trials 3
```

## Output Structure

```
experiment_results/jobs/<timestamp>/
├── runner.log                     # full run log
├── runs_summary.json              # conversation outcomes (success/fail per trial)
├── skills_used.json               # which skills were active
├── runner_config.yaml             # copy of config used
├── <case_id>/
│   └── trial_<N>/
│       ├── conversation.json      # full conversation history
│       ├── thread_id.txt          # sandbox thread ID
│       ├── <case>.yaml            # copy of test case
│       ├── *_cuga_db.db           # filtered DB backup
│       ├── trace_*.json           # converted trace (DB + conversation overlay)
│       └── eval_results_*/
│           └── eval_results.json  # per-trial metrics
└── eval_results_<ts>/
    ├── trial_<N>_results.json     # per-trial eval summaries
    └── aggregate_metrics_results.json  # aggregated metrics across all trials
```

## Metrics

| Metric | Source | Notes |
|--------|--------|-------|
| Progress rate | LLM judge | Per-subgoal completion scored by judge, averaged |
| Skill precision | `agent-inspect` | `\|invoked ∩ expected\| / \|invoked\|` — None when 0 invocations |
| Skill recall | `agent-inspect` | `\|invoked ∩ expected\| / \|expected\|` — 0.0 when 0 invocations |
| Capability score | LLM judge | Fraction of expected capabilities completed |
| Pass@k / Pass^k | `agent-inspect` | Includes failed trials as score=0 (not excluded) |
| Tokens, latency, tool calls | Trace | Deterministic, from DB/stream events |

## File Overview

| File | Role |
|------|------|
| `config.py` | Constants, dataclasses, YAML loading, shared helpers |
| `testcase.py` | Parse YAML test cases into typed `TestCaseCriteria` |
| `trace.py` | Trace conversion (wraps `trace_converter.py`) + deserialization |
| `conversation.py` | Drive CUGA conversations, save artifacts |
| `evaluate.py` | Run metrics on saved artifacts (no CUGA imports) |
| `recompute_metric.py` | Selectively recompute specific metrics on existing results |
| `aggregate_by_type.py` | 2×2 system comparison across sample-type groups |
| `e2e.py` | Glue: conversation → eval |
| `runner_config.yaml` | Judge, user proxy, and skills config |
| `sample_types.yaml` | Sample type definitions (skill sets per type) |
| `groups.yaml` | T_old / T_new group assignments |
