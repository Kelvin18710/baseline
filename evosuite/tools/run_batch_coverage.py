#!/usr/bin/env python3
"""Batch run run.py for selected methods and collect coverage stats.

python3 /home/kelvin/work/baseline/evosuite/tools/run_batch_coverage.py \
  --project JxPath \
    --sampled-csv /home/kelvin/work/baseline/evosuite/data/sampled_methods.csv \
  --sampled-project-dir commons-jxpath \
  --time-limit 10


"""
import argparse
import csv
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

EVOSUITE_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = EVOSUITE_ROOT.parents[1]
CC_SCAN = REPO_ROOT / "dataset" / "complex" / "cc_scan.py"
import run as runner  # noqa: E402

RUN_SCRIPT = Path(__file__).resolve().parent / "run.py"

PROJECT_DIR_MAP = {
    "JCore": "com_fasterxml_jackson_core",
    "JDataBind": "com_fasterxml_jackson_databind",
    "JXML": "com_fasterxml_jackson_dataformat_xml",
    "JxPath": "commons_jxpath",
    "JodaTime": "joda_time",
    "Lang": "org_apache_commons_lang3",
    "Math": "org_apache_commons_math3",
    "Cli": "org_apache_commons_cli",
    "Codec": "org_apache_commons_codec",
    "Collections": "org_apache_commons_collections4",
    "CSV": "org_apache_commons_csv",
    "Compress": "org_apache_commons_compress",
}


def slugify(text: str) -> str:
    out = []
    for ch in text:
        if ch.isalnum():
            out.append(ch)
        else:
            out.append("_")
    slug = "".join(out).strip("_")
    return slug[:160] if len(slug) > 160 else slug


def load_cc_rows(csv_path: Path, min_cc: int) -> List[Dict[str, str]]:
    rows: List[Dict[str, str]] = []
    with csv_path.open("r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                cc = int(row.get("cc", "0"))
            except Exception:
                cc = 0
            if cc < min_cc:
                continue
            rows.append(row)
    return rows


def generate_cc_csv(project: str, out_path: Path, threshold: int) -> None:
    if not CC_SCAN.exists():
        raise RuntimeError(f"Cannot find cc_scan.py at {CC_SCAN}")

    _, src_dir, _ = runner.prepare_stable_project(project, need_classes=False)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    cmd = [
        sys.executable,
        str(CC_SCAN),
        "--root",
        str(src_dir),
        "--out",
        str(out_path),
        "--threshold",
        str(threshold),
    ]
    print("[*] auto-generate CC CSV:", " ".join(cmd))
    subprocess.run(cmd, check=True)


def parse_method_fen(method_fen: str) -> Tuple[str, str, str]:
    s = method_fen.strip().strip("\"")
    if not s:
        return "", "", ""
    paren_idx = s.find("(")
    if paren_idx == -1:
        head = s
        params = ""
    else:
        head = s[:paren_idx]
        params = s[paren_idx + 1:s.rfind(")")]
    if "." not in head:
        return "", head, params
    class_name, method_name = head.rsplit(".", 1)
    method_filter = method_name if params == "" else f"{method_name}({params})"
    return class_name, method_filter, params


def infer_project_dir(project: str) -> Optional[str]:
    return PROJECT_DIR_MAP.get(project)


def load_sampled_rows(csv_path: Path, project_dir: Optional[str]) -> List[Dict[str, str]]:
    rows: List[Dict[str, str]] = []
    with csv_path.open("r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if project_dir and row.get("project_dir") != project_dir:
                continue
            method_fen = row.get("method_FEN", "")
            target_class, target_method, params = parse_method_fen(method_fen)
            if not target_class or not target_method:
                continue
            rows.append({
                "class": target_class,
                "method": target_method,
                "params": params,
                "start_line": "",
                "cc": "",
                "project_dir": row.get("project_dir", ""),
            })
    return rows


def read_existing_keys(summary_path: Path) -> set:
    if not summary_path.exists():
        return set()
    keys = set()
    with summary_path.open("r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            key = (
                row.get("class") or "",
                row.get("method") or "",
                row.get("params") or "",
                row.get("start_line") or "",
            )
            keys.add(key)
    return keys


def make_method_key(target_class: str, target_method: str, params: str, start_line: str) -> Tuple[str, str, str, str]:
    return (
        (target_class or "").strip(),
        (target_method or "").strip(),
        (params or "").strip(),
        (start_line or "").strip(),
    )


def compute_method_coverage(
    coverage_map: Dict[int, Dict[str, int]],
    lines: Iterable[int],
) -> Tuple[Optional[float], Optional[float], Optional[float], int, int, int, int, int, int]:
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

    total = len(list(lines))
    known_total = total - unknown
    if known_total <= 0:
        return None, None, None, fully_covered + partially_covered, known_total, covered_instr, total_instr, covered_branch, total_branch

    line_covered = fully_covered + partially_covered
    line_ratio = (line_covered / float(known_total)) * 100.0
    instr_ratio = (covered_instr / float(total_instr) * 100.0) if total_instr > 0 else 0.0
    branch_ratio = (covered_branch / float(total_branch) * 100.0) if total_branch > 0 else 0.0
    return line_ratio, instr_ratio, branch_ratio, line_covered, known_total, covered_instr, total_instr, covered_branch, total_branch


def run_target(project: str, target_class: str, target_method: str, args, log_path: Path) -> int:
    cmd = [
        sys.executable, str(RUN_SCRIPT),
        "--project", project,
        "--time-limit", str(args.time_limit),
        "--target-class", target_class,
        "--target-method", target_method,
        "--method-filter-mode", args.method_filter_mode,
        "--min-tests", str(args.min_tests),
        "--min-tests-retry-mult", str(args.min_tests_retry_mult),
        "--min-goals", str(args.min_goals),
        "--min-generated-tests", str(args.min_generated_tests),
    ]
    if args.no_fallback:
        cmd.append("--no-fallback")

    log_path.parent.mkdir(parents=True, exist_ok=True)
    print("[*] exec:", " ".join(cmd))
    with log_path.open("w", encoding="utf-8") as f:
        proc = subprocess.Popen(cmd, stdout=f, stderr=subprocess.STDOUT, text=True)
        return proc.wait()


def write_summary_row(summary_path: Path, header: List[str], row: Dict[str, str]) -> None:
    exists = summary_path.exists()
    with summary_path.open("a", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=header)
        if not exists:
            writer.writeheader()
        writer.writerow(row)


def copy_artifacts(tests_dir: Path, report_dir: Path, exec_file: Path, dest_dir: Path) -> Tuple[Path, Path, Path]:
    dest_dir.mkdir(parents=True, exist_ok=True)
    tests_dest = dest_dir / "evosuite-tests"
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

    return tests_dest, report_dest, exec_dest


def main():
    parser = argparse.ArgumentParser(description="Batch run run.py and collect method coverage")
    parser.add_argument("--project", default="Lang", choices=runner.DEFAULT_PROJECTS, help="项目名")
    parser.add_argument("--cc-csv", default=None, help="CC CSV 文件（不传则自动生成 data/complexity/<Project>_stable_cc.csv）")
    parser.add_argument("--sampled-csv", default=None, help="采样 CSV（默认可用 data/sampled_methods.csv）")
    parser.add_argument("--sampled-project-dir", default=None, help="Sampled CSV 的 project_dir 过滤值（默认按 --project 推断）")
    parser.add_argument("--time-limit", type=int, default=0, help="EvoSuite 搜索预算（秒），<=0 时使用 EvoSuite 默认")
    parser.add_argument("--method-filter-mode", choices=["signature", "name", "post-filter"], default="signature")
    parser.add_argument("--min-tests", type=int, default=1, help="最少测试数")
    parser.add_argument("--min-tests-retry-mult", type=int, default=3, help="最少测试不足时预算倍数")
    parser.add_argument("--min-goals", type=int, default=2, help="方法过滤最少目标数阈值")
    parser.add_argument("--min-generated-tests", type=int, default=1, help="方法过滤最少生成测试数阈值")
    parser.add_argument("--no-fallback", action="store_true", help="禁用方法过滤失败的回退")
    parser.add_argument("--max-methods", type=int, default=None, help="最多处理的方法数")
    parser.add_argument("--start-index", type=int, default=0, help="从第几个方法开始（用于断点续跑）")
    parser.add_argument("--workers", type=int, default=1, help="并行 worker 总数（默认 1）")
    parser.add_argument("--worker-id", type=int, default=0, help="worker 编号（0~workers-1）")
    parser.add_argument("--skip-existing", action="store_true", default=True, help="跳过 summary 中已有的条目（默认开启）")
    parser.add_argument("--no-skip-existing", action="store_true", help="禁用跳过 summary 中已有的条目")
    parser.add_argument("--out-dir", default=str(EVOSUITE_ROOT / "reports" / "batch" / "coverage"),
                        help="summary 输出目录")
    parser.add_argument("--log-dir", default=str(EVOSUITE_ROOT / "reports" / "batch" / "logs"),
                        help="每次运行日志输出目录")
    parser.add_argument("--artifact-dir", default=str(EVOSUITE_ROOT / "reports" / "batch" / "artifacts"),
                        help="每轮测试产物保存目录")
    parser.add_argument("--no-artifacts", action="store_true", help="不保存测试/Jacoco 产物")
    args = parser.parse_args()

    if args.sampled_csv:
        sampled_csv = Path(args.sampled_csv)
        if not sampled_csv.exists():
            raise RuntimeError(f"Sampled CSV not found: {sampled_csv}")
        project_dir = args.sampled_project_dir or infer_project_dir(args.project)
        rows = load_sampled_rows(sampled_csv, project_dir)
    else:
        cc_csv = Path(args.cc_csv) if args.cc_csv else EVOSUITE_ROOT / "data" / "complexity" / f"{args.project}_stable_cc.csv"
        cc_threshold = 2
        generate_cc_csv(args.project, cc_csv, cc_threshold)
        rows = load_cc_rows(cc_csv, cc_threshold)
    if not rows:
        print("[WARN] No rows found after filtering.")
        return

    workdir, src_dir, _ = runner.prepare_stable_project(args.project)
    classes_dir = workdir / "classes"
    tests_dir = workdir / "evosuite-tests"

    out_dir = (Path(args.out_dir).resolve() / args.project)
    out_dir.mkdir(parents=True, exist_ok=True)
    log_dir = (Path(args.log_dir).resolve() / args.project)
    log_dir.mkdir(parents=True, exist_ok=True)
    artifact_dir = (Path(args.artifact_dir).resolve() / args.project)
    artifact_dir.mkdir(parents=True, exist_ok=True)

    summary_path = out_dir / f"{args.project}_stable_coverage.csv"
    if args.no_skip_existing:
        args.skip_existing = False
    existing_keys = read_existing_keys(summary_path) if args.skip_existing else set()

    if args.workers < 1:
        raise RuntimeError("--workers 必须 >= 1")
    if args.worker_id < 0 or args.worker_id >= args.workers:
        raise RuntimeError("--worker-id 必须在 [0, workers-1] 范围内")

    header = [
        "project", "class", "method", "params", "start_line", "cc",
        "status", "line_cov", "instr_cov", "branch_cov",
        "line_cov_num", "line_cov_den",
        "instr_cov_num", "instr_cov_den",
        "branch_cov_num", "branch_cov_den",
        "tests", "calls", "log_path", "report_path",
        "tests_path", "artifact_report_path", "exec_path",
    ]

    selected: List[Tuple[int, Dict[str, str]]] = []
    for idx, row in enumerate(rows):
        if idx < args.start_index:
            continue
        if args.workers > 1 and (idx % args.workers) != args.worker_id:
            continue
        target_class = row.get("class_guess") or row.get("class") or ""
        target_method = row.get("method") or ""
        params = row.get("params") or ""
        start_line = row.get("start_line") or ""
        key = make_method_key(target_class, target_method, params, start_line)
        if args.skip_existing and key in existing_keys:
            continue
        selected.append((idx, row))

    if args.max_methods is not None:
        selected = selected[:args.max_methods]

    if not selected:
        print("[WARN] No rows found after filtering.")
        return

    total = len(selected)
    processed = 0
    elapsed_samples: List[float] = []

    for pos, (idx, row) in enumerate(selected, start=1):
        target_class = row.get("class_guess") or row.get("class") or ""
        target_method = row.get("method") or ""
        params = row.get("params") or ""
        start_line = row.get("start_line") or ""
        cc_val = row.get("cc") or ""

        log_name = slugify(f"{target_class}__{target_method}__{start_line}") + ".log"
        log_path = log_dir / log_name

        print(f"\n=== [{pos}/{total}] (global #{idx + 1}) {target_class}::{target_method} (CC={cc_val}) ===")
        iter_start = time.time()
        status = "ok"
        line_cov = instr_cov = branch_cov = ""
        line_cov_num = line_cov_den = ""
        instr_cov_num = instr_cov_den = ""
        branch_cov_num = branch_cov_den = ""
        tests = calls = ""
        report_path = workdir / "jacoco-report" / "report.xml"
        report_dir = workdir / "jacoco-report"
        exec_file = workdir / "jacoco.exec"
        tests_path = artifact_report_path = exec_path = ""

        rc = run_target(args.project, target_class, target_method, args, log_path)
        if rc != 0:
            status = f"error(rc={rc})"
        else:
            try:
                coverage_map = runner.load_line_coverage(report_path, target_class)
                methods = runner.parse_javap(runner.run_javap(classes_dir, target_class))
                method_names = [runner.method_name_from_filter(target_method)]
                method_lines_map = runner.collect_method_lines(methods, method_names, [])
                lines = method_lines_map.get(method_names[0], set())

                if not lines:
                    status = "method-lines-missing"
                else:
                    line_ratio, instr_ratio, branch_ratio, lc_num, lc_den, ic_num, ic_den, bc_num, bc_den = compute_method_coverage(
                        coverage_map, lines
                    )
                    if line_ratio is None:
                        status = "coverage-missing"
                    else:
                        line_cov = f"{line_ratio:.1f}"
                        instr_cov = f"{instr_ratio:.1f}"
                        branch_cov = f"{branch_ratio:.1f}"
                    line_cov_num = str(lc_num)
                    line_cov_den = str(lc_den)
                    instr_cov_num = str(ic_num)
                    instr_cov_den = str(ic_den)
                    branch_cov_num = str(bc_num)
                    branch_cov_den = str(bc_den)

                test_file = runner.find_evosuite_test_file(tests_dir, target_class)
                tests = str(runner.count_tests_in_file(test_file))
                calls = str(runner.count_method_calls_in_test(test_file, target_class, target_method))
            except Exception as exc:
                status = f"coverage-error:{exc}"

        if not args.no_artifacts:
            artifact_name = slugify(f"{target_class}__{target_method}__{start_line}")
            artifact_root = artifact_dir / artifact_name
            try:
                tests_dest, report_dest, exec_dest = copy_artifacts(tests_dir, report_dir, exec_file, artifact_root)
                tests_path = str(tests_dest)
                artifact_report_path = str(report_dest / "report.xml")
                exec_path = str(exec_dest)
            except Exception as exc:
                status = f"artifact-error:{exc}"

        row_out = {
            "project": args.project,
            "class": target_class,
            "method": target_method,
            "params": params,
            "start_line": start_line,
            "cc": cc_val,
            "status": status,
            "line_cov": line_cov,
            "instr_cov": instr_cov,
            "branch_cov": branch_cov,
            "line_cov_num": line_cov_num,
            "line_cov_den": line_cov_den,
            "instr_cov_num": instr_cov_num,
            "instr_cov_den": instr_cov_den,
            "branch_cov_num": branch_cov_num,
            "branch_cov_den": branch_cov_den,
            "tests": tests,
            "calls": calls,
            "log_path": str(log_path),
            "report_path": str(report_path),
            "tests_path": tests_path,
            "artifact_report_path": artifact_report_path,
            "exec_path": exec_path,
        }
        write_summary_row(summary_path, header, row_out)
        processed += 1
        iter_elapsed = time.time() - iter_start
        elapsed_samples.append(iter_elapsed)
        if processed > 0:
            avg = sum(elapsed_samples) / float(len(elapsed_samples))
            remaining = max(0, total - processed)
            eta_seconds = int(avg * remaining)
            eta_minutes, eta_seconds = divmod(eta_seconds, 60)
            eta_hours, eta_minutes = divmod(eta_minutes, 60)
            if eta_hours > 0:
                eta_text = f"{eta_hours}h{eta_minutes}m{eta_seconds}s"
            elif eta_minutes > 0:
                eta_text = f"{eta_minutes}m{eta_seconds}s"
            else:
                eta_text = f"{eta_seconds}s"
            print(f"[ETA] avg {avg:.1f}s/iter, remaining ~{eta_text}")

    print("\n=== batch done ===")
    print("summary:", summary_path)


if __name__ == "__main__":
    main()
