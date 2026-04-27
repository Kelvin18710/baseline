#!/usr/bin/env python3
"""Repair EvoSuite batch coverage CSV using existing artifacts.

Edit the config block below, then run:
    python3 dataset/repair_evosuite_coverage.py
"""

from __future__ import annotations

import csv
import sys
from collections import Counter
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple


# ------------------------- Config -------------------------

PROJECT = "Math"
INPUT_CSV = "evosuite/reports/batch/coverage/Math/Math_stable_coverage.csv"
OUTPUT_CSV = "dataset/outputs/Math_stable_coverage_repaired.csv"

# Usually enough to repair old buggy summaries without touching normal rows.
RECHECK_STATUSES = {
    "method-lines-missing",
    "coverage-missing",
}

# If True, recompute all rows that still have usable artifacts.
REWRITE_ALL_ROWS = False

# Preferred artifact columns in the input CSV.
REPORT_PATH_COLUMNS = ["artifact_report_path", "report_path"]
TESTS_PATH_COLUMNS = ["tests_path"]

# Isolated workspace suffix used only for javap / class preparation.
WORKDIR_SUFFIX = "repair_coverage"


# ------------------------- Imports -------------------------

REPO_ROOT = Path(__file__).resolve().parents[1]
TOOLS_DIR = REPO_ROOT / "evosuite" / "tools"
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

import run as runner  # noqa: E402


# ------------------------- Helpers -------------------------

def compute_method_coverage(
    coverage_map: Dict[int, Dict[str, int]],
    lines: Iterable[int],
) -> Tuple[Optional[float], Optional[float], Optional[float], int, int, int, int, int, int]:
    lines = list(sorted(set(lines)))
    fully_covered = 0
    partially_covered = 0
    missed = 0
    unknown = 0
    total_instr = 0
    covered_instr = 0
    total_branch = 0
    covered_branch = 0

    for line_no in lines:
        info = coverage_map.get(line_no)
        if not info:
            unknown += 1
            continue
        mi = info.get("mi", 0)
        ci = info.get("ci", 0)
        mb = info.get("mb", 0)
        cb = info.get("cb", 0)
        total_instr += mi + ci
        covered_instr += ci
        total_branch += mb + cb
        covered_branch += cb

        if ci > 0 and mi == 0:
            fully_covered += 1
        elif ci > 0 and mi > 0:
            partially_covered += 1
        elif ci == 0 and mi > 0:
            missed += 1
        else:
            unknown += 1

    known_total = len(lines) - unknown
    if known_total <= 0:
        return None, None, None, fully_covered + partially_covered, known_total, covered_instr, total_instr, covered_branch, total_branch

    line_covered = fully_covered + partially_covered
    line_ratio = (line_covered / float(known_total)) * 100.0
    instr_ratio = (covered_instr / float(total_instr) * 100.0) if total_instr > 0 else 0.0
    branch_ratio = (covered_branch / float(total_branch) * 100.0) if total_branch > 0 else 0.0
    return line_ratio, instr_ratio, branch_ratio, line_covered, known_total, covered_instr, total_instr, covered_branch, total_branch


def resolve_repo_path(path_str: str) -> Optional[Path]:
    s = (path_str or "").strip()
    if not s:
        return None

    candidates = []
    raw = Path(s)
    if raw.is_absolute():
        candidates.append(raw)
    else:
        candidates.append(REPO_ROOT / raw)
        candidates.append(raw)

    normalized = s.replace("\\", "/")
    for marker in ("evosuite/", "dataset/"):
        idx = normalized.find(marker)
        if idx != -1:
            candidates.append(REPO_ROOT / normalized[idx:])

    seen = set()
    for candidate in candidates:
        key = str(candidate)
        if key in seen:
            continue
        seen.add(key)
        if candidate.exists():
            return candidate
    return candidates[0] if candidates else None


def first_existing_path(row: Dict[str, str], columns: List[str]) -> Optional[Path]:
    for col in columns:
        p = resolve_repo_path(row.get(col, ""))
        if p and p.exists():
            return p
    return None


def build_method_filter(row: Dict[str, str]) -> str:
    method = (row.get("method") or "").strip()
    params = (row.get("params") or "").strip()
    if "(" in method:
        return method
    if params:
        return f"{method}({params})"
    return method


def should_recheck(row: Dict[str, str]) -> bool:
    if REWRITE_ALL_ROWS:
        return True
    status = (row.get("status") or "").strip()
    return status in RECHECK_STATUSES


def main() -> int:
    input_csv = REPO_ROOT / INPUT_CSV
    output_csv = REPO_ROOT / OUTPUT_CSV
    if not input_csv.exists():
        raise RuntimeError(f"Input CSV not found: {input_csv}")

    with input_csv.open("r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
        fieldnames = list(reader.fieldnames or [])

    if not rows:
        raise RuntimeError(f"No rows found in {input_csv}")

    workdir, _, _ = runner.prepare_stable_project(PROJECT, workdir_suffix=WORKDIR_SUFFIX)
    classes_dir = workdir / "classes"

    method_cache: Dict[str, List[Dict[str, object]]] = {}
    coverage_cache: Dict[Path, Dict[int, Dict[str, int]]] = {}

    updated_rows = []
    old_counter = Counter()
    new_counter = Counter()
    repaired = 0
    unresolved = 0

    extra_columns = ["repair_note", "repair_changed"]
    for col in extra_columns:
        if col not in fieldnames:
            fieldnames.append(col)

    for row in rows:
        old_counter[row.get("status", "")] += 1
        row = dict(row)
        row["repair_note"] = ""
        row["repair_changed"] = "0"

        if not should_recheck(row):
            updated_rows.append(row)
            new_counter[row.get("status", "")] += 1
            continue

        target_class = (row.get("class") or "").strip()
        method_filter = build_method_filter(row)
        if not target_class or not method_filter:
            row["repair_note"] = "missing-class-or-method"
            updated_rows.append(row)
            new_counter[row.get("status", "")] += 1
            unresolved += 1
            continue

        report_path = first_existing_path(row, REPORT_PATH_COLUMNS)
        if not report_path or not report_path.exists():
            row["repair_note"] = "report-not-found"
            updated_rows.append(row)
            new_counter[row.get("status", "")] += 1
            unresolved += 1
            continue

        try:
            if target_class not in method_cache:
                method_cache[target_class] = runner.parse_javap(runner.run_javap(classes_dir, target_class))
            methods = method_cache[target_class]

            if report_path not in coverage_cache:
                coverage_cache[report_path] = runner.load_line_coverage(report_path, target_class)
            coverage_map = coverage_cache[report_path]

            method_sig_filters = [method_filter] if "(" in method_filter else []
            method_name_filters = [method_filter] if "(" not in method_filter else []
            method_lines_map = runner.collect_method_lines(methods, method_name_filters, method_sig_filters)
            lines = method_lines_map.get(method_filter, set())

            if not lines:
                row["status"] = "method-lines-missing"
                row["repair_note"] = "method-lines-still-missing"
                updated_rows.append(row)
                new_counter[row.get("status", "")] += 1
                unresolved += 1
                continue

            line_ratio, instr_ratio, branch_ratio, lc_num, lc_den, ic_num, ic_den, bc_num, bc_den = compute_method_coverage(
                coverage_map, lines
            )

            row["line_cov_num"] = str(lc_num)
            row["line_cov_den"] = str(lc_den)
            row["instr_cov_num"] = str(ic_num)
            row["instr_cov_den"] = str(ic_den)
            row["branch_cov_num"] = str(bc_num)
            row["branch_cov_den"] = str(bc_den)

            if line_ratio is None:
                row["status"] = "coverage-missing"
                row["repair_note"] = "coverage-still-missing"
            else:
                row["status"] = "ok"
                row["line_cov"] = f"{line_ratio:.1f}"
                row["instr_cov"] = f"{instr_ratio:.1f}"
                row["branch_cov"] = f"{branch_ratio:.1f}"
                row["repair_note"] = "recomputed"

            tests_dir = first_existing_path(row, TESTS_PATH_COLUMNS)
            if tests_dir and tests_dir.exists():
                test_file = runner.find_evosuite_test_file(tests_dir, target_class)
                row["tests"] = str(runner.count_tests_in_file(test_file))
                row["calls"] = str(runner.count_method_calls_in_test(test_file, target_class, method_filter))

            row["repair_changed"] = "1"
            repaired += 1
        except Exception as exc:
            row["repair_note"] = f"repair-error:{exc}"
            unresolved += 1

        updated_rows.append(row)
        new_counter[row.get("status", "")] += 1

    output_csv.parent.mkdir(parents=True, exist_ok=True)
    with output_csv.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(updated_rows)

    print("input:", input_csv)
    print("output:", output_csv)
    print("old_status:", dict(old_counter))
    print("new_status:", dict(new_counter))
    print("repaired_rows:", repaired)
    print("unresolved_rows:", unresolved)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
