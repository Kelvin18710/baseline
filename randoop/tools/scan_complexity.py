#!/usr/bin/env python3
"""
Scan project source for cyclomatic complexity.

使用方式：
  python3 scan_complexity.py --project Lang [--threshold 2]
  
输出：
  data/complexity/<project>_stable_cc.csv (包含方法列表)
"""

import argparse
import csv
import subprocess
import sys
from pathlib import Path
from typing import List, Tuple

SCRIPT_DIR = Path(__file__).resolve().parent
RANDOOP_ROOT = SCRIPT_DIR.parent
DATA_DIR = RANDOOP_ROOT / "data"
CC_SCAN = SCRIPT_DIR / "cc_scan.py"

def run_cc_scan(src_dir: Path, threshold: int = 2) -> List[Tuple[str, str, int]]:
    """
    Run cc_scan.py on source directory.
    Returns list of (class_fqcn, method_name, cc_value).
    """
    if not CC_SCAN.exists():
        raise FileNotFoundError(f"cc_scan.py not found at {CC_SCAN}")
    
    output_csv = DATA_DIR / "complexity" / "_cc_scan_raw.csv"
    output_csv.parent.mkdir(parents=True, exist_ok=True)

    # Local tools/cc_scan.py uses "CC > threshold".
    # To preserve wrapper semantics "CC >= threshold", pass threshold-1.
    raw_threshold = max(0, threshold - 1)
    cmd = [
        "python3", str(CC_SCAN),
        "--root", str(src_dir),
        "--out", str(output_csv),
        "--threshold", str(raw_threshold),
    ]
    
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"cc_scan.py failed: {result.stderr}")
    
    # Parse output CSV from cc_scan.py
    methods = []
    if not output_csv.exists():
        raise RuntimeError(f"cc_scan output not found: {output_csv}")

    with output_csv.open("r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                class_fqcn = (row.get("class_guess") or "").strip()
                method_name = (row.get("method") or "").strip()
                cc = int(row.get("cc") or 0)
                if class_fqcn and method_name and cc >= threshold:
                    methods.append((class_fqcn, method_name, cc))
            except Exception:
                continue
    
    return methods


def get_project_src(project: str) -> Path:
    """
    Get source directory for project (from stable Maven or workspace).
    """
    workspace = RANDOOP_ROOT / "cache" / "project_workspace" / project
    src_dir = workspace / "src"
    
    if src_dir.exists():
        return src_dir

    # Bootstrap workspace from stable Maven coordinates.
    try:
        from run import prepare_stable_project
        print(f"[i] Source not found for {project}, bootstrapping from stable Maven...")
        prepare_stable_project(project, workspace)
    except Exception as e:
        raise FileNotFoundError(f"Source directory not found for {project}: {e}")

    if src_dir.exists():
        return src_dir
    raise FileNotFoundError(f"Source directory not found for {project} after bootstrap")


def main():
    parser = argparse.ArgumentParser(description="Scan cyclomatic complexity")
    parser.add_argument("--project", default="Lang", help="Project name")
    parser.add_argument("--threshold", type=int, default=2, help="CC threshold")
    
    args = parser.parse_args()
    
    project = args.project
    threshold = args.threshold
    
    print(f"[i] Scanning {project} for CC >= {threshold}...")
    
    # Get source directory (may need to download first)
    try:
        src_dir = get_project_src(project)
    except FileNotFoundError as e:
        print(f"[-] {e}")
        sys.exit(1)
    
    # Run cc_scan
    try:
        methods = run_cc_scan(src_dir, threshold)
    except Exception as e:
        print(f"[-] Error: {e}")
        sys.exit(1)
    
    if not methods:
        print(f"[-] No methods found with CC >= {threshold}")
        sys.exit(1)
    
    print(f"[+] Found {len(methods)} methods")
    
    # Write CSV
    output_dir = DATA_DIR / "complexity"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_csv = output_dir / f"{project}_stable_cc.csv"
    
    with open(output_csv, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["class_fqcn", "method_name", "cc"])
        for class_fqcn, method_name, cc in sorted(methods):
            writer.writerow([class_fqcn, method_name, cc])
    
    print(f"[+] CC CSV saved to {output_csv}")
    
    # Summary
    cc_values = [cc for _, _, cc in methods]
    print(f"[i] CC range: {min(cc_values)}-{max(cc_values)}, avg={sum(cc_values)/len(cc_values):.1f}")


if __name__ == "__main__":
    main()
