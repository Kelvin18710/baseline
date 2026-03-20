#!/usr/bin/env python3
"""Launch run_batch_coverage.py with multiple workers using a single command."""
import argparse
import os
import subprocess
import sys
from pathlib import Path
from typing import List

BASE_DIR = Path(__file__).resolve().parent
BATCH_RUN = BASE_DIR / "run_batch_coverage.py"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run run_batch_coverage.py in parallel workers with a single command",
        allow_abbrev=False,
    )
    parser.add_argument("--workers", type=int, default=0, help="并行 worker 数量（默认使用 CPU 核数）")
    parser.add_argument("--worker-start", type=int, default=0, help="起始 worker 编号（默认 0）")
    parser.add_argument("--log-dir", default=None, help="并行 worker 日志目录（默认不重定向）")
    parser.add_argument("--dry-run", action="store_true", help="仅打印命令，不实际执行")
    args, unknown = parser.parse_known_args()
    args._unknown = unknown
    return args


def ensure_log_dir(log_dir: str) -> Path:
    path = Path(log_dir).resolve()
    path.mkdir(parents=True, exist_ok=True)
    return path


def build_worker_cmd(worker_id: int, workers: int, extra_args: List[str]) -> List[str]:
    return [
        sys.executable,
        str(BATCH_RUN),
        "--workers",
        str(workers),
        "--worker-id",
        str(worker_id),
        *extra_args,
    ]


def main() -> int:
    args = parse_args()
    workers = args.workers or (os.cpu_count() or 1)
    if workers < 1:
        raise RuntimeError("--workers 必须 >= 1")
    if args.worker_start < 0 or args.worker_start >= workers:
        raise RuntimeError("--worker-start 必须在 [0, workers-1] 范围内")

    log_dir = ensure_log_dir(args.log_dir) if args.log_dir else None
    processes: List[subprocess.Popen] = []

    for worker_id in range(args.worker_start, workers):
        cmd = build_worker_cmd(worker_id, workers, args._unknown)
        cmd_display = " ".join(cmd)
        if args.dry_run:
            print(f"[DRY] {cmd_display}")
            continue

        stdout = None
        if log_dir:
            log_path = log_dir / f"worker_{worker_id}.log"
            stdout = log_path.open("w", encoding="utf-8")
            print(f"[*] worker {worker_id} -> {log_path}")
        else:
            print(f"[*] worker {worker_id}: {cmd_display}")

        proc = subprocess.Popen(cmd, stdout=stdout, stderr=subprocess.STDOUT, text=True)
        processes.append(proc)

    if args.dry_run:
        return 0

    exit_code = 0
    for proc in processes:
        rc = proc.wait()
        if rc != 0:
            exit_code = rc
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
