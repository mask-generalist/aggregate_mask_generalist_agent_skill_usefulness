# Aggregate by type (2×2 comparison)

Compares two systems (old vs new) across T_old / T_new sample-type groups, producing a 2×2 metrics report.

```bash
python logs_aggregator/aggregate_by_type.py \
    --system-old path/to/old_system_job/ \
    --system-new path/to/new_system_job/ \
    --sample-types logs_aggregator/sample_types.yaml \
    --groups logs_aggregator/groups.yaml
```

**Example** — reproduce the CUGA setting-1 comparison from the archived raw logs
(the raw-log folders live at the repo root, one level up from `helper_script/`):

```bash
python logs_aggregator/aggregate_by_type.py \
    --system-old ../CUGA_raw_logs/CUGA_gpt5_6_sol_setting1_old_system \
    --system-new ../CUGA_raw_logs/CUGA_gpt5_6_sol_setting1_new_system \
    --sample-types logs_aggregator/sample_types.yaml \
    --groups logs_aggregator/groups.yaml
```

| Flag | Required | Default | Description |
|------|----------|---------|-------------|
| `--system-old` | Yes | — | Old system job dir or parent (recursive discovery) |
| `--system-new` | Yes | — | New system job dir or parent (recursive discovery) |
| `--sample-types` | No | `logs_aggregator/sample_types.yaml` | Sample type definitions YAML |
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


# Confidence Interval Plotter

To plot the metric value with 95% confidence interval using the bootstrap method, use the below command 

```bash
python3 bootstrap_ci.py <agg_dir_path>
```

Example:

```bash
python3 bootstrap_ci.py ../aggregate_results_log/paper_experiments/cuga_gpt5.6-sol/settings_1/table_1_general_single_domain
```

# Downloading the raw logs (fallback)

The raw-log folders (`CUGA_raw_logs/`, `cuga_raw_logs_improvement/`) are already included
in the repo, so you normally don't need this. It's here only as a fallback — if a
folder is missing or incomplete, `cuga_logs_download/download_cuga_logs.py` can
restore it from the Hugging Face Hub:

- [`CUGA_raw_logs`](https://huggingface.co/datasets/maskgeneralist/CUGA_raw_logs) → `<repo_root>/CUGA_raw_logs/`
- [`cuga_raw_logs_improvement`](https://huggingface.co/datasets/maskgeneralist/cuga_raw_logs_improvement) → `<repo_root>/cuga_raw_logs_improvement/`

```bash
pip install -U "huggingface_hub[cli]"
python cuga_logs_download/download_cuga_logs.py            # both folders
python cuga_logs_download/download_cuga_logs.py --only CUGA_raw_logs   # just one
```