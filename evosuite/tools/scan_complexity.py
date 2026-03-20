#!/usr/bin/env python3
"""
Scan cyclomatic complexity for stable Maven artifacts using dataset/complex/cc_scan.py.
"""
import argparse
import subprocess
import sys
from pathlib import Path

EVOSUITE_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = EVOSUITE_ROOT.parents[1]
CC_SCAN = REPO_ROOT / "dataset" / "complex" / "cc_scan.py"

import run as runner  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description="Scan CC>threshold for stable Maven artifacts")
    parser.add_argument("--project", default="Lang", choices=runner.DEFAULT_PROJECTS, help="项目名")
    parser.add_argument("--threshold", type=int, default=2, help="CC 阈值（默认 2）")
    parser.add_argument("--out-dir", default=str(EVOSUITE_ROOT / "data" / "complexity"),
                        help="输出目录（默认 data/complexity）")
    parser.add_argument("--out-file", default=None, help="输出文件名（默认 <Project>_stable_cc.csv）")
    args = parser.parse_args()

    if not CC_SCAN.exists():
        raise RuntimeError(f"Cannot find cc_scan.py at {CC_SCAN}")

    workdir, src_dir, _ = runner.prepare_stable_project(args.project)

    out_dir = Path(args.out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    out_name = args.out_file or f"{args.project}_stable_cc.csv"
    out_path = out_dir / out_name

    cmd = [
        sys.executable, str(CC_SCAN),
        "--root", str(src_dir),
        "--out", str(out_path),
        "--threshold", str(args.threshold),
    ]
    print("[*] exec:", " ".join(cmd))
    subprocess.run(cmd, check=True)

    print("\n=== stable CC scan done ===")
    print("project:", args.project)
    print("sources:", src_dir)
    print("output:", out_path)


if __name__ == "__main__":
    main()
