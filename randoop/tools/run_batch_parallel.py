#!/usr/bin/env python3
"""
Parallel batch execution wrapper for Randoop coverage.

使用方式：
  python3 run_batch_parallel.py --workers 4 --project Lang [--max-methods N]
  
每个 worker 运行 run_batch_coverage.py，处理其分配的方法子集。
"""

import argparse
import subprocess
import sys
from pathlib import Path
from typing import List

SCRIPT_DIR = Path(__file__).resolve().parent


def main():
    parser = argparse.ArgumentParser(description="Parallel Randoop batch execution")
    parser.add_argument("--workers", type=int, default=4, help="Number of parallel workers")
    parser.add_argument("--project", default="Lang", help="Project name")
    parser.add_argument("--max-methods", type=int, help="Max methods total to process")
    parser.add_argument("--no-artifacts", action="store_true", help="Don't backup artifacts")
    
    args = parser.parse_args()
    
    workers = args.workers
    project = args.project
    max_methods = args.max_methods
    
    print(f"[*] Launching {workers} parallel workers for {project}...")
    
    procs = []
    for worker_id in range(workers):
        cmd = [
            "python3", str(SCRIPT_DIR / "run_batch_coverage.py"),
            "--project", project,
            f"--worker-id={worker_id}",
            f"--workers={workers}",
        ]
        
        if max_methods:
            cmd.extend(["--max-methods", str(max_methods)])
        
        if args.no_artifacts:
            cmd.append("--no-artifacts")
        
        print(f"[*] Starting worker {worker_id+1}/{workers}...")
        proc = subprocess.Popen(cmd)
        procs.append(proc)
    
    # Wait for all workers to complete
    failed = 0
    for idx, proc in enumerate(procs, 1):
        rc = proc.wait()
        if rc != 0:
            print(f"[-] Worker {idx} failed with rc={rc}")
            failed += 1
        else:
            print(f"[+] Worker {idx} completed")
    
    if failed > 0:
        print(f"[-] {failed}/{workers} workers failed")
        sys.exit(1)
    
    print("[+] All workers completed successfully")
    
    print(f"[i] Worker summaries in reports/batch/coverage/{project}/")
    print(f"[i] Worker logs in reports/batch/logs/{project}/")


if __name__ == "__main__":
    main()
