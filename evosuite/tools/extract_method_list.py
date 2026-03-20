#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# 
"""
Scan Java projects and output method list CSV in the same format as
baseline/evosuite/data/sampled_methods.csv.

Features:
- Select project by name (stable Maven artifacts) or by path.
- Filter by cyclomatic complexity >= k.
- Output CSV: method_FEN, all_cfg_paths_num, project_dir

python3 /home/kelvin/work/baseline/evosuite/tools/extract_method_list.py \
  --project JxPath \
  --min-cc 2

"""
import argparse
import csv
import os
import re
import sys
from pathlib import Path
from typing import List, Optional

TOOLS_DIR = Path(__file__).resolve().parent
EVOSUITE_ROOT = TOOLS_DIR.parent
REPO_ROOT = EVOSUITE_ROOT.parents[1]

# Reuse CC scanner utilities
CC_SCAN_PATH = REPO_ROOT / "dataset" / "complex" / "cc_scan.py"
sys.path.insert(0, str(CC_SCAN_PATH.parent))
import cc_scan  # type: ignore  # noqa: E402

import run as runner  # noqa: E402


MODIFIERS = {
	"final",
	"volatile",
	"transient",
	"synchronized",
	"public",
	"protected",
	"private",
	"static",
}


def split_params(params_str: str) -> List[str]:
	"""Split parameter list by commas while respecting generics."""
	params = []
	buf = []
	depth = 0
	for ch in params_str:
		if ch == '<':
			depth += 1
		elif ch == '>':
			depth = max(depth - 1, 0)
		elif ch == ',' and depth == 0:
			params.append("".join(buf).strip())
			buf = []
			continue
		buf.append(ch)
	if buf:
		params.append("".join(buf).strip())
	return [p for p in params if p]


def normalize_param_type(raw: str) -> str:
	if not raw:
		return ""
	s = raw.strip()
	# remove annotations
	s = re.sub(r"@\w+(\([^)]*\))?\s*", "", s)
	# remove excessive whitespace
	s = re.sub(r"\s+", " ", s).strip()

	# strip trailing param name
	if " " in s:
		type_part = s.rsplit(" ", 1)[0].strip()
	else:
		type_part = s

	# remove modifiers from type part
	tokens = [t for t in type_part.split(" ") if t and t not in MODIFIERS]
	type_part = " ".join(tokens)
	# normalize spaces around generics
	type_part = re.sub(r"\s*([<>?,])\s*", r"\1", type_part)
	return type_part.strip()


def params_to_types(params_str: str) -> str:
	if not params_str.strip():
		return ""
	parts = split_params(params_str)
	types = []
	for p in parts:
		t = normalize_param_type(p)
		if t:
			types.append(t)
	return ",".join(types)


def project_dir_name_from_coords(project: str) -> str:
	if project not in runner.STABLE_COORDS:
		return project
	artifact, _, group = runner.STABLE_COORDS[project]
	# Prefer group as project_dir in the baseline style: com_fasterxml_jackson_core
	return group.replace(".", "_") if group else artifact.replace("-", "_")


def scan_project(root: Path, min_cc: int) -> List[dict]:
	src_roots = cc_scan.guess_source_roots(str(root))
	results = []
	seen_files = set()

	for sr in src_roots:
		for fp in cc_scan.iter_java_files(sr):
			real_fp = os.path.realpath(fp)
			if real_fp in seen_files:
				continue
			seen_files.add(real_fp)

			try:
				with open(fp, "r", encoding="utf-8") as f:
					code = f.read()
			except Exception:
				try:
					with open(fp, "r", encoding="latin-1") as f:
						code = f.read()
				except Exception:
					continue

			pkg = cc_scan.read_package(code)
			clean = cc_scan._strip_comments_and_strings(code)
			methods = cc_scan.extract_methods(clean)

			cls_guess = os.path.splitext(os.path.basename(fp))[0]
			class_fqcn = (pkg + "." + cls_guess) if pkg else cls_guess

			for md in methods:
				cc_val = cc_scan.compute_cc(md["body"])
				if cc_val < min_cc:
					continue
				params_types = params_to_types(md["params"])
				method_fen = "{0}.{1}({2})".format(class_fqcn, md["name"], params_types)
				results.append(
					{
						"method_FEN": method_fen,
						"all_cfg_paths_num": cc_val,
					}
				)

	results.sort(key=lambda x: (-int(x["all_cfg_paths_num"]), x["method_FEN"]))
	return results


def main():
	parser = argparse.ArgumentParser(description="Scan project methods by CC>=k and export CSV")
	parser.add_argument("--project", default=None, choices=runner.DEFAULT_PROJECTS,
						help="项目名（stable Maven，默认 None）")
	parser.add_argument("--project-dir", default=None, help="直接指定项目根目录")
	parser.add_argument("--project-dir-name", default=None, help="输出 CSV 的 project_dir 字段值")
	parser.add_argument("--min-cc", type=int, default=10, help="圈复杂度阈值 k（默认 10）")
	parser.add_argument("--out", default=None, help="输出 CSV 路径（默认 data/method_lists/<name>_cc<k>.csv）")
	args = parser.parse_args()

	if not CC_SCAN_PATH.exists():
		raise RuntimeError("Cannot find cc_scan.py at {0}".format(CC_SCAN_PATH))

	if args.project and args.project_dir:
		raise RuntimeError("请二选一：--project 或 --project-dir")

	if args.project:
		_, src_dir, _ = runner.prepare_stable_project(args.project, need_classes=False)
		root = Path(src_dir)
		project_dir = args.project_dir_name or project_dir_name_from_coords(args.project)
		default_name = "{0}_cc{1}.csv".format(args.project, args.min_cc)
	elif args.project_dir:
		root = Path(args.project_dir)
		if not root.exists():
			raise RuntimeError("project-dir 不存在: {0}".format(root))
		project_dir = args.project_dir_name or root.name
		default_name = "{0}_cc{1}.csv".format(root.name, args.min_cc)
	else:
		raise RuntimeError("必须提供 --project 或 --project-dir")

	out_path = Path(args.out) if args.out else (EVOSUITE_ROOT / "data" / "method_lists" / default_name)
	out_path.parent.mkdir(parents=True, exist_ok=True)

	rows = scan_project(root, args.min_cc)

	with out_path.open("w", encoding="utf-8", newline="") as f:
		writer = csv.writer(f)
		writer.writerow(["method_FEN", "all_cfg_paths_num", "project_dir"])
		for r in rows:
			writer.writerow([r["method_FEN"], r["all_cfg_paths_num"], project_dir])

	print("=== 方法扫描完成 ===")
	print("project root:", root)
	print("min_cc:", args.min_cc)
	print("project_dir:", project_dir)
	print("methods:", len(rows))
	print("output:", out_path)


if __name__ == "__main__":
	main()
