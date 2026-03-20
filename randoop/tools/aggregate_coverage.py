#!/usr/bin/env python3
"""
Aggregate coverage results from batch runs.

使用方式：
  python3 aggregate_coverage.py --project Lang
  
从 reports/batch/coverage_<project>.csv 读取，计算总体统计。
"""

import argparse
import csv
import sys
from pathlib import Path
from typing import Dict, Tuple, Optional

SCRIPT_DIR = Path(__file__).resolve().parent
RANDOOP_ROOT = SCRIPT_DIR.parent
BATCH_DIR = RANDOOP_ROOT / "reports" / "batch"


def parse_nonneg_int(s: str) -> int:
    """Parse non-negative integer from string."""
    try:
        v = int(s)
        return max(0, v)
    except (ValueError, TypeError):
        return 0


def aggregate_coverage_csv(csv_path: Path) -> Tuple[float, float, float, Dict[str, Tuple[int, int]]]:
    """
    Aggregate coverage from CSV with 分子/分母 fields.
    
    Expected CSV columns:
      class_fqcn, method_name,
      line_cov, instr_cov, branch_cov,  (percentages)
      line_cov_num, line_cov_den,
      instr_cov_num, instr_cov_den,
      branch_cov_num, branch_cov_den
    
    Returns (line_pct, instr_pct, branch_pct, breakdown)
    """
    if not csv_path.exists():
        print(f"[-] File not found: {csv_path}")
        return 0.0, 0.0, 0.0, {}
    
    totals = {
        "line": [0, 0],      # [numerator, denominator]
        "instr": [0, 0],
        "branch": [0, 0],
    }
    
    with open(csv_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames is None:
            print("[-] Empty CSV file")
            return 0.0, 0.0, 0.0, {}
        
        for row in reader:
            try:
                # Try CSV field approach first (fast path)
                if "line_cov_num" in row and "line_cov_den" in row:
                    line_num = parse_nonneg_int(row.get("line_cov_num", "0"))
                    line_den = parse_nonneg_int(row.get("line_cov_den", "0"))
                    instr_num = parse_nonneg_int(row.get("instr_cov_num", "0"))
                    instr_den = parse_nonneg_int(row.get("instr_cov_den", "0"))
                    branch_num = parse_nonneg_int(row.get("branch_cov_num", "0"))
                    branch_den = parse_nonneg_int(row.get("branch_cov_den", "0"))
                else:
                    # Fallback: use percentages (less accurate for aggregation)
                    line_num = int(float(row.get("line_cov", "0")) * 100)
                    line_den = 10000
                    instr_num = int(float(row.get("instr_cov", "0")) * 100)
                    instr_den = 10000
                    branch_num = int(float(row.get("branch_cov", "0")) * 100)
                    branch_den = 10000
                
                totals["line"][0] += line_num
                totals["line"][1] += line_den
                totals["instr"][0] += instr_num
                totals["instr"][1] += instr_den
                totals["branch"][0] += branch_num
                totals["branch"][1] += branch_den
            
            except Exception as e:
                print(f"[!] Error parsing row: {e}")
                continue
    
    # Calculate percentages
    line_pct = 100.0 * totals["line"][0] / totals["line"][1] if totals["line"][1] > 0 else 0.0
    instr_pct = 100.0 * totals["instr"][0] / totals["instr"][1] if totals["instr"][1] > 0 else 0.0
    branch_pct = 100.0 * totals["branch"][0] / totals["branch"][1] if totals["branch"][1] > 0 else 0.0
    
    breakdown = {
        "line": tuple(totals["line"]),
        "instr": tuple(totals["instr"]),
        "branch": tuple(totals["branch"]),
    }
    
    return line_pct, instr_pct, branch_pct, breakdown


def main():
    parser = argparse.ArgumentParser(description="Aggregate Randoop coverage results")
    parser.add_argument("--project", default="Lang", help="Project name")
    
    args = parser.parse_args()
    project = args.project
    
    csv_path = BATCH_DIR / f"coverage_{project}.csv"
    
    print(f"[i] Aggregating from {csv_path}...")
    
    line_pct, instr_pct, branch_pct, breakdown = aggregate_coverage_csv(csv_path)
    
    print("\n" + "="*60)
    print(f"Aggregate coverage for {project}:")
    print("="*60)
    
    for metric in ["line", "instr", "branch"]:
        num, den = breakdown[metric]
        pcts = [line_pct, instr_pct, branch_pct]
        metric_idx = ["line", "instr", "branch"].index(metric)
        pct = pcts[metric_idx]
        print(f"  {metric:8s}: {num:6d}/{den:6d} ({pct:6.2f}%)")
    
    print("="*60)


if __name__ == "__main__":
    main()
