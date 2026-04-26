#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
整理 EvoSuite 在指定方法池上的覆盖结果。

当前默认配置：
- 项目: lang3.20
- 访问等级: 不限制
- 圈复杂度: CC > 2
- 覆盖率结果: dataset/evosuite_result/Lang_stable_coverage.csv

运行方式：
    python3 dataset/analyze_evosuite_coverage.py
"""

from __future__ import annotations

import csv
import json
from contextlib import contextmanager
from pathlib import Path
from typing import Dict, Iterable, List, Tuple

import analyze_methods


BASE_DIR = Path(__file__).resolve().parent


CONFIG = {
    "project_key": "lang3.20",
    "cc_strict_gt": 2,
    "access_levels": [],
    "include_constructors": True,
    "coverage_csv": BASE_DIR / "evosuite_result" / "Lang_stable_coverage.csv",
    "output_dir": BASE_DIR / "evosuite_result" / "processed",
    "full_coverage_metrics": ["line", "instr", "branch"],
    "treat_zero_denominator_as_full": True,
    "require_status_ok": True,
}


def parse_method_fen(method_fen: str) -> Tuple[str, str, str]:
    text = method_fen.strip()
    paren_idx = text.find("(")
    if paren_idx == -1:
        head = text
        params = ""
    else:
        head = text[:paren_idx]
        params = text[paren_idx + 1:text.rfind(")")]
    class_name, method_name = head.rsplit(".", 1)
    return class_name, method_name, params


@contextmanager
def patched_analyze_config() -> Iterable[None]:
    backup = {
        "active_project": analyze_methods.CONFIG["active_project"],
        "min_cc": analyze_methods.CONFIG["min_cc"],
        "access_levels": list(analyze_methods.CONFIG["access_levels"]),
        "include_constructors": analyze_methods.CONFIG["include_constructors"],
    }
    analyze_methods.CONFIG["active_project"] = CONFIG["project_key"]
    analyze_methods.CONFIG["min_cc"] = int(CONFIG["cc_strict_gt"]) + 1
    analyze_methods.CONFIG["access_levels"] = list(CONFIG["access_levels"])
    analyze_methods.CONFIG["include_constructors"] = bool(CONFIG["include_constructors"])
    try:
        yield
    finally:
        analyze_methods.CONFIG["active_project"] = backup["active_project"]
        analyze_methods.CONFIG["min_cc"] = backup["min_cc"]
        analyze_methods.CONFIG["access_levels"] = backup["access_levels"]
        analyze_methods.CONFIG["include_constructors"] = backup["include_constructors"]


def load_method_pool() -> Dict[str, object]:
    with patched_analyze_config():
        result = analyze_methods.analyze_project(str(CONFIG["project_key"]))

    filtered_rows = [row for row in result["rows"] if int(row["cc"]) > int(CONFIG["cc_strict_gt"])]
    filtered_rows.sort(key=lambda row: (-int(row["cc"]), str(row["method_fen"])))

    result = dict(result)
    result["rows"] = filtered_rows
    result["matched_methods"] = len(filtered_rows)
    return result


def load_coverage_rows() -> List[Dict[str, str]]:
    coverage_csv = Path(CONFIG["coverage_csv"]).resolve()
    if not coverage_csv.exists():
        raise RuntimeError("coverage csv not found: {0}".format(coverage_csv))

    with coverage_csv.open("r", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    return rows


def metric_is_full(row: Dict[str, str], metric: str) -> bool:
    num = int(row.get("{0}_cov_num".format(metric), "0") or "0")
    den = int(row.get("{0}_cov_den".format(metric), "0") or "0")
    if den == 0:
        return bool(CONFIG["treat_zero_denominator_as_full"])
    return num == den


def metric_summary(row: Dict[str, str], metric: str) -> str:
    num = row.get("{0}_cov_num".format(metric), "")
    den = row.get("{0}_cov_den".format(metric), "")
    pct = row.get("{0}_cov".format(metric), "")
    return "{0}% ({1}/{2})".format(pct, num, den)


def coverage_key_from_pool_row(row: Dict[str, object]) -> Tuple[str, str, str]:
    class_name, method_name, params = parse_method_fen(str(row["method_fen"]))
    return class_name, method_name, params


def coverage_key_from_coverage_row(row: Dict[str, str]) -> Tuple[str, str, str]:
    class_name = (row.get("class") or "").strip()
    method_name = (row.get("method") or "").strip()
    params_types = analyze_methods.params_to_types((row.get("params") or "").strip())
    return class_name, method_name, params_types


def choose_coverage_row(rows: List[Dict[str, str]]) -> Dict[str, str]:
    def sort_key(row: Dict[str, str]) -> Tuple[int, int]:
        status_ok = 0 if row.get("status") == "ok" else 1
        start_line = int(row.get("start_line", "0") or "0")
        return status_ok, start_line

    return sorted(rows, key=sort_key)[0]


def build_coverage_index(rows: List[Dict[str, str]]) -> Dict[Tuple[str, str, str], List[Dict[str, str]]]:
    index: Dict[Tuple[str, str, str], List[Dict[str, str]]] = {}
    for row in rows:
        key = coverage_key_from_coverage_row(row)
        index.setdefault(key, []).append(row)
    return index


def analyze_not_full_coverage(
    method_pool_rows: List[Dict[str, object]],
    coverage_rows: List[Dict[str, str]],
) -> Dict[str, object]:
    coverage_index = build_coverage_index(coverage_rows)

    not_full_rows: List[Dict[str, object]] = []
    full_rows = 0
    missing_rows = 0
    matched_rows = 0

    for pool_row in method_pool_rows:
        key = coverage_key_from_pool_row(pool_row)
        matched = coverage_index.get(key, [])

        class_name, method_name, params_types = key
        base_record = {
            "project": pool_row["project"],
            "access": pool_row["access"],
            "cc": pool_row["cc"],
            "is_constructor": pool_row["is_constructor"],
            "method_fen": pool_row["method_fen"],
            "class_name": class_name,
            "method_name": method_name,
            "params_types": params_types,
            "file": pool_row["file"],
            "line_number": pool_row["line_number"],
        }

        if not matched:
            missing_rows += 1
            record = dict(base_record)
            record.update(
                {
                    "coverage_status": "missing",
                    "full_coverage": False,
                    "not_full_reasons": "missing_coverage_row",
                    "line_cov_summary": "",
                    "instr_cov_summary": "",
                    "branch_cov_summary": "",
                    "tests": "",
                    "calls": "",
                }
            )
            not_full_rows.append(record)
            continue

        matched_rows += 1
        chosen = choose_coverage_row(matched)
        reasons: List[str] = []

        if CONFIG["require_status_ok"] and chosen.get("status") != "ok":
            reasons.append("status={0}".format(chosen.get("status", "")))

        for metric in CONFIG["full_coverage_metrics"]:
            if not metric_is_full(chosen, metric):
                reasons.append("{0}_not_full".format(metric))

        is_full = not reasons
        if is_full:
            full_rows += 1
            continue

        record = dict(base_record)
        record.update(
            {
                "coverage_status": chosen.get("status", ""),
                "full_coverage": False,
                "not_full_reasons": ";".join(reasons),
                "line_cov_summary": metric_summary(chosen, "line"),
                "instr_cov_summary": metric_summary(chosen, "instr"),
                "branch_cov_summary": metric_summary(chosen, "branch"),
                "tests": chosen.get("tests", ""),
                "calls": chosen.get("calls", ""),
            }
        )
        not_full_rows.append(record)

    not_full_rows.sort(key=lambda row: (-int(row["cc"]), str(row["method_fen"])))
    return {
        "not_full_rows": not_full_rows,
        "matched_rows": matched_rows,
        "missing_rows": missing_rows,
        "full_rows": full_rows,
        "coverage_total_rows": len(coverage_rows),
        "coverage_unmatched_rows": len(coverage_rows) - matched_rows,
    }


def write_csv(path: Path, rows: List[Dict[str, object]], fieldnames: List[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def main() -> None:
    method_pool = load_method_pool()
    coverage_rows = load_coverage_rows()
    analysis = analyze_not_full_coverage(method_pool["rows"], coverage_rows)

    output_dir = Path(CONFIG["output_dir"]).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    project_key = str(CONFIG["project_key"])
    cc_label = "cc_gt_{0}".format(CONFIG["cc_strict_gt"])
    pool_csv = output_dir / "{0}_{1}_all_access_methods.csv".format(project_key, cc_label)
    not_full_csv = output_dir / "{0}_{1}_evosuite_not_full_coverage.csv".format(project_key, cc_label)
    summary_json = output_dir / "{0}_{1}_evosuite_not_full_summary.json".format(project_key, cc_label)

    pool_rows = []
    for row in method_pool["rows"]:
        pool_rows.append(
            {
                "project": row["project"],
                "access": row["access"],
                "cc": row["cc"],
                "is_constructor": row["is_constructor"],
                "method_fen": row["method_fen"],
                "class_name_guess": row["class_name_guess"],
                "method_name": row["method_name"],
                "params_types": row["params_types"],
                "file": row["file"],
                "line_number": row["line_number"],
            }
        )

    write_csv(
        pool_csv,
        pool_rows,
        [
            "project",
            "access",
            "cc",
            "is_constructor",
            "method_fen",
            "class_name_guess",
            "method_name",
            "params_types",
            "file",
            "line_number",
        ],
    )

    write_csv(
        not_full_csv,
        analysis["not_full_rows"],
        [
            "project",
            "access",
            "cc",
            "is_constructor",
            "method_fen",
            "class_name",
            "method_name",
            "params_types",
            "file",
            "line_number",
            "coverage_status",
            "full_coverage",
            "not_full_reasons",
            "line_cov_summary",
            "instr_cov_summary",
            "branch_cov_summary",
            "tests",
            "calls",
        ],
    )

    summary = {
        "project_key": project_key,
        "cc_strict_gt": CONFIG["cc_strict_gt"],
        "access_levels": CONFIG["access_levels"],
        "include_constructors": CONFIG["include_constructors"],
        "method_pool_count": len(method_pool["rows"]),
        "coverage_total_rows": analysis["coverage_total_rows"],
        "matched_coverage_rows": analysis["matched_rows"],
        "missing_coverage_rows": analysis["missing_rows"],
        "coverage_unmatched_rows": analysis["coverage_unmatched_rows"],
        "fully_covered_methods": analysis["full_rows"],
        "not_fully_covered_methods": len(analysis["not_full_rows"]),
        "coverage_csv": str(Path(CONFIG["coverage_csv"]).resolve()),
        "method_pool_csv": str(pool_csv),
        "not_full_csv": str(not_full_csv),
    }
    summary_json.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")

    print("=== EvoSuite 覆盖整理完成 ===")
    print("project_key:", project_key)
    print("cc filter: > {0}".format(CONFIG["cc_strict_gt"]))
    print("access_levels:", ", ".join(CONFIG["access_levels"]) or "all")
    print("method_pool_count:", len(method_pool["rows"]))
    print("coverage_total_rows:", analysis["coverage_total_rows"])
    print("matched_coverage_rows:", analysis["matched_rows"])
    print("missing_coverage_rows:", analysis["missing_rows"])
    print("coverage_unmatched_rows:", analysis["coverage_unmatched_rows"])
    print("fully_covered_methods:", analysis["full_rows"])
    print("not_fully_covered_methods:", len(analysis["not_full_rows"]))
    print("method_pool_csv:", pool_csv)
    print("not_full_csv:", not_full_csv)
    print("summary_json:", summary_json)


if __name__ == "__main__":
    main()
