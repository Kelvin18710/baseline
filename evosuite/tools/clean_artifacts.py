#!/usr/bin/env python3
"""Clean generated artifacts for baseline/evosuite.

Default behavior (safe clean):
- remove run outputs under reports/
- remove generated complexity CSV under data/complexity
- remove per-project workspaces under cache/project_workspace
- remove local __pycache__ folders in evosuite tree

Use --all-cache to also remove dependency/source caches:
- cache/lib
- cache/project_archives
"""

import argparse
import shutil
from pathlib import Path
from typing import List

EVOSUITE_ROOT = Path(__file__).resolve().parents[1]


def rm_path(path: Path, dry_run: bool) -> bool:
    if not path.exists():
        return False
    if dry_run:
        print(f"[DRY] remove {path}")
        return True

    if path.is_dir():
        shutil.rmtree(path)
    else:
        path.unlink()
    print(f"[OK] removed {path}")
    return True


def ensure_dir(path: Path, dry_run: bool) -> None:
    if dry_run:
        return
    path.mkdir(parents=True, exist_ok=True)


def collect_targets(all_cache: bool) -> List[Path]:
    targets = [
        EVOSUITE_ROOT / "reports" / "batch",
        EVOSUITE_ROOT / "reports" / "method_coverage",
        EVOSUITE_ROOT / "data" / "complexity",
        EVOSUITE_ROOT / "cache" / "project_workspace",
        EVOSUITE_ROOT / "__pycache__",
        EVOSUITE_ROOT / "tools" / "__pycache__",
    ]
    if all_cache:
        targets.extend(
            [
                EVOSUITE_ROOT / "cache" / "lib",
                EVOSUITE_ROOT / "cache" / "project_archives",
            ]
        )
    return targets


def main() -> None:
    parser = argparse.ArgumentParser(description="Clean generated artifacts under baseline/evosuite")
    parser.add_argument("--dry-run", action="store_true", help="仅打印将删除的路径")
    parser.add_argument("--all-cache", action="store_true", help="额外清理 cache/lib 与 cache/project_archives")
    args = parser.parse_args()

    removed = 0
    for target in collect_targets(all_cache=args.all_cache):
        if rm_path(target, dry_run=args.dry_run):
            removed += 1

    # Recreate expected directory skeleton for next run.
    ensure_dir(EVOSUITE_ROOT / "reports", args.dry_run)
    ensure_dir(EVOSUITE_ROOT / "data", args.dry_run)
    ensure_dir(EVOSUITE_ROOT / "cache", args.dry_run)

    print("\n=== clean done ===")
    print("root:", EVOSUITE_ROOT)
    print("removed_paths:", removed)
    print("mode:", "dry-run" if args.dry_run else "apply")


if __name__ == "__main__":
    main()
