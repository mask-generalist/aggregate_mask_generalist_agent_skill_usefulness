#!/usr/bin/env python3

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

# {destination folder name (relative to repo root): HF dataset repo id}
DATASETS = {
    "CUGA_raw_logs": "maskgeneralist/CUGA_raw_logs",
    "cuga_raw_logs_improvement": "maskgeneralist/cuga_raw_logs_improvement",
}

# This file lives at <repo_root>/helper_script/cuga_logs_download/, so the repo
# root is two directories up.
REPO_ROOT = Path(__file__).resolve().parents[2]


def download_one(folder_name: str, repo_id: str, clean: bool) -> None:
    try:
        from huggingface_hub import snapshot_download
    except ImportError:
        sys.exit(
            'huggingface_hub is not installed. Run:\n'
            '    pip install -U "huggingface_hub[cli]"'
        )

    dest = REPO_ROOT / folder_name

    if clean and dest.exists():
        print(f"[clean] removing existing {dest}")
        shutil.rmtree(dest)

    dest.mkdir(parents=True, exist_ok=True)
    print(f"[download] {repo_id} -> {dest}")

    # local_dir places the files directly under dest with no HF cache symlinks,
    # so the result is a plain folder identical to the original.
    snapshot_download(
        repo_id=repo_id,
        repo_type="dataset",
        local_dir=str(dest),
    )
    print(f"[done] {folder_name}")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument(
        "--only",
        choices=sorted(DATASETS),
        help="Download only this folder (default: both).",
    )
    p.add_argument(
        "--clean",
        action="store_true",
        help="Remove the destination folder before downloading.",
    )
    args = p.parse_args()

    targets = {args.only: DATASETS[args.only]} if args.only else DATASETS

    print(f"Repo root: {REPO_ROOT}")
    for folder_name, repo_id in targets.items():
        download_one(folder_name, repo_id, args.clean)

    print("\nAll requested datasets restored.")


if __name__ == "__main__":
    main()
