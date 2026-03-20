#!/usr/bin/env python3
"""
Clean up artifacts and cache.

使用方式：
  python3 clean_artifacts.py [--dry-run] [--all-cache]
  
选项：
  --dry-run:    Preview what will be deleted (don't actually delete)
    --all-cache:  Also delete cache/lib and shared project archives (offline assets)
"""

import argparse
import shutil
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
RANDOOP_ROOT = SCRIPT_DIR.parent
BASELINE_ROOT = RANDOOP_ROOT.parent


def list_paths(paths: list, dry_run: bool = False):
    """List paths to be deleted."""
    total_size = 0
    for p in paths:
        if not p.exists():
            continue
        
        if p.is_file():
            size = p.stat().st_size
            total_size += size
            print(f"  {p} ({size} bytes)")
        else:
            size = sum(f.stat().st_size for f in p.rglob("*") if f.is_file())
            total_size += size
            print(f"  {p}/ ({size} bytes)")
    
    print(f"\nTotal size to be deleted: {total_size / (1024*1024):.1f} MB")
    
    if not dry_run:
        return total_size
    return 0


def clean_paths(paths: list, dry_run: bool = False):
    """Delete specified paths."""
    for p in paths:
        if not p.exists():
            continue
        
        try:
            if p.is_file():
                p.unlink()
                if not dry_run:
                    print(f"[DEL] {p}")
            else:
                shutil.rmtree(p)
                if not dry_run:
                    print(f"[DEL] {p}/")
        except Exception as e:
            print(f"[-] Error deleting {p}: {e}", file=sys.stderr)


def main():
    parser = argparse.ArgumentParser(description="Clean up artifacts")
    parser.add_argument("--dry-run", action="store_true", help="Preview without deleting")
    parser.add_argument("--all-cache", action="store_true", help="Also delete offline assets")
    
    args = parser.parse_args()
    dry_run = args.dry_run
    all_cache = args.all_cache
    
    print("Paths to clean:")
    
    # Default cleanup
    paths = [
        RANDOOP_ROOT / "reports" / "batch",
        RANDOOP_ROOT / "reports" / "method_coverage",
        RANDOOP_ROOT / "data" / "complexity",
        RANDOOP_ROOT / "cache" / "project_workspace",
    ]
    
    # Optional full cache cleanup
    if all_cache:
        paths.extend([
            RANDOOP_ROOT / "cache" / "lib",
            RANDOOP_ROOT / "lib",
            BASELINE_ROOT / "shared_project_packages" / "project_archives",
        ])
    
    # List what will be deleted
    list_paths(paths, dry_run)
    
    if dry_run:
        print("\n[DRY-RUN] Use without --dry-run to actually delete")
        sys.exit(0)
    
    # Confirm deletion
    response = input("\nDelete? (yes/no): ").strip().lower()
    if response not in ["yes", "y"]:
        print("[CANCEL] No files deleted")
        sys.exit(0)
    
    # Perform deletion
    print("\nDeleting...")
    clean_paths(paths, dry_run)
    
    print("[+] Cleanup complete")


if __name__ == "__main__":
    main()
