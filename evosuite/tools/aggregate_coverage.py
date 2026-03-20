#!/usr/bin/env python3
"""Aggregate coverage using total line/instruction/branch counts across methods.
python3 aggregate_coverage.py --project Lang

"""
import argparse
import csv
import sys
from pathlib import Path
from typing import Dict, Iterable, Optional, Tuple

EVOSUITE_ROOT = Path(__file__).resolve().parents[1]
import run as runner  # noqa: E402


def load_summary_rows(summary_csv: Path) -> list:
    rows = []
    with summary_csv.open("r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(row)
    return rows


def compute_method_coverage(
    coverage_map: Dict[int, Dict[str, int]],
    lines: Iterable[int],
) -> Tuple[int, int, int, int, int, int]:
    fully_covered = 0
    partially_covered = 0
    missed = 0
    unknown = 0
    total_instr = 0
    covered_instr = 0
    total_branch = 0
    covered_branch = 0

    for line_no in sorted(lines):
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

    total_lines = len(list(lines))
    known_total = total_lines - unknown
    covered_lines = fully_covered + partially_covered
    return covered_lines, known_total, covered_instr, total_instr, covered_branch, total_branch


def pick_report_path(row: dict) -> Optional[Path]:
    for key in ("artifact_report_path", "report_path"):
        value = row.get(key)
        if value:
            path = Path(value)
            if path.exists():
                return path
    return None


def parse_nonneg_int(row: dict, key: str) -> Optional[int]:
    value = (row.get(key) or "").strip()
    if value == "":
        return None
    try:
        n = int(value)
    except Exception:
        return None
    return n if n >= 0 else None


def main() -> None:
    print("[DEBUG] main() started")
    parser = argparse.ArgumentParser(description="Aggregate coverage using total line/instruction/branch counts")
    parser.add_argument("--project", default="Lang", help="项目名")
    parser.add_argument(
        "--csv",
        default=None,
        help="覆盖率 CSV 路径（默认 reports/batch/coverage/<Project>/<Project>_stable_coverage.csv）",
    )
    parser.add_argument("--out", default=None, help="输出结果 CSV（可选）")
    args = parser.parse_args()

    default_csv = EVOSUITE_ROOT / "reports" / "batch" / "coverage" / args.project / f"{args.project}_stable_coverage.csv"
    csv_path = Path(args.csv) if args.csv else default_csv
    print(f"[DEBUG] Using CSV: {csv_path}")
    if not csv_path.exists():
        print(f"[ERROR] Coverage CSV not found: {csv_path}")
        return

    rows = load_summary_rows(csv_path)
    print(f"[DEBUG] Loaded {len(rows)} rows from CSV")
    if not rows:
        print("[WARN] No rows found.")
        return

    workdir, _, _ = runner.prepare_stable_project(args.project)
    print(f"[DEBUG] workdir: {workdir}")
    classes_dir = workdir / "classes"
    print(f"[DEBUG] classes_dir: {classes_dir}")

    total_covered_lines = 0
    total_known_lines = 0
    total_covered_instr = 0
    total_instr = 0
    total_covered_branch = 0
    total_branch = 0
    skipped = 0

    for row in rows:
        lc_num = parse_nonneg_int(row, "line_cov_num")
        lc_den = parse_nonneg_int(row, "line_cov_den")
        ic_num = parse_nonneg_int(row, "instr_cov_num")
        ic_den = parse_nonneg_int(row, "instr_cov_den")
        bc_num = parse_nonneg_int(row, "branch_cov_num")
        bc_den = parse_nonneg_int(row, "branch_cov_den")

        if None not in (lc_num, lc_den, ic_num, ic_den, bc_num, bc_den):
            total_covered_lines += lc_num
            total_known_lines += lc_den
            total_covered_instr += ic_num
            total_instr += ic_den
            total_covered_branch += bc_num
            total_branch += bc_den
            continue

        target_class = row.get("class") or row.get("class_guess") or ""
        target_method = row.get("method") or ""
        if not target_class or not target_method:
            skipped += 1
            continue

        report_path = pick_report_path(row)
        if not report_path:
            skipped += 1
            continue

        try:
            coverage_map = runner.load_line_coverage(report_path, target_class)
            methods = runner.parse_javap(runner.run_javap(classes_dir, target_class))
            method_names = [runner.method_name_from_filter(target_method)]
            method_lines_map = runner.collect_method_lines(methods, method_names, [])
            lines = method_lines_map.get(method_names[0], set())
            if not lines:
                skipped += 1
                continue

            covered_lines, known_lines, covered_instr, total_instr_local, covered_branch, total_branch_local = compute_method_coverage(
                coverage_map, lines
            )
            total_covered_lines += covered_lines
            total_known_lines += known_lines
            total_covered_instr += covered_instr
            total_instr += total_instr_local
            total_covered_branch += covered_branch
            total_branch += total_branch_local
        except Exception as e:
            print(f"[SKIP] {target_class}#{target_method}: {e}")
            skipped += 1

    line_ratio = (total_covered_lines / float(total_known_lines) * 100.0) if total_known_lines > 0 else 0.0
    instr_ratio = (total_covered_instr / float(total_instr) * 100.0) if total_instr > 0 else 0.0
    branch_ratio = (total_covered_branch / float(total_branch) * 100.0) if total_branch > 0 else 0.0

    print("=== aggregate coverage (weighted by total counts) ===")
    print("project:", args.project)
    print("methods:", len(rows), "skipped:", skipped)
    print("line coverage: {0:.1f}% ({1}/{2})".format(line_ratio, total_covered_lines, total_known_lines))
    print("instruction coverage: {0:.1f}% ({1}/{2})".format(instr_ratio, total_covered_instr, total_instr))
    print("branch coverage: {0:.1f}% ({1}/{2})".format(branch_ratio, total_covered_branch, total_branch))

    if args.out:
        out_path = Path(args.out).resolve()
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with out_path.open("w", encoding="utf-8", newline="") as f:
            writer = csv.writer(f)
            for row in rows:
                target_class = row.get("class") or row.get("class_guess") or ""
                target_method = row.get("method") or ""
                if not target_class or not target_method:
                    print(f"[SKIP] 缺class或method: class='{target_class}' method='{target_method}'")
                    skipped += 1
                    continue

                report_path = pick_report_path(row)
                if not report_path:
                    print(f"[SKIP] 找不到report路径: class='{target_class}' method='{target_method}'")
                    skipped += 1
                    continue

                try:
                    coverage_map = runner.load_line_coverage(report_path, target_class)
                    methods = runner.parse_javap(runner.run_javap(classes_dir, target_class))
                    method_names = [runner.method_name_from_filter(target_method)]
                    method_lines_map = runner.collect_method_lines(methods, method_names, [])
                    lines = method_lines_map.get(method_names[0], set())
                    if not lines:
                        print(f"[SKIP] 方法找不到代码行: class='{target_class}' method='{target_method}'")
                        skipped += 1
                        continue

                    covered_lines, known_lines, covered_instr, total_instr_local, covered_branch, total_branch_local = compute_method_coverage(
                        coverage_map, lines
                    )
                    total_covered_lines += covered_lines
                    total_known_lines += known_lines
                    total_covered_instr += covered_instr
                    total_instr += total_instr_local
                    total_covered_branch += covered_branch
                    total_branch += total_branch_local
                except Exception as e:
                    print(f"[SKIP] 处理异常: class='{target_class}' method='{target_method}' error={e}")
                    skipped += 1
if __name__ == "__main__":
    main()