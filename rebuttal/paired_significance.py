#!/usr/bin/env python3
"""
Paired significance of system_new - system_old, per (setting, table, T, metric), for ONE
agent-model at a time.

Answers the reviewer's question: of the performance differences on previously-supported
tasks (T_old) and new tasks (T_new), how many are statistically significant once we account
for pairing (same test cases run by both systems)?

Why paired (and why NOT the existing bootstrap_ci.py as-is):
  helper_script/bootstrap_ci.py bootstraps EACH system's mean separately -> two CIs that
  overlap because they carry the large between-task variance. That is the unpaired view the
  reviewer objects to. Here we difference each task against itself first (d_i = new_i - old_i),
  which cancels the shared between-task variance, then test whether mean(d_i) differs from 0.

Reported quantity per cell (on the paired diff vector d_i):
  * Bootstrap 95% CI of mean(d): resample d_i with replacement (same bootstrap machinery the
    paper already uses in bootstrap_ci.py), take 2.5/97.5 percentiles of the bootstrap means.
    Significance test: the difference is significant iff this CI excludes 0.

Respects bootstrap_ci.EXCLUDE_CELLS / EXCLUDE_METRICS so meaningless cells (e.g. skill_*
for system_old on T_new) are skipped exactly as the existing tooling does.

Usage
-----
Per agent-model, passing a folder for each setting (any may be omitted):

    /usr/bin/python3 rebuttal/paired_significance.py \
        --agent CUGA-Opus \
        --s1 /path/to/cuga_opus/settings_1 \
        --s2 /path/to/cuga_opus/settings_2 \
        --s3 /path/to/cuga_opus/settings_3

Each --sN path is the *setting folder* that directly contains the per-table dirs
(table_1_general_single_domain / table1_general_single_domain, etc.). The result JSON
file (aggregate_metrics_results_system_{old,new}_T_{old,new}.json) may sit directly in a
table dir or one level below it in a run folder -- both are handled.

Omit any setting that does not exist for this agent (e.g. --s3 for an agent that only ran
settings 1-2). At least one of --s1/--s2/--s3 must be given.

With NO arguments the script falls back to discovering all three agents under
aggregate_results_log/paper_experiments (the original behaviour), producing one output set
per agent.

Outputs (into rebuttal/paired_CI/significance/), one set PER agent-model:
  * paired_significance_<agent>.json      (params + every per-cell result)
  * paired_significance_plot_<agent>.png  (one subplot per metric)

Read-only over the source result files. Writes only into rebuttal/paired_CI/significance/.
"""

import argparse
import glob
import json
import math
import os
import re
import sys

import numpy as np

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.lines import Line2D  # noqa: E402

ROOT = "/home/ec2-user/work_folder/aggregate_mask_generalist_agent_skill_usefulness_internal"
EXP = os.path.join(ROOT, "aggregate_results_log", "paper_experiments")
OUT = os.path.join(ROOT, "rebuttal", "paired_CI", "significance")

# Reuse the existing bootstrap machinery + exclusion rules.
sys.path.insert(0, os.path.join(ROOT, "helper_script"))
import bootstrap_ci as bci  # noqa: E402

# Default (no-arg) discovery.
DEFAULT_AGENTS = ["cuga_opus_4_6", "pi_opus_4_6", "cuga_gpt5.6-sol"]
DEFAULT_SETTINGS = ["settings_1", "settings_2", "settings_3"]
AGENT_LABEL = {
    "cuga_opus_4_6": "CUGA-Opus",
    "pi_opus_4_6": "PI-Opus",
    "cuga_gpt5.6-sol": "CUGA-GPT5.6",
}

TABLES = {
    "table_1": ["table_1_general_single_domain", "table1_general_single_domain"],
    "table_2": ["table_2_cross_domain", "table2_cross_domain"],
    "table_3": ["table_3_general_single_cross_domain", "table3_general_single_cross_domain"],
}

# Human-readable table names for plot axis labels.
TABLE_LABEL = {
    "table_1": "general+single-domain",
    "table_2": "cross_domain",
    "table_3": "union",
}

N_BOOT = 10000  # same as helper_script/bootstrap_ci.py
ALPHA = 0.05
SEED = 12345

# Settings to exclude from the plots. Empty = include all settings provided.
SKIP_PLOT_SETTINGS = set()


def slug(label):
    """Filesystem-safe token from an agent label."""
    return re.sub(r"[^0-9A-Za-z._-]+", "_", label).strip("_")


def find_table_dir(setting_path, variants):
    """setting_path directly contains the per-table dirs; try each naming variant."""
    for v in variants:
        p = os.path.join(setting_path, v)
        if os.path.isdir(p):
            return p
    return None


def find_json(folder, fname):
    """Result file is in `folder` directly or one level down in a run folder."""
    direct = os.path.join(folder, fname)
    if os.path.isfile(direct):
        return direct
    hits = glob.glob(os.path.join(folder, "*", fname))
    return hits[0] if hits else None


def load_metrics(folder, system, T):
    f = find_json(folder, f"aggregate_metrics_results_system_{system}_T_{T}.json")
    if not f:
        return None
    return json.load(open(f)).get("metrics", {})


def paired_tests(old_ps, new_ps, rng):
    """old_ps/new_ps: {tc_id: value}. Returns paired-diff stats or None if unusable."""
    shared = sorted(set(old_ps) & set(new_ps))
    pairs = [(old_ps[k], new_ps[k]) for k in shared
             if isinstance(old_ps[k], (int, float)) and isinstance(new_ps[k], (int, float))]
    if len(pairs) < 2:
        return None
    old = np.array([a for a, _ in pairs], float)
    new = np.array([b for _, b in pairs], float)
    d = new - old
    n = d.size
    mean_d = float(d.mean())

    # Bootstrap CI of mean(d): resample the paired difference vector (same 1x bootstrap
    # as helper_script/bootstrap_ci.py, but on d_i instead of a single system's values).
    idx = rng.integers(0, n, size=(N_BOOT, n))
    boot_means = d[idx].mean(axis=1)
    ci_low, ci_high = np.percentile(boot_means, [100 * ALPHA / 2, 100 * (1 - ALPHA / 2)])

    return {
        "n": int(n),
        "mean_diff": mean_d,
        "ci_low": float(ci_low),
        "ci_high": float(ci_high),
        "significant_ci": bool(ci_low > 0 or ci_high < 0),
        "n_increased": int((d > 1e-9).sum()),
        "n_unchanged": int((np.abs(d) <= 1e-9).sum()),
        "n_decreased": int((d < -1e-9).sum()),
    }


def compute_rows(setting_paths, rng):
    """setting_paths: {setting_key -> folder_path or None}. Returns list of per-cell rows."""
    rows = []
    for setting_key, spath in setting_paths.items():
        if not spath:
            continue
        if not os.path.isdir(spath):
            print(f"  WARNING: {setting_key} path is not a directory, skipping: {spath}",
                  file=sys.stderr)
            continue
        for table_key, variants in TABLES.items():
            tdir = find_table_dir(spath, variants)
            if not tdir:
                continue
            for T in ["old", "new"]:
                om = load_metrics(tdir, "old", T)
                nm = load_metrics(tdir, "new", T)
                if om is None or nm is None:
                    continue
                for metric in sorted(set(om) & set(nm)):
                    if metric in bci.EXCLUDE_METRICS:
                        continue
                    if (metric, "system_old", f"T_{T}") in bci.EXCLUDE_CELLS:
                        continue
                    if (metric, "system_new", f"T_{T}") in bci.EXCLUDE_CELLS:
                        continue
                    po = om[metric].get("per_sample")
                    pn = nm[metric].get("per_sample")
                    if not isinstance(po, dict) or not isinstance(pn, dict):
                        continue
                    res = paired_tests(po, pn, rng)
                    if res is None:
                        continue
                    rows.append({
                        "setting": setting_key, "table": table_key,
                        "T": f"T_{T}", "metric": metric, **res,
                    })
    return rows


def build_plot(agent_label, rows, out_path):
    """One or more figures for a single agent-model: each PNG holds up to 3 metric subplots
    (so each subplot stays large). Each point is a (setting, table, T) cell showing mean(d)
    with bootstrap-CI whiskers and a reference line at 0. Cells whose CI excludes 0 are
    highlighted. Returns the list of PNG paths written."""
    plot_rows = [r for r in rows if r["setting"] not in SKIP_PLOT_SETTINGS]
    metrics = sorted({r["metric"] for r in plot_rows})
    if not metrics:
        return []
    T_COLOR = {"T_old": "#4C72B0", "T_new": "#DD8452"}

    def short(r):
        s = r["setting"].replace("settings_", "S")
        t = TABLE_LABEL.get(r["table"], r["table"])
        return f"{s} / {t}"

    settings_present = sorted({r["setting"].replace("settings_", "") for r in plot_rows})
    legend_handles = [
        Line2D([0], [0], marker="o", color="w", markerfacecolor=T_COLOR["T_old"],
               markersize=10, label="T_old"),
        Line2D([0], [0], marker="o", color="w", markerfacecolor=T_COLOR["T_new"],
               markersize=10, label="T_new"),
        Line2D([0], [0], marker="o", color="w", markerfacecolor="#888888",
               markeredgecolor="black", markeredgewidth=1.5, markersize=11,
               label="CI excludes 0 (significant)"),
    ]

    # Chunk metrics 3-per-figure so each subplot renders at a readable size.
    PER_FIG = 3
    chunks = [metrics[i:i + PER_FIG] for i in range(0, len(metrics), PER_FIG)]
    base, ext = os.path.splitext(out_path)
    written = []

    for ci, chunk in enumerate(chunks, start=1):
        nrows = len(chunk)
        fig, axes = plt.subplots(nrows, 1, figsize=(11.0, 5.2 * nrows), squeeze=False)
        axes = axes.ravel()

        for ax, metric in zip(axes, chunk):
            cells = [r for r in plot_rows if r["metric"] == metric]
            cells.sort(key=lambda r: (r["T"] != "T_old", r["setting"], r["table"]))
            ys = np.arange(len(cells))
            for y, r in zip(ys, cells):
                md = r["mean_diff"]
                lo_err = md - r["ci_low"]
                hi_err = r["ci_high"] - md
                sig = r["significant_ci"]
                color = T_COLOR[r["T"]]
                ax.errorbar(md, y, xerr=[[lo_err], [hi_err]], fmt="o",
                            color=color, ecolor=color,
                            elinewidth=2.0 if sig else 1.0,
                            capsize=4, markersize=10 if sig else 7,
                            markeredgecolor="black" if sig else color,
                            markeredgewidth=1.5 if sig else 0.0)
            ax.axvline(0.0, color="#333333", linewidth=1.2, linestyle="--")
            ax.set_yticks(ys)
            ax.set_yticklabels([short(r) for r in cells], fontsize=16)
            ax.tick_params(axis="x", labelsize=15)
            ax.invert_yaxis()
            ax.set_title(metric, fontsize=20, fontweight="bold")
            ax.set_xlabel(r"mean paired diff  (new $-$ old)", fontsize=16)
            ax.grid(True, axis="x", alpha=0.3)

        # Legend on the right, outside the plot area, so it never blocks the points.
        fig.legend(handles=legend_handles, loc="center left",
                   bbox_to_anchor=(0.80, 0.5), ncol=1, fontsize=14, frameon=False)
        part = f"  (part {ci}/{len(chunks)})" if len(chunks) > 1 else ""
        fig.suptitle(f"{agent_label} — paired difference (system_new - system_old), "
                     f"bootstrap 95% CI  [settings {', '.join(settings_present)}]{part}",
                     fontsize=17, fontweight="bold", y=0.998)
        # Reserve the right margin for the legend and the top for the title.
        fig.tight_layout(rect=[0, 0, 0.79, 0.975])

        fig_path = out_path if len(chunks) == 1 else f"{base}_part{ci}{ext}"
        fig.savefig(fig_path, dpi=130, bbox_inches="tight")
        plt.close(fig)
        written.append(fig_path)

    return written


def process_agent(agent_label, setting_paths):
    """Compute + write JSON/plot for one agent-model. Returns the rows."""
    rng = np.random.default_rng(SEED)
    rows = compute_rows(setting_paths, rng)
    if not rows:
        print(f"  NOTE: no usable cells for {agent_label}; nothing written.", file=sys.stderr)
        return rows

    tag = slug(agent_label)
    json_path = os.path.join(OUT, f"paired_significance_{tag}.json")
    png_path = os.path.join(OUT, f"paired_significance_plot_{tag}.png")

    with open(json_path, "w") as f:
        json.dump({"agent": agent_label,
                   "params": {"n_boot": N_BOOT, "alpha": ALPHA, "seed": SEED,
                              "significance_test": "bootstrap_ci_excludes_zero"},
                   "setting_paths": setting_paths,
                   "rows": rows}, f, indent=2)

    pngs = build_plot(agent_label, rows, png_path)

    # Headline tallies the reviewer asked for: focus on drops (mean_diff < 0).
    def tally(subset, label):
        drops = [r for r in subset if r["mean_diff"] < 0]
        sig_ci = [r for r in drops if r["significant_ci"]]
        print(f"  {label}: {len(drops)} drops | {len(sig_ci)} sig by bootstrap CI")

    headline = ["capability_score", "mean_progress_rate"]
    print(f"\n=== {agent_label}: paired significance "
          f"(n_boot={N_BOOT}, bootstrap CI) ===")
    print(f"  Total cells: {len(rows)}")
    print("  -- T_old (previously supported tasks) --")
    tally([r for r in rows if r["T"] == "T_old"], "all metrics")
    tally([r for r in rows if r["T"] == "T_old" and r["metric"] in headline], "headline (cap+mpr)")
    print("  -- T_new (new tasks) --")
    tally([r for r in rows if r["T"] == "T_new"], "all metrics")
    tally([r for r in rows if r["T"] == "T_new" and r["metric"] in headline], "headline (cap+mpr)")
    print(f"  Wrote -> {os.path.basename(json_path)}, "
          f"{', '.join(os.path.basename(p) for p in pngs)}")
    return rows


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Paired significance (bootstrap CI) for one agent-model.")
    parser.add_argument("--agent", help="Agent-model label (used for titles + filenames).")
    parser.add_argument("--s1", help="Folder for settings_1 (contains the table_* dirs).")
    parser.add_argument("--s2", help="Folder for settings_2.")
    parser.add_argument("--s3", help="Folder for settings_3.")
    args = parser.parse_args(argv)

    os.makedirs(OUT, exist_ok=True)

    if args.agent or args.s1 or args.s2 or args.s3:
        if not args.agent:
            parser.error("--agent is required when passing setting paths.")
        if not (args.s1 or args.s2 or args.s3):
            parser.error("give at least one of --s1/--s2/--s3.")
        setting_paths = {"settings_1": args.s1, "settings_2": args.s2, "settings_3": args.s3}
        process_agent(args.agent, setting_paths)
        return

    # No-arg fallback: discover all default agents under EXP and process each separately.
    print("No arguments given; discovering default agents under paper_experiments.")
    for agent in DEFAULT_AGENTS:
        setting_paths = {s: os.path.join(EXP, agent, s) for s in DEFAULT_SETTINGS}
        setting_paths = {s: (p if os.path.isdir(p) else None) for s, p in setting_paths.items()}
        process_agent(AGENT_LABEL.get(agent, agent), setting_paths)


if __name__ == "__main__":
    main()
