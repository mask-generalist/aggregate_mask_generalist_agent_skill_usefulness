#!/usr/bin/env python3
"""Bootstrap confidence intervals for aggregated CUGA evaluation metrics.

Given a 2x2 system-comparison directory (the kind produced by
experiment_clean/aggregate_by_type.py), this reads the per-test-case values
(``per_sample``) for every metric in every ``aggregate_metrics_results_*.json``
file and computes a bootstrap 95% CI around the mean.

Method (per metric, per file):
  * The population is the list of per-test-case values in ``per_sample`` --
    one scalar per test case (already averaged over trials upstream).
  * Point estimate = mean of those values.
  * For a metric with ``x`` test cases, each bootstrap iteration draws ``x``
    values (one per test case) WITH replacement and takes their mean -- the
    standard 1x bootstrap.
  * Repeat ``n_boot`` times; the CI is the [alpha/2, 1-alpha/2] percentiles
    of the bootstrap means.

CIs are computed for EVERY metric present in each file. ``RATE_METRICS`` only
controls number formatting in the log/plot (matching print_results.log), not
which metrics are bootstrapped.

Outputs (into a subfolder of the provided path, default ``bootstrap_ci/``):
  * bootstrap_ci_results.json  -- structured {metric: {system: {group: {...}}}}
  * bootstrap_ci_quadrant.log  -- print_results.log-style quadrant tables,
                                  CI shown beside each mean
  * bootstrap_ci_plot.png      -- point + asymmetric error-bar plot per metric

Run with system python3 (needs numpy + matplotlib; matplotlib 3.9.4 is present
there, the repo .venv does not have it):

    python3 bootstrap_ci.py <agg_dir_path>

All tuning flags default to the values in the plan, so the bare command above
is sufficient.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import Patch  # noqa: E402


# Metric ordering / grouping mirrors experiment_clean/aggregate_by_type.py so
# outputs line up with the existing tooling.
METRIC_KEYS = [
    "mean_progress_rate",
    "capability_score",
    "skill_precision",
    "skill_recall",
    "total_tokens",
    "total_latency_ms",
    "tool_call_count",
    "pass@k",
    "pass^k",
]

# Metrics to skip entirely (no bootstrap, no JSON/log/plot output).
EXCLUDE_METRICS = {
    "max_progress_rate",
}

# Per-cell exclusions: (metric, system, group) tuples to skip. Used to drop
# specific (metric, system, group) combinations while keeping the metric
# elsewhere. E.g. skill_precision/recall for system_old on new samples
# (T_new, and T_union which blends new samples in).
EXCLUDE_CELLS = {
    ("skill_precision", "system_old", "T_new"),
    ("skill_precision", "system_old", "T_union"),
    ("skill_recall", "system_old", "T_new"),
    ("skill_recall", "system_old", "T_union"),
}

# Display-formatting only (0-1 style values). Does NOT restrict which metrics
# are bootstrapped -- every metric in each file gets a CI.
RATE_METRICS = {
    "mean_progress_rate",
    "skill_precision",
    "skill_recall",
    "capability_score",
    "pass@k",
    "pass^k",
}

SYSTEMS = ("system_old", "system_new")
GROUPS = ("T_old", "T_new", "T_union")

# aggregate_metrics_results_<system_xxx>_<T_group>.json
FILE_RE = re.compile(
    r"^aggregate_metrics_results_(system_(?:old|new))_(T_(?:old|new|union))\.json$"
)


def bootstrap_ci(
    values: List[float],
    n_boot: int,
    alpha: float,
    rng: np.random.Generator,
) -> Dict[str, Any]:
    """Bootstrap CI around the mean of ``values``.

    Standard bootstrap: each iteration draws ``len(values)`` samples WITH
    replacement (as many as there are test cases for this metric) and takes
    their mean. Returns point estimate, CI bounds, and n.
    """
    arr = np.asarray(values, dtype=float)
    n = arr.size
    point = float(arr.mean())

    if n == 1:
        # Degenerate: nothing to resample; CI collapses to the point.
        return {
            "mean": point,
            "ci_low": point,
            "ci_high": point,
            "n": int(n),
            "degenerate": True,
        }

    # Vectorized: (n_boot, n) index matrix -> mean over axis 1.
    idx = rng.integers(0, n, size=(n_boot, n))
    boot_means = arr[idx].mean(axis=1)
    lo, hi = np.percentile(boot_means, [100 * alpha / 2, 100 * (1 - alpha / 2)])

    return {
        "mean": point,
        "ci_low": float(lo),
        "ci_high": float(hi),
        "n": int(n),
        "degenerate": False,
    }


def discover_files(agg_dir: Path) -> Dict[str, Dict[str, Path]]:
    """Map {system: {group: path}} from aggregate_metrics_results_*.json files."""
    found: Dict[str, Dict[str, Path]] = {s: {} for s in SYSTEMS}
    for p in sorted(agg_dir.glob("aggregate_metrics_results_*.json")):
        m = FILE_RE.match(p.name)
        if not m:
            continue
        system, group = m.group(1), m.group(2)
        found[system][group] = p
    return found


def load_metrics(path: Path) -> Dict[str, Any]:
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    return data.get("metrics", {})


def fmt_value(metric: str, v: float) -> str:
    """Format a single number matching print_results.log conventions."""
    if metric in RATE_METRICS:
        return f"{v:.4f}"
    if metric in ("total_tokens", "total_latency_ms"):
        return f"{v:,.0f}"
    if metric == "tool_call_count":
        return f"{v:,.2f}"
    return f"{v:.4f}"


def fmt_cell(metric: str, entry: Optional[Dict[str, Any]]) -> str:
    """'<mean> [<lo>, <hi>]' for a quadrant cell."""
    if entry is None:
        return "-"
    mean = fmt_value(metric, entry["mean"])
    lo = fmt_value(metric, entry["ci_low"])
    hi = fmt_value(metric, entry["ci_high"])
    return f"{mean} [{lo}, {hi}]"


def build_quadrant_log(
    results: Dict[str, Dict[str, Dict[str, Any]]],
    metric_order: List[str],
    params: Dict[str, Any],
) -> str:
    lines: List[str] = []
    lines.append("Bootstrap 95% confidence intervals (mean [ci_low, ci_high])")
    lines.append(
        "params: n_boot={n_boot}, alpha={alpha}, seed={seed}".format(**params)
    )
    lines.append("Each cell: point estimate = mean(per_sample); CI via bootstrap.")
    lines.append("")

    for metric in metric_order:
        by_system = results.get(metric)
        if not by_system:
            continue

        # Column width driven by the widest cell content.
        col_cells: Dict[str, List[str]] = {g: [] for g in GROUPS}
        for system in SYSTEMS:
            for g in GROUPS:
                entry = by_system.get(system, {}).get(g)
                col_cells[g].append(fmt_cell(metric, entry))

        row_label_w = max(len(s) for s in SYSTEMS) + 2  # padding
        col_w = {}
        for g in GROUPS:
            widest = max([len(g)] + [len(c) for c in col_cells[g]])
            col_w[g] = widest + 2  # padding

        def hline(left: str, mid: str, right: str) -> str:
            segs = ["─" * row_label_w] + ["─" * col_w[g] for g in GROUPS]
            return "  " + left + mid.join(segs) + right

        def row(label: str, cells: List[str]) -> str:
            parts = [f" {label} ".ljust(row_label_w)]
            for g, c in zip(GROUPS, cells):
                parts.append(c.center(col_w[g]))
            return "  │" + "│".join(parts) + "│"

        lines.append(f"  {metric}")
        lines.append(hline("┌", "┬", "┐"))
        header_cells = [g for g in GROUPS]
        lines.append(row("", header_cells))
        lines.append(hline("├", "┼", "┤"))
        for system in SYSTEMS:
            cells = [fmt_cell(metric, by_system.get(system, {}).get(g)) for g in GROUPS]
            lines.append(row(system, cells))
        lines.append(hline("└", "┴", "┘"))
        lines.append("")

    return "\n".join(lines) + "\n"


def build_plot(
    results: Dict[str, Dict[str, Dict[str, Any]]],
    metric_order: List[str],
    out_path: Path,
) -> None:
    metrics = [m for m in metric_order if results.get(m)]
    if not metrics:
        return

    ncols = 3
    nrows = math.ceil(len(metrics) / ncols)
    fig, axes = plt.subplots(nrows, ncols, figsize=(7.5 * ncols, 5.5 * nrows))
    axes = np.atleast_1d(axes).ravel()

    x = np.arange(len(GROUPS))
    bar_w = 0.38
    offsets = {"system_old": -bar_w / 2, "system_new": bar_w / 2}
    colors = {"system_old": "#4C72B0", "system_new": "#DD8452"}

    for ax, metric in zip(axes, metrics):
        by_system = results[metric]
        for system in SYSTEMS:
            heights, lo_err, hi_err, xs = [], [], [], []
            for gi, g in enumerate(GROUPS):
                entry = by_system.get(system, {}).get(g)
                if entry is None:
                    continue
                heights.append(entry["mean"])
                lo_err.append(entry["mean"] - entry["ci_low"])
                hi_err.append(entry["ci_high"] - entry["mean"])
                xs.append(gi + offsets[system])
            if not heights:
                continue
            ax.bar(
                xs,
                heights,
                width=bar_w,
                color=colors[system],
                label=system,
                yerr=[lo_err, hi_err],
                capsize=6,
                error_kw={"elinewidth": 1.6, "ecolor": "#333333"},
            )
        ax.set_title(metric, fontsize=22, fontweight="bold")
        ax.set_xticks(x)
        ax.set_xticklabels(GROUPS, fontsize=24)
        ax.tick_params(axis="y", labelsize=18)
        ax.grid(True, axis="y", alpha=0.3)

        # Bars start at 0. For 0-1 rate metrics, cap the top just above 1.
        if metric in RATE_METRICS:
            ax.set_ylim(0, 1.05)
        else:
            ax.set_ylim(bottom=0)

    for ax in axes[len(metrics):]:
        ax.set_visible(False)

    fig.suptitle(
        "Bootstrap 95% CI by metric (bar = mean, whiskers = 2.5/97.5 pct)",
        fontsize=26,
        fontweight="bold",
        y=0.99,
    )
    # Single shared legend for the whole figure, just under the title.
    legend_handles = [
        Patch(facecolor=colors[s], label=s) for s in SYSTEMS
    ]
    fig.legend(
        handles=legend_handles,
        loc="upper center",
        bbox_to_anchor=(0.5, 0.965),
        ncol=len(SYSTEMS),
        fontsize=24,
        frameon=False,
    )
    fig.tight_layout(rect=[0, 0, 1, 0.94])
    fig.savefig(out_path, dpi=130)
    plt.close(fig)


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Bootstrap CIs for aggregated CUGA metrics."
    )
    parser.add_argument("agg_dir", help="2x2 comparison directory path.")
    parser.add_argument("--n-boot", type=int, default=10000)
    parser.add_argument("--alpha", type=float, default=0.05)
    parser.add_argument("--seed", type=int, default=12345)
    parser.add_argument("--out-subdir", default="bootstrap_ci")
    args = parser.parse_args(argv)

    agg_dir = Path(args.agg_dir)
    if not agg_dir.is_dir():
        print(f"ERROR: not a directory: {agg_dir}", file=sys.stderr)
        return 1

    files = discover_files(agg_dir)
    n_found = sum(len(g) for g in files.values())
    if n_found == 0:
        print(
            f"ERROR: no aggregate_metrics_results_*.json files in {agg_dir}",
            file=sys.stderr,
        )
        return 1
    print(f"Found {n_found} aggregate file(s).")

    rng = np.random.default_rng(args.seed)

    # results[metric][system][group] = {mean, ci_low, ci_high, n, ...}
    results: Dict[str, Dict[str, Dict[str, Any]]] = {}

    for system in SYSTEMS:
        for group, path in files[system].items():
            metrics = load_metrics(path)
            for metric, mdata in metrics.items():
                if metric in EXCLUDE_METRICS:
                    continue
                if (metric, system, group) in EXCLUDE_CELLS:
                    continue
                per_sample = mdata.get("per_sample")
                if not per_sample:
                    continue
                values = list(per_sample.values())
                if len(values) == 0:
                    continue
                ci = bootstrap_ci(
                    values,
                    n_boot=args.n_boot,
                    alpha=args.alpha,
                    rng=rng,
                )
                # Sanity check against the file's reported avg.
                reported_avg = mdata.get("avg")
                if reported_avg is not None and not math.isclose(
                    ci["mean"], reported_avg, rel_tol=1e-6, abs_tol=1e-6
                ):
                    ci["reported_avg"] = reported_avg
                    print(
                        f"  NOTE: {metric} {system} {group}: computed mean "
                        f"{ci['mean']:.6g} != file avg {reported_avg:.6g}"
                    )
                results.setdefault(metric, {}).setdefault(system, {})[group] = ci

    # Metric order: known keys first (aggregate_by_type order), then any extras.
    extra = [m for m in results if m not in METRIC_KEYS]
    metric_order = [m for m in METRIC_KEYS if m in results] + sorted(extra)

    out_dir = agg_dir / args.out_subdir
    out_dir.mkdir(parents=True, exist_ok=True)

    params = {
        "n_boot": args.n_boot,
        "alpha": args.alpha,
        "seed": args.seed,
    }

    json_path = out_dir / "bootstrap_ci_results.json"
    with open(json_path, "w", encoding="utf-8") as fh:
        json.dump({"params": params, "metrics": results}, fh, indent=2)

    log_path = out_dir / "bootstrap_ci_quadrant.log"
    with open(log_path, "w", encoding="utf-8") as fh:
        fh.write(build_quadrant_log(results, metric_order, params))

    png_path = out_dir / "bootstrap_ci_plot.png"
    build_plot(results, metric_order, png_path)

    print(f"Wrote:\n  {json_path}\n  {log_path}\n  {png_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
