#!/usr/bin/env python3
"""
Batch Randoop coverage measurement (class-once generation, method-level stats).

Key behavior:
- Group methods by class.
- Generate Randoop tests once per class.
- Reuse generated tests and filter per target method.
- Compute method-level coverage via javap line mapping + JaCoCo line counters.
"""

import argparse
import csv
import os
import shutil
import sys
import time
from collections import OrderedDict
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import run as runner  # same folder import

SCRIPT_DIR = Path(__file__).resolve().parent
RANDOOP_ROOT = SCRIPT_DIR.parent
DATA_DIR = RANDOOP_ROOT / "data"
REPORTS_DIR = RANDOOP_ROOT / "reports"
BATCH_DIR = REPORTS_DIR / "batch"


def slugify(text: str) -> str:
    out = []
    for ch in text:
        if ch.isalnum():
            out.append(ch)
        else:
            out.append("_")
    slug = "".join(out).strip("_")
    return slug[:160] if len(slug) > 160 else slug


def find_complexity_csv(project: str) -> Path:
    candidates = [
        DATA_DIR / "complexity" / f"{project}_stable_cc.csv",
        DATA_DIR / "complexity" / f"{project}_cc.csv",
    ]
    for p in candidates:
        if p.exists():
            return p
    raise FileNotFoundError(f"No CC CSV found for {project}")


def read_methods_from_cc_csv(cc_csv: Path) -> List[Tuple[str, str]]:
    methods: List[Tuple[str, str]] = []
    seen = set()
    with cc_csv.open("r", encoding="utf-8") as f:
        reader = csv.reader(f)
        _ = next(reader, None)
        for row in reader:
            if len(row) < 2:
                continue
            class_fqcn = row[0].strip()
            method_name = row[1].strip()
            if not class_fqcn or not method_name:
                continue
            if method_name[0].isupper():
                continue
            key = (class_fqcn, method_name)
            if key in seen:
                continue
            seen.add(key)
            methods.append(key)
    return methods


def write_summary_row(summary_path: Path, header: List[str], row: Dict[str, str]) -> None:
    exists = summary_path.exists()
    with summary_path.open("a", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=header)
        if not exists:
            writer.writeheader()
        writer.writerow(row)


def compute_method_coverage(coverage: Dict[str, Tuple[int, int]]) -> Tuple[float, float, float, int, int, int, int, int, int]:
    line_cov, line_den = coverage.get("line", (0, 0))
    instr_cov, instr_den = coverage.get("instr", (0, 0))
    branch_cov, branch_den = coverage.get("branch", (0, 0))

    line_pct = 100.0 * line_cov / line_den if line_den > 0 else 0.0
    instr_pct = 100.0 * instr_cov / instr_den if instr_den > 0 else 0.0
    branch_pct = 100.0 * branch_cov / branch_den if branch_den > 0 else 0.0

    return (
        line_pct, instr_pct, branch_pct,
        line_cov, line_den,
        instr_cov, instr_den,
        branch_cov, branch_den,
    )


def copy_artifacts(workdir: Path, dest_dir: Path) -> Tuple[str, str, str]:
    tests_dir = workdir / "randoop-tests" / "src"
    report_dir = workdir / "jacoco-report"
    exec_file = workdir / "jacoco.exec"

    tests_dest = dest_dir / "tests"
    report_dest = dest_dir / "jacoco-report"
    exec_dest = dest_dir / "jacoco.exec"

    if tests_dir.exists():
        if tests_dest.exists():
            shutil.rmtree(tests_dest)
        shutil.copytree(tests_dir, tests_dest)
    if report_dir.exists():
        if report_dest.exists():
            shutil.rmtree(report_dest)
        shutil.copytree(report_dir, report_dest)
    if exec_file.exists():
        shutil.copy2(exec_file, exec_dest)

    return str(tests_dest), str(report_dest / "jacoco.xml"), str(exec_dest)


def group_by_class(methods: List[Tuple[str, str]]) -> "OrderedDict[str, List[str]]":
    grouped: "OrderedDict[str, List[str]]" = OrderedDict()
    for cls, m in methods:
        grouped.setdefault(cls, []).append(m)
    return grouped


def main() -> None:
    parser = argparse.ArgumentParser(description="Batch Randoop coverage measurement")
    parser.add_argument("--project", default="Lang", help="Project name")
    parser.add_argument("--time-limit", type=int, default=0, help="Randoop time budget per class; <=0 uses Randoop default")
    parser.add_argument("--max-methods", type=int, default=None, help="Max methods to process")
    parser.add_argument("--start-index", type=int, default=0, help="Start index for resume")
    parser.add_argument("--workers", type=int, default=1, help="Total workers")
    parser.add_argument("--worker-id", type=int, default=0, help="Worker id in [0, workers-1]")
    parser.add_argument("--out-dir", default=str(BATCH_DIR / "coverage"), help="Summary output directory")
    parser.add_argument("--log-dir", default=str(BATCH_DIR / "logs"), help="Method log directory")
    parser.add_argument("--artifact-dir", default=str(BATCH_DIR / "artifacts"), help="Artifact output directory")
    parser.add_argument("--no-artifacts", action="store_true", help="Do not save tests/jacoco artifacts")
    args = parser.parse_args()

    if args.workers < 1:
        raise RuntimeError("--workers must be >= 1")
    if args.worker_id < 0 or args.worker_id >= args.workers:
        raise RuntimeError("--worker-id must be in [0, workers-1]")

    project = args.project
    save_artifacts = not args.no_artifacts

    cc_csv = find_complexity_csv(project)
    print(f"[i] Using CC CSV: {cc_csv}")

    methods = read_methods_from_cc_csv(cc_csv)
    if not methods:
        print("[-] No methods to process")
        sys.exit(1)

    selected: List[Tuple[int, Tuple[str, str]]] = []
    for idx, pair in enumerate(methods):
        if idx < args.start_index:
            continue
        if args.workers > 1 and (idx % args.workers) != args.worker_id:
            continue
        selected.append((idx, pair))

    if args.max_methods is not None:
        selected = selected[:args.max_methods]

    if not selected:
        print("[-] No methods selected after filters")
        sys.exit(1)

    out_dir = (Path(args.out_dir).resolve() / project)
    out_dir.mkdir(parents=True, exist_ok=True)
    log_dir = (Path(args.log_dir).resolve() / project)
    log_dir.mkdir(parents=True, exist_ok=True)
    artifact_dir = (Path(args.artifact_dir).resolve() / project)
    artifact_dir.mkdir(parents=True, exist_ok=True)

    summary_path = out_dir / f"{project}_stable_coverage.csv"
    legacy_csv = BATCH_DIR / f"coverage_{project}.csv"

    # Fresh run resets outputs; resume/parallel shards keep append behavior.
    if args.start_index == 0 and args.worker_id == 0:
        summary_path.unlink(missing_ok=True)
        legacy_csv.unlink(missing_ok=True)

    header = [
        "project", "class", "method", "status",
        "line_cov", "instr_cov", "branch_cov",
        "line_cov_num", "line_cov_den",
        "instr_cov_num", "instr_cov_den",
        "branch_cov_num", "branch_cov_den",
        "log_path", "tests_path", "artifact_report_path", "exec_path",
    ]

    print(f"[i] Selected {len(selected)} methods")

    # Prepare tools and project once per batch.
    randoop_jar = runner.ensure_randoop()
    jacoco_agent, jacoco_cli = runner.ensure_jacoco()
    workdir = runner.PROJECT_ROOT / project
    bin_dir, _src_dir, classpath = runner.prepare_stable_project(project, workdir)

    grouped_input = [pair for _, pair in selected]
    grouped = group_by_class(grouped_input)

    total = len(selected)
    processed = 0
    elapsed_samples: List[float] = []

    # For legacy flat csv compatibility
    legacy_rows: List[List[object]] = []

    for class_fqcn, method_list in grouped.items():
        print(f"\n=== class {class_fqcn} ({len(method_list)} methods) ===")

        class_slug = slugify(class_fqcn)
        classlist = workdir / f"classlist_{class_slug}.txt"

        # 1) Generate tests once per class.
        runner.build_classlist(bin_dir, classlist, class_fqcn)

        # Clean previous generated tests before class run.
        class_test_src = workdir / "randoop-tests" / "src"
        class_test_bin = workdir / "randoop-tests" / "bin"
        if class_test_src.exists():
            shutil.rmtree(class_test_src)
        if class_test_bin.exists():
            shutil.rmtree(class_test_bin)

        runner.run_randoop(workdir, randoop_jar, classpath, classlist, args.time_limit)

        base_src = workdir / "randoop-tests" / "base_src" / class_slug
        base_src.parent.mkdir(parents=True, exist_ok=True)
        if base_src.exists():
            shutil.rmtree(base_src)
        if class_test_src.exists():
            shutil.copytree(class_test_src, base_src)

        for method_name in method_list:
            iter_start = time.time()
            processed += 1
            print(f"[{processed}/{total}] Testing {class_fqcn}.{method_name}...")

            method_slug = slugify(f"{class_fqcn}__{method_name}")
            log_file = log_dir / f"{method_slug}.log"
            tests_path = artifact_report_path = exec_path = ""
            status = "ok"

            # Restore full class test pool for each method filter.
            if class_test_src.exists():
                shutil.rmtree(class_test_src)
            if base_src.exists():
                shutil.copytree(base_src, class_test_src)

            kept = runner.filter_randoop_tests_by_method(class_test_src, class_fqcn, method_name)

            coverage = {"line": (0, 0), "instr": (0, 0), "branch": (0, 0)}
            if kept == 0:
                status = "no-test-hit"
            else:
                try:
                    if class_test_bin.exists():
                        shutil.rmtree(class_test_bin)
                    cp_with_junit = os.pathsep.join([classpath, str(workdir / "src")])
                    runner.compile_tests(class_test_src, class_test_bin, cp_with_junit)
                    test_classes = runner.collect_test_classes(class_test_bin)
                    report_dir = runner.run_jacoco_tests(
                        workdir,
                        jacoco_agent,
                        jacoco_cli,
                        os.pathsep.join([str(class_test_bin), classpath]),
                        test_classes,
                        bin_dir,
                    )
                    xml_file = report_dir / "jacoco.xml"

                    # method-level mapping
                    javap_lines = runner.run_javap(bin_dir, class_fqcn)
                    parsed_methods = runner.parse_javap(javap_lines)
                    m_lines = runner.collect_method_lines(parsed_methods, method_name)
                    if not m_lines:
                        status = "method-lines-missing"
                    else:
                        line_cov = runner.load_line_coverage(xml_file, class_fqcn)
                        coverage = runner.compute_method_coverage_from_lines(line_cov, m_lines)
                except Exception as e:
                    status = f"coverage-error:{e}"

            values = compute_method_coverage(coverage)
            line_cov, instr_cov, branch_cov, line_num, line_den, instr_num, instr_den, branch_num, branch_den = values

            if save_artifacts:
                artifact_root = artifact_dir / method_slug
                artifact_root.mkdir(parents=True, exist_ok=True)
                try:
                    tests_path, artifact_report_path, exec_path = copy_artifacts(workdir, artifact_root)
                except Exception as e:
                    status = f"artifact-error:{e}"

            # Write light per-method log
            with log_file.open("w", encoding="utf-8") as lf:
                lf.write(f"project={project}\n")
                lf.write(f"class={class_fqcn}\n")
                lf.write(f"method={method_name}\n")
                lf.write(f"status={status}\n")
                lf.write(f"kept_tests={kept}\n")
                lf.write(f"line={line_num}/{line_den}\n")
                lf.write(f"instr={instr_num}/{instr_den}\n")
                lf.write(f"branch={branch_num}/{branch_den}\n")

            row_out = {
                "project": project,
                "class": class_fqcn,
                "method": method_name,
                "status": status,
                "line_cov": str(line_cov),
                "instr_cov": str(instr_cov),
                "branch_cov": str(branch_cov),
                "line_cov_num": str(line_num),
                "line_cov_den": str(line_den),
                "instr_cov_num": str(instr_num),
                "instr_cov_den": str(instr_den),
                "branch_cov_num": str(branch_num),
                "branch_cov_den": str(branch_den),
                "log_path": str(log_file),
                "tests_path": tests_path,
                "artifact_report_path": artifact_report_path,
                "exec_path": exec_path,
            }
            write_summary_row(summary_path, header, row_out)

            legacy_rows.append([
                class_fqcn,
                method_name,
                line_cov,
                instr_cov,
                branch_cov,
                line_num,
                line_den,
                instr_num,
                instr_den,
                branch_num,
                branch_den,
            ])

            iter_elapsed = time.time() - iter_start
            elapsed_samples.append(iter_elapsed)
            avg = sum(elapsed_samples) / float(len(elapsed_samples))
            remaining = total - processed
            print(f"[ETA] avg {avg:.1f}s/iter, remaining ~{int(avg * remaining)}s")

    # Legacy CSV for backward compatibility
    legacy_header = [
        "class_fqcn", "method_name",
        "line_cov", "instr_cov", "branch_cov",
        "line_cov_num", "line_cov_den",
        "instr_cov_num", "instr_cov_den",
        "branch_cov_num", "branch_cov_den",
    ]
    with legacy_csv.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(legacy_header)
        writer.writerows(legacy_rows)

    # Summary display from legacy rows
    total_line_num = sum(int(row[5]) for row in legacy_rows)
    total_line_den = sum(int(row[6]) for row in legacy_rows)
    total_instr_num = sum(int(row[7]) for row in legacy_rows)
    total_instr_den = sum(int(row[8]) for row in legacy_rows)
    total_branch_num = sum(int(row[9]) for row in legacy_rows)
    total_branch_den = sum(int(row[10]) for row in legacy_rows)

    line_pct = 100.0 * total_line_num / total_line_den if total_line_den > 0 else 0.0
    instr_pct = 100.0 * total_instr_num / total_instr_den if total_instr_den > 0 else 0.0
    branch_pct = 100.0 * total_branch_num / total_branch_den if total_branch_den > 0 else 0.0

    print("\n" + "=" * 60)
    print(f"Batch summary for {project}:")
    print("=" * 60)
    print(f"  Methods tested: {len(legacy_rows)}")
    print(f"  Line coverage:   {total_line_num:6d}/{total_line_den:6d} ({line_pct:6.2f}%)")
    print(f"  Instr coverage:  {total_instr_num:6d}/{total_instr_den:6d} ({instr_pct:6.2f}%)")
    print(f"  Branch coverage: {total_branch_num:6d}/{total_branch_den:6d} ({branch_pct:6.2f}%)")
    print("=" * 60)
    print(f"[+] Summary saved to {summary_path}")
    print(f"[+] Legacy CSV saved to {legacy_csv}")


if __name__ == "__main__":
    main()
