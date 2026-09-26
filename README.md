# Aggregate Scores Mask Generalist Agent's Skill Usefulness

## Built on top of the following open-source libraries

We use and built on top of the following open-source libraries:

1. **Cuga-agent**
   - code: https://github.com/cuga-project/cuga-agent
   - paper: https://ojs.aaai.org/index.php/AAAI/article/view/41485
2. **Pi-agent**
   - code: https://github.com/earendil-works/pi
3. **Tau2bench agent**
   - code: https://github.com/sierra-research/tau2-bench
   - paper: https://arxiv.org/pdf/2506.07982
4. **ToolSandbox agent**
   - code: https://github.com/apple-aiml-research/ToolSandbox
   - paper: https://aclanthology.org/2025.findings-naacl.65.pdf
5. **OfficeBench**
   - code: https://github.com/zlwang-cs/OfficeBench
   - paper: https://arxiv.org/pdf/2407.19056
6. **STATEBench**
   - code: https://github.com/microsoft/STATE-Bench
7. **TED evaluation framework**
   - code: https://github.com/SAP/agent-quality-inspect
   - paper: https://arxiv.org/pdf/2603.15483
   - The `agent_quality_inspect/` folder in this repo is our **extension** of TED's `agent-quality-inspect` package: we build on its methodology and add new metrics that the upstream package does not include.

---

## How the pieces fit together

```
                test cases                     runs the agent,              scores traces
                (testcases)                    drives conversation          with LLM-judge +
                                                                            deterministic metrics
                     │                                │                            │
                     ▼                                ▼                            ▼
   ┌───────────────────────┐      ┌─────────────────────────────┐    ┌──────────────────────────┐
   │  testcases/           │ ───▶ │  CUGA_generalist_agent/     │ ─▶ │  agent_quality_inspect/  │
   │                       │      │  pi_agent/                  │    │  (shared metrics library)│
   └───────────────────────┘      └─────────────────────────────┘    └──────────────────────────┘
                                                                                   │
                                                                                   ▼
                                                        raw outputs ──▶ CUGA_raw_logs/, pi_raw_logs/
                                                        paper tables ──▶ aggregate_results_log/
```

- **Test cases** (`testcases/`) are YAML files defining a persona, a task,
  expected skill invocations, and expected capability (tool) calls; they are
  synthesized by the pipeline in `testcase-generation/`.
- Each **agent** (`CUGA_generalist_agent/`, `pi_agent/`) has an `experiment_clean/`
  pipeline that drives automated multi-turn conversations against the agent and
  writes conversation traces.
- **`agent_quality_inspect/`** — our extension of TED's `agent-quality-inspect`
  package — provides the metrics, scorers, and validators both pipelines use to
  score those traces, including new metrics not in the upstream package.
- **Raw run outputs** land in `CUGA_raw_logs/` and `pi_raw_logs/`; the curated
  results backing the paper's tables live in `aggregate_results_log/`.

---

## Top-level folders

### Agents

| Folder | What it is |
|--------|------------|
| **`CUGA_generalist_agent/`** | The full CUGA (Configurable Generalist Agent) codebase from IBM Research, plus its `experiment_clean/` evaluation pipeline. Agent source is in `src/cuga/`; runtime skills and the sandbox world live in `.cuga/` (`.cuga/skills/`, `.cuga/env/world.db`). Run the agent via the `cuga` CLI; run evaluations via `python -m experiment_clean.e2e …`. |
| **`pi_agent/`** | A monorepo fork of the Pi coding agent (github.com/earendil-works/pi) wired to run headless against Azure Anthropic (Claude Opus 4.6). TypeScript source is in `packages/`; the Dockerized sandbox + HTTP gateway is in `docker-pi/`; the evaluation pipeline is in `experiment_clean/`. See `pi_agent/README.md` for the two-terminal run flow. |

Both agents share the same `experiment_clean/` design: `e2e.py` (full pipeline),
`conversation.py` (drive conversations only), `evaluate.py` (score an existing job),
`recompute_metric.py` (recompute one metric without a full rerun), and
`aggregate_by_type.py` (the 2×2 old-vs-new-system comparison). Config lives in
`runner_config.yaml` (LLM judge, user-proxy model, and a skills whitelist). Results
are written to `experiment_clean/experiment_results/jobs/<timestamp>/`.

### Metrics library

| Folder | What it is |
|--------|------------|
| **`agent_quality_inspect/`** | Our extension of an open-source agent-evaluation package. |

### Test cases

| Folder | What it is |
|--------|------------|
| **`testcases/`** | The YAML test-case inputs fed to the pipelines, in `cuga_*` and `pi_*` variants across three settings (settings1 ≈ 91 cases, settings2 ≈ 30, settings3 ≈ 199). Each `tc_<hash>.yaml` defines a persona, a `dynamic_conversation` task, `skill_validations`, `agent_response_validations`, and `capability_validations`. |
| **`testcase-generation/`** | The synthesis pipeline that produces the test cases. It runs in three steps — **graph** (build a capability graph from skill definitions, add cross-skill edges via LLM), **sample** (random-walk the graph into 2–5 step capability chains), and **generate** (ground each chain in real `world.db`/workspace state via Claude Code, produce a structured case with GPT-5.4, then verify consistency). Entry point is `run_pipeline.py`; see [`testcase-generation/README.md`](testcase-generation/README.md). |

### Result artifacts

| Folder | What it is |
|--------|------------|
| **`CUGA_raw_logs/`** | Raw evaluation outputs from CUGA runs, named `CUGA_<model>_<n>_[sol_]setting<X>_<old\|new>_system` (e.g. `CUGA_opus4_6_setting1_new_system`). Each holds per-testcase `tc_<hash>/` trial folders, `runs_summary.json`, `skills_used.json`, and `eval_results_*` metric dumps. |
| **`cuga_raw_logs_improvement/`** | CUGA runs from context-improvement experiments (e.g. `CUGA_opus4_6_setting1_new_system_pruned`, `..._random_mask`), same per-testcase layout as `CUGA_raw_logs/`. |
| **`pi_raw_logs/`** | The same as `CUGA_raw_logs/`, for Pi runs, named `pi_opus4_6_setting<X>_<old\|new>_system`. Each contains a timestamped job folder mirroring the pipeline's `jobs/<timestamp>/` output (conversation traces, converted traces, per-trial eval results). |
| **`aggregate_results_log/`** | Curated experiment results backing the paper's tables, under `paper_experiments/`, organized by model (`cuga_gpt5.6-sol`, `cuga_opus_4_6`, `pi_opus_4_6`) and settings, with `table_1_*` / `table_2_*` / `table_3_*` (single-domain, cross-domain, combined) subfolders. |

### Reproducibility scripts

| Folder | What it is |
|--------|------------|
| **`helper_script/`** | Standalone scripts to reproduce the paper's numbers from the archived raw logs. `logs_aggregator/aggregate_by_type.py` produces the 2×2 old-vs-new-system comparison across sample-type groups (reading each system's existing `aggregate_metrics_results*.json`), and `bootstrap_ci.py` plots a metric with its 95% confidence interval via bootstrap. `cuga_logs_download/download_cuga_logs.py` is a fallback for restoring the CUGA raw logs from the Hugging Face Hub if they are missing. See [`helper_script/README.md`](helper_script/README.md). |

---

## Getting started

Pick the agent you want to evaluate and follow its own README — each is
self-contained:

- **Pi:** [`pi_agent/README.md`](pi_agent/README.md) (upstream Pi agent) and
  [`pi_agent/README_EVAL.md`](pi_agent/README_EVAL.md) (evaluation pipeline —
  build the Docker sandbox, set up the Python env, then run the two-terminal flow).
- **CUGA:** [`CUGA_generalist_agent/README.md`](CUGA_generalist_agent/README.md)
  (agent) and
  [`CUGA_generalist_agent/experiment_clean/README.md`](CUGA_generalist_agent/experiment_clean/README.md)
  (evaluation pipeline).

Both pipelines depend on
[`agent_quality_inspect/`](agent_quality_inspect/README.md) — our extended
version of TED's `agent-quality-inspect`, which adds metrics beyond the upstream
package.
