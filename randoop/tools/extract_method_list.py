#!/usr/bin/env python3
"""
Extract method list from project source/bytecode.

使用方式：
  python3 extract_method_list.py --project Lang [--threshold 2]
  
输出：
  data/method_lists/<project>_methods.csv
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


def extract_all_methods_javap(bin_dir: Path) -> List[Tuple[str, str]]:
    """
    Extract all methods from .class files using javap.
    Returns list of (class_fqcn, method_signature).
    """
    methods = []
    
    for cls_file in bin_dir.rglob("*.class"):
        rel = cls_file.relative_to(bin_dir)
        
        # Skip META-INF, inner classes, etc.
        if rel.parts and rel.parts[0].upper() == "META-INF":
            continue
        if "$" in rel.name or rel.name == "package-info.class":
            continue
        
        class_fqcn = ".".join(rel.with_suffix("").parts)
        
        # Extract methods using javap
        try:
            res = subprocess.run(
                ["javap", "-classpath", str(bin_dir), "-public", class_fqcn],
                capture_output=True, text=True, timeout=10
            )
            if res.returncode == 0:
                for line in res.stdout.split("\n"):
                    line = line.strip()
                    if "(" in line and not line.startswith("//"):
                        # e.g., "public void method();"
                        method_sig = line.rstrip(";").strip()
                        if method_sig and not method_sig.startswith("public class"):
                            methods.append((class_fqcn, method_sig))
        except Exception:
            pass
    
    return methods


def main():
    parser = argparse.ArgumentParser(description="Extract method list")
    parser.add_argument("--project", default="Lang", help="Project name")
    parser.add_argument("--threshold", type=int, default=2, help="CC threshold (not used for simple extraction)")
    
    args = parser.parse_args()
    project = args.project
    
    # Get binary directory
    workspace = RANDOOP_ROOT / "cache" / "project_workspace" / project
    bin_dir = workspace / "bin"
    
    if not bin_dir.exists():
        print(f"[-] Binary directory not found: {bin_dir}")
        print("[i] Run run_batch_coverage.py first to download project")
        sys.exit(1)
    
    print(f"[i] Extracting methods from {bin_dir}...")
    
    methods = extract_all_methods_javap(bin_dir)
    
    if not methods:
        print("[-] No methods found")
        sys.exit(1)
    
    print(f"[+] Found {len(methods)} methods")
    
    # Write output
    output_dir = DATA_DIR / "method_lists"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_csv = output_dir / f"{project}_methods.csv"
    
    with open(output_csv, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["class_fqcn", "method_signature"])
        for class_fqcn, method_sig in sorted(methods):
            writer.writerow([class_fqcn, method_sig])
    
    print(f"[+] Method list saved to {output_csv}")


if __name__ == "__main__":
    main()
