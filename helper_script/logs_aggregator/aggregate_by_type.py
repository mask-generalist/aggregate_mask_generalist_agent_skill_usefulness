"""2×2 system comparison: aggregate metrics by sample type.

Compares --system-old vs --system-new across T_old/T_new sample groups.
All per-sample metric values are read from each system's source
aggregate_metrics_results.json — nothing is recomputed from trial data.

Output (to experiment_results/agg/system_old_<name>_vs_system_new_<name>_agg_<ts>/):
  - 4 aggregate JSONs  (system_{old,new}_T_{old,new})
  - 4 filtered trial dirs with trial_N_results.json per cell
  - sample_classification.json, print_results.log, config copies

Usage:
    PYENV_VERSION=venv_meta_harness PYTHONPATH="." \\
        python -m experiment_clean.aggregate_by_type \\
        --system-old <path> --system-new <path> \\
        --sample-types experiment_clean/sample_types.yaml \\
        --groups experiment_clean/groups.yaml
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import shutil
import statistics
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import yaml

logger = logging.getLogger(__name__)

METRIC_KEYS = [
    "max_progress_rate", "mean_progress_rate",
    "total_tokens", "total_latency_ms", "tool_call_count",
    "skill_precision", "skill_recall", "capability_score",
    "pass@k", "pass^k",
]

RATE_METRICS = {
    "max_progress_rate", "mean_progress_rate",
    "skill_precision", "skill_recall", "capability_score",
    "pass@k", "pass^k",
}

# Reported columns. T_old/T_new come from groups.yaml; T_union is the combined
# set of both groups (computed, not configured).
GROUP_LABELS = ("T_old", "T_new", "T_union")


def group_sample_ids(gname: str, shared: Dict[str, str], groups: Dict[str, List[str]]) -> set:
    """Sample ids belonging to a reported column.

    T_old/T_new → samples whose type is in that group. T_union → samples whose
    type is in either group (the combined set).
    """
    if gname == "T_union":
        gtypes = set(groups["T_old"]) | set(groups["T_new"])
    else:
        gtypes = set(groups[gname])
    return {s for s, t in shared.items() if t in gtypes}


# ─── Config ─────────────────────────────────────────────────────────────────


def load_sample_types(path: str) -> Dict[str, frozenset]:
    """sample_types.yaml → {type_label: frozenset(expected_skills)}."""
    raw = yaml.safe_load(open(path, encoding="utf-8"))
    types = raw.get("sample_types", {})
    return {label: frozenset(d["expected_skills"]) for label, d in types.items()}


def load_groups(path: str, known: Dict[str, frozenset]) -> Dict[str, List[str]]:
    """groups.yaml → {"T_old": [...], "T_new": [...]}."""
    raw = yaml.safe_load(open(path, encoding="utf-8"))
    for key in ("T_old", "T_new"):
        for t in raw.get(key, []):
            if t not in known:
                raise ValueError(f"Unknown type '{t}' in {key}. Known: {sorted(known)}")
    return {k: raw.get(k) or [] for k in ("T_old", "T_new")}


# ─── Classification ─────────────────────────────────────────────────────────


def classify_all_samples(job_dir: Path, type_defs: Dict[str, frozenset]) -> Dict[str, str]:
    """Classify tc_* samples in a job dir → {sample_id: type_label}."""
    skill_to_type = {skills: label for label, skills in type_defs.items()}
    result = {}

    for entry in sorted(job_dir.iterdir()):
        if not entry.is_dir() or not entry.name.startswith("tc_"):
            continue
        # Find the YAML in any available trial dir (identical across trials)
        yaml_path = None
        for trial_dir in sorted(entry.iterdir()):
            if trial_dir.is_dir() and trial_dir.name.startswith("trial_"):
                candidate = trial_dir / f"{entry.name}.yaml"
                if candidate.exists():
                    yaml_path = candidate
                    break
        if yaml_path is None:
            logger.warning("No YAML for %s — skipping", entry.name)
            continue

        case = yaml.safe_load(open(yaml_path, encoding="utf-8"))
        skills = frozenset()
        for step in case.get("test_steps", []):
            if step.get("type") == "dynamic_conversation":
                invocations = (step.get("skill_validations") or {}).get("expected_skill_invocations") or []
                skills = frozenset(s["skill"] for s in invocations if s.get("skill"))
                break

        result[entry.name] = skill_to_type.get(skills, "unclassified")
    return result


# ─── Data loading ───────────────────────────────────────────────────────────


def load_system_data(
    system_path: Path, type_defs: Dict[str, frozenset]
) -> Tuple[Dict[str, str], List[Dict], int, List[Path], Dict, List[Path]]:
    """Load one system: classify samples, read trial data + source aggregate.

    Returns (classification, trial_samples, n_trials, eval_dirs, source_agg, agg_files_used).
    """
    # Find job directories
    has_tc = any(p.is_dir() and p.name.startswith("tc_") for p in system_path.iterdir())
    if has_tc:
        job_dirs = [system_path]
    else:
        job_dirs = sorted({
            tc.parent for tc in system_path.rglob("tc_*") if tc.is_dir()
        })
        if not job_dirs:
            raise FileNotFoundError(f"No jobs found under {system_path}")
        logger.info("Found %d job dirs under %s", len(job_dirs), system_path)

    classification: Dict[str, str] = {}
    trial_samples: List[Dict] = []
    eval_dirs: List[Path] = []
    agg_files_used: List[Path] = []
    n_trials: Optional[int] = None
    source_agg: Dict[str, Any] = {"metrics": {}}

    for job_dir in job_dirs:
        logger.info("Loading job: %s", job_dir.name)
        classification.update(classify_all_samples(job_dir, type_defs))

        # Find eval dir (latest eval_results_*)
        eval_dir = sorted(
            p for p in job_dir.iterdir()
            if p.is_dir() and p.name.startswith("eval_results_")
        )[-1]
        eval_dirs.append(eval_dir)

        # Read trial files
        for tf in sorted(eval_dir.glob("trial_*_results.json")):
            data = json.loads(tf.read_text(encoding="utf-8"))
            trial_samples.extend(data.get("samples", []))
        job_n = len(list(eval_dir.glob("trial_*_results.json")))
        if n_trials is None:
            n_trials = job_n
        elif job_n != n_trials:
            logger.warning("Job %s: %d trials (expected %d)", job_dir.name, job_n, n_trials)

        # Read source aggregate and merge per-sample values
        agg_files = sorted(eval_dir.glob("aggregate_metrics_results*.json"))
        if agg_files:
            agg_files_used.append(agg_files[-1])
            agg = json.loads(agg_files[-1].read_text(encoding="utf-8"))
            for key in METRIC_KEYS:
                src = agg.get("metrics", {}).get(key, {})
                if key not in source_agg["metrics"]:
                    entry: Dict[str, Any] = {"per_sample": {}}
                    if key in ("pass@k", "pass^k"):
                        entry["k"] = src["k"]
                    source_agg["metrics"][key] = entry
                source_agg["metrics"][key]["per_sample"].update(src.get("per_sample", {}))

    type_counts = defaultdict(int)
    for t in classification.values():
        type_counts[t] += 1
    logger.info("System %s: %d samples — %s", system_path.name, len(classification), dict(type_counts))

    return classification, trial_samples, n_trials or 0, eval_dirs, source_agg, agg_files_used


# ─── Aggregation ────────────────────────────────────────────────────────────


def aggregate_subset(
    sample_ids: set, trial_samples: List[Dict], n_trials: int, source_agg: Dict
) -> Dict[str, Any]:
    """Filter source aggregate to sample_ids and re-average."""
    src = source_agg.get("metrics", {})
    metrics = {}

    for key in METRIC_KEYS:
        source = src.get(key, {})
        per_sample = {sid: source.get("per_sample", {}).get(sid)
                      for sid in sample_ids if sid in source.get("per_sample", {})}
        valid = [v for v in per_sample.values() if v is not None]
        entry: Dict[str, Any] = {
            "per_sample": per_sample,
            "avg": statistics.mean(valid) if valid else None,
        }
        if key in ("pass@k", "pass^k"):
            entry["k"] = source["k"]
        metrics[key] = entry

    # Summary from trial data
    subset = [s for s in trial_samples if s["sample_id"] in sample_ids]
    ok = [s for s in subset if s.get("status") == "success"]

    return {
        "timestamp": datetime.now().isoformat(),
        "summary": {
            "n_trials": n_trials, "n_samples": len(sample_ids),
            "total_runs": len(subset), "successful": len(ok),
            "failed": len(subset) - len(ok),
            "avg_turns": sum(s.get("total_turns", 0) for s in ok) / len(ok) if ok else 0,
        },
        "n_samples": len(sample_ids),
        "n_trials": n_trials,
        "metrics": metrics,
    }


# ─── Filtered trial output ─────────────────────────────────────────────────


def write_filtered_trials(eval_dirs: List[Path], sample_ids: set, out_dir: Path) -> None:
    """Write trial_N_results.json filtered to sample_ids into out_dir/."""
    out_dir.mkdir(parents=True, exist_ok=True)
    by_trial: Dict[int, list] = {}

    for eval_dir in eval_dirs:
        for tf in sorted(eval_dir.glob("trial_*_results.json")):
            data = json.loads(tf.read_text(encoding="utf-8"))
            tid = data["trial_id"]
            by_trial.setdefault(tid, []).extend(
                s for s in data.get("samples", []) if s["sample_id"] in sample_ids
            )

    for tid in sorted(by_trial):
        samples = by_trial[tid]
        trial = {
            "trial_id": tid, "total_samples": len(samples),
            "successful": sum(1 for s in samples if s.get("status") == "success"),
            "samples": samples,
        }
        (out_dir / f"trial_{tid}_results.json").write_text(json.dumps(trial, indent=2, default=str))

    logger.info("Wrote %d filtered trial files to %s", len(by_trial), out_dir.name)


# ─── 2×2 display ───────────────────────────────────────────────────────────


def _fmt(key: str, val: Optional[float]) -> str:
    if val is None:
        return "N/A"
    if key in RATE_METRICS:
        return f"{val:.4f}"
    if key in ("total_tokens", "total_latency_ms"):
        return f"{val:,.0f}"
    return f"{val:.2f}"


def print_quadrant(
    quad: Dict[str, Dict[str, Optional[Dict]]],
    old_name: str, new_name: str, output_dir: Path,
    old_agg_files: List[Path], new_agg_files: List[Path],
) -> None:
    """Print 2×2 tables to console and save to print_results.log."""
    W_SYS, W_VAL = 12, 14
    lines: List[str] = []
    out = lines.append

    out(f"Command: {' '.join(sys.argv)}")
    out(f"Timestamp: {datetime.now().isoformat()}")
    out(f"system_old: {old_name}")
    out(f"system_new: {new_name}")
    out("")
    out("Source aggregates:")
    for f in old_agg_files:
        out(f"  system_old: {f}")
    for f in new_agg_files:
        out(f"  system_new: {f}")
    out("")

    for sl in ("system_old", "system_new"):
        for g in GROUP_LABELS:
            a = quad[sl].get(g)
            out(f"  {sl} × {g}: {a['n_samples'] if a else 0} samples")
    out("")

    out(f"╔{'═'*68}╗")
    out(f"║  Comparison: {old_name} vs {new_name:<{68-17-len(old_name)}}║")
    out(f"╚{'═'*68}╝")
    out("")

    for key in METRIC_KEYS:
        out(f"  {key}")
        out(f"  ┌{'─'*W_SYS}┬{'─'*W_VAL}┬{'─'*W_VAL}┬{'─'*W_VAL}┐")
        out(f"  │{'':{W_SYS}}│{'T_old':^{W_VAL}}│{'T_new':^{W_VAL}}│{'T_union':^{W_VAL}}│")
        out(f"  ├{'─'*W_SYS}┼{'─'*W_VAL}┼{'─'*W_VAL}┼{'─'*W_VAL}┤")
        for sl in ("system_old", "system_new"):
            vals = []
            for g in GROUP_LABELS:
                cell = quad[sl].get(g)
                v = cell.get("metrics", {}).get(key, {}).get("avg") if cell else None
                vals.append(_fmt(key, v))
            out(f"  │{sl:^{W_SYS}}│{vals[0]:^{W_VAL}}│{vals[1]:^{W_VAL}}│{vals[2]:^{W_VAL}}│")
        out(f"  └{'─'*W_SYS}┴{'─'*W_VAL}┴{'─'*W_VAL}┴{'─'*W_VAL}┘")
        out("")

    text = "\n".join(lines)
    print(text)
    (output_dir / "print_results.log").write_text(text + "\n", encoding="utf-8")
    logger.info("Wrote print_results.log")


# ─── Main pipeline ──────────────────────────────────────────────────────────


def process_comparison(
    old_path: Path, new_path: Path,
    type_defs: Dict[str, frozenset], groups: Dict[str, List[str]],
    sample_types_file: str, groups_file: str,
) -> None:
    """Load both systems → intersect samples → aggregate 2×2 → report."""

    # Load
    logger.info("=== Loading system_old: %s ===", old_path)
    old_cls, old_trials, old_nt, old_edirs, old_agg, old_agg_files = load_system_data(old_path, type_defs)
    logger.info("=== Loading system_new: %s ===", new_path)
    new_cls, new_trials, new_nt, new_edirs, new_agg, new_agg_files = load_system_data(new_path, type_defs)

    # Intersect
    common = set(old_cls) & set(new_cls)
    if not common:
        raise ValueError(f"No common samples ({len(old_cls)} vs {len(new_cls)})")
    bad = {s for s in common if old_cls[s] != new_cls[s]}
    if bad:
        raise ValueError(f"Type mismatch on: {sorted(bad)}")
    if set(old_cls) != set(new_cls):
        logger.warning("Filtered to %d common samples (dropped %d old-only, %d new-only)",
                        len(common), len(set(old_cls) - common), len(set(new_cls) - common))

    shared = {s: old_cls[s] for s in common}
    old_trials = [s for s in old_trials if s["sample_id"] in common]
    new_trials = [s for s in new_trials if s["sample_id"] in common]
    logger.info("Using %d common samples", len(shared))

    # Output dir
    old_name, new_name = old_path.resolve().name, new_path.resolve().name
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")

    # Find experiment_results/ ancestor for agg root
    agg_root = old_path.resolve().parent / "agg"
    for p in [old_path.resolve(), new_path.resolve()]:
        cur = p
        while cur != cur.parent:
            if cur.name == "experiment_results":
                agg_root = cur / "agg"
                break
            cur = cur.parent

    out_dir = agg_root / f"system_old_{old_name}_vs_system_new_{new_name}_agg_{ts}"
    out_dir.mkdir(parents=True, exist_ok=True)
    logger.info("Output: %s", out_dir)

    shutil.copy2(sample_types_file, out_dir / "sample_types.yaml")
    shutil.copy2(groups_file, out_dir / "groups.yaml")

    # Classification
    cls_data = {}
    for gname in GROUP_LABELS:
        gids = group_sample_ids(gname, shared, groups)
        samples = [{"sample_id": s, "type": shared[s]} for s in gids]
        samples.sort(key=lambda x: (x["type"], x["sample_id"]))
        cls_data[gname] = {"samples": samples}
    (out_dir / "sample_classification.json").write_text(json.dumps(cls_data, indent=2, default=str))
    logger.info("Wrote sample_classification.json")

    # Aggregate 2×2
    quad: Dict[str, Dict[str, Optional[Dict]]] = {"system_old": {}, "system_new": {}}

    for label, trials, nt, edirs, agg in [
        ("system_old", old_trials, old_nt, old_edirs, old_agg),
        ("system_new", new_trials, new_nt, new_edirs, new_agg),
    ]:
        for gname in GROUP_LABELS:
            gids = group_sample_ids(gname, shared, groups)
            if not gids:
                logger.warning("No samples for %s × %s", label, gname)
                quad[label][gname] = None
                continue

            result = aggregate_subset(gids, trials, nt, agg)
            fname = f"aggregate_metrics_results_{label}_{gname}.json"
            (out_dir / fname).write_text(json.dumps(result, indent=2, default=str))
            logger.info("Wrote %s (%d samples)", fname, result["n_samples"])
            quad[label][gname] = result

            write_filtered_trials(edirs, gids, out_dir / f"{label}_{gname}")

    print_quadrant(quad, old_name, new_name, out_dir, old_agg_files, new_agg_files)
    logger.info("Done. Output in %s", out_dir)


# ─── CLI ────────────────────────────────────────────────────────────────────


def main() -> None:
    p = argparse.ArgumentParser(description="Compare two systems across T_old/T_new sample groups.")
    p.add_argument("--system-old", required=True, help="Old system job dir or parent.")
    p.add_argument("--system-new", required=True, help="New system job dir or parent.")
    p.add_argument("--sample-types", default=os.path.join(os.path.dirname(__file__), "sample_types.yaml"))
    p.add_argument("--groups", required=True, help="T_old/T_new groups YAML.")
    args = p.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    old, new = Path(args.system_old), Path(args.system_new)
    for label, path in [("system-old", old), ("system-new", new)]:
        if not path.is_dir():
            logger.error("%s not found: %s", label, path)
            sys.exit(1)

    type_defs = load_sample_types(args.sample_types)
    groups = load_groups(args.groups, type_defs)
    logger.info("Types: %s | T_old=%s, T_new=%s", sorted(type_defs), groups["T_old"], groups["T_new"])

    process_comparison(old, new, type_defs, groups, args.sample_types, args.groups)


if __name__ == "__main__":
    main()
