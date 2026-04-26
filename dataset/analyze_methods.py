#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
在 dataset 目录下做项目方法统计与筛选。

当前默认配置：
- 项目: lang3.20
- 访问等级: public
- 圈复杂度: >= 2

运行方式：
    python3 dataset/analyze_methods.py

后续如果要切换项目或筛选条件，直接修改本文件开头的 CONFIG 即可。
"""

from __future__ import annotations

import csv
import json
import os
import re
import tarfile
import zipfile
from pathlib import Path
from typing import Dict, Iterable, List


BASE_DIR = Path(__file__).resolve().parent
REPO_ROOT = BASE_DIR.parent


CONFIG = {
    "active_project": "lang3.20",
    "projects": {
        "lang3.20": {
            "archive": REPO_ROOT / "shared_project_packages" / "project_archives" / "lang-commons-lang3-3.20.0-sources.jar",
            "type": "archive",
        },
        "codec1.21": {
            "archive": REPO_ROOT / "shared_project_packages" / "project_archives" / "codec-commons-codec-1.21.0-sources.jar",
            "type": "archive",
        },
    },
    "min_cc": 2,
    "access_levels": [],
    "include_constructors": True,
    "workspace_dir": BASE_DIR / "_workspace",
    "output_dir": BASE_DIR / "outputs",
    "force_reextract": False,
}


CONTROL_KEYWORDS = {
    "if",
    "for",
    "while",
    "switch",
    "catch",
    "do",
    "try",
    "synchronized",
    "new",
    "return",
    "throw",
    "assert",
}

MODIFIERS = {
    "abstract",
    "default",
    "final",
    "native",
    "private",
    "protected",
    "public",
    "static",
    "strictfp",
    "synchronized",
    "transient",
    "volatile",
}

SKIP_DIRS = {"target", "build", ".git", ".idea", ".svn", "out"}
JAVA_NAMESPACE_DIRS = {"com", "edu", "io", "jakarta", "javax", "net", "org"}

CC_PATTERNS = [
    (re.compile(r"\bif\b"), 1),
    (re.compile(r"\bfor\b"), 1),
    (re.compile(r"\bwhile\b"), 1),
    (re.compile(r"\bdo\b"), 1),
    (re.compile(r"\bcase\b"), 1),
    (re.compile(r"\bcatch\b"), 1),
    (re.compile(r"\?"), 1),
    (re.compile(r"&&"), 1),
    (re.compile(r"\|\|"), 1),
]


def ensure_project_root(project_key: str) -> Path:
    project_cfg = CONFIG["projects"][project_key]
    project_type = project_cfg["type"]

    if project_type == "dir":
        root = Path(project_cfg["path"]).resolve()
        if not root.exists():
            raise RuntimeError("project path does not exist: {0}".format(root))
        return root

    archive_path = Path(project_cfg["archive"]).resolve()
    if not archive_path.exists():
        raise RuntimeError("archive does not exist: {0}".format(archive_path))

    extract_root = Path(CONFIG["workspace_dir"]).resolve() / project_key
    marker_path = extract_root / ".extracted_from"

    if CONFIG["force_reextract"] and extract_root.exists():
        remove_tree(extract_root)

    if not extract_root.exists():
        extract_root.mkdir(parents=True, exist_ok=True)
        extract_archive(archive_path, extract_root)
        marker_path.write_text(str(archive_path), encoding="utf-8")
    elif not marker_path.exists():
        marker_path.write_text(str(archive_path), encoding="utf-8")

    return pick_source_root(extract_root)


def remove_tree(path: Path) -> None:
    for child in sorted(path.glob("**/*"), reverse=True):
        if child.is_file() or child.is_symlink():
            child.unlink()
        elif child.is_dir():
            child.rmdir()
    if path.exists():
        path.rmdir()


def extract_archive(archive_path: Path, extract_root: Path) -> None:
    suffixes = archive_path.suffixes
    if archive_path.suffix in {".jar", ".zip"}:
        with zipfile.ZipFile(str(archive_path), "r") as zf:
            zf.extractall(str(extract_root))
        return
    if suffixes[-2:] == [".tar", ".gz"] or archive_path.suffix == ".tgz":
        with tarfile.open(str(archive_path), "r:gz") as tf:
            tf.extractall(str(extract_root))
        return
    raise RuntimeError("unsupported archive format: {0}".format(archive_path))


def pick_source_root(extract_root: Path) -> Path:
    common_roots = [
        extract_root / "src" / "main" / "java",
        extract_root / "src" / "java",
        extract_root / "source",
    ]
    for root in common_roots:
        if root.is_dir():
            return root

    subdirs = [p for p in extract_root.iterdir() if p.is_dir() and p.name != "META-INF"]
    if len(subdirs) == 1 and not any(extract_root.glob("*.java")):
        nested_root = subdirs[0]
        if nested_root.name not in JAVA_NAMESPACE_DIRS:
            return nested_root

    return extract_root


def guess_source_roots(root: Path) -> List[Path]:
    candidates = [
        root / "src" / "main" / "java",
        root / "src" / "java",
        root / "source",
        root / "src",
    ]
    exists = [p for p in candidates if p.is_dir()]
    return exists or [root]


def iter_java_files(src_root: Path) -> Iterable[Path]:
    for base, dirs, files in os.walk(str(src_root)):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for filename in files:
            if filename.endswith(".java") and filename != "package-info.java":
                yield Path(base) / filename


def read_text(path: Path) -> str:
    for encoding in ("utf-8", "latin-1"):
        try:
            return path.read_text(encoding=encoding)
        except Exception:
            continue
    raise RuntimeError("cannot read file: {0}".format(path))


def read_package(code: str) -> str:
    match = re.search(r"^\s*package\s+([A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*)\s*;", code, re.M)
    return match.group(1) if match else ""


def strip_comments_and_strings(code: str) -> str:
    out: List[str] = []
    i = 0
    n = len(code)

    in_line = False
    in_block = False
    in_str = False
    in_char = False

    while i < n:
        ch = code[i]
        nxt = code[i + 1] if i + 1 < n else ""

        if not (in_line or in_block or in_str or in_char):
            if ch == "/" and nxt == "/":
                in_line = True
                out.extend([" ", " "])
                i += 2
                continue
            if ch == "/" and nxt == "*":
                in_block = True
                out.extend([" ", " "])
                i += 2
                continue
            if ch == '"':
                in_str = True
                out.append(" ")
                i += 1
                continue
            if ch == "'":
                in_char = True
                out.append(" ")
                i += 1
                continue

            out.append(ch)
            i += 1
            continue

        if in_line:
            if ch == "\n":
                in_line = False
                out.append("\n")
            else:
                out.append(" ")
            i += 1
            continue

        if in_block:
            if ch == "*" and nxt == "/":
                out.extend([" ", " "])
                i += 2
                in_block = False
            else:
                out.append("\n" if ch == "\n" else " ")
                i += 1
            continue

        if in_str:
            if ch == "\\" and i + 1 < n:
                out.extend([" ", " "])
                i += 2
                continue
            if ch == '"':
                out.append(" ")
                i += 1
                in_str = False
            else:
                out.append("\n" if ch == "\n" else " ")
                i += 1
            continue

        if in_char:
            if ch == "\\" and i + 1 < n:
                out.extend([" ", " "])
                i += 2
                continue
            if ch == "'":
                out.append(" ")
                i += 1
                in_char = False
            else:
                out.append("\n" if ch == "\n" else " ")
                i += 1
            continue

    return "".join(out)


def compute_cc(method_body: str) -> int:
    cc = 1
    for pattern, weight in CC_PATTERNS:
        matches = pattern.findall(method_body)
        if matches:
            cc += len(matches) * weight
    return cc


def extract_methods(clean_code: str, class_name_guess: str) -> List[Dict[str, object]]:
    methods: List[Dict[str, object]] = []
    n = len(clean_code)
    i = 0

    while i < n:
        if clean_code[i] != "(":
            i += 1
            continue

        j = i - 1
        while j >= 0 and clean_code[j].isspace():
            j -= 1

        name_end = j
        while j >= 0 and (clean_code[j].isalnum() or clean_code[j] in {"_", "$"}):
            j -= 1
        name_start = j + 1

        if name_start > name_end:
            i += 1
            continue

        name = clean_code[name_start:name_end + 1]
        if not name or name in CONTROL_KEYWORDS or name in {"super", "this"}:
            i += 1
            continue

        depth = 1
        k = i + 1
        while k < n and depth > 0:
            if clean_code[k] == "(":
                depth += 1
            elif clean_code[k] == ")":
                depth -= 1
            k += 1
        if depth != 0:
            i += 1
            continue

        params_end = k - 1
        t = k
        while t < n and clean_code[t].isspace():
            t += 1

        if clean_code.startswith("throws", t):
            t += len("throws")
            while t < n and clean_code[t] not in "{;":
                t += 1
            while t < n and clean_code[t].isspace():
                t += 1

        if t >= n or clean_code[t] in ";":
            i += 1
            continue
        if clean_code[t] != "{":
            i += 1
            continue

        header_start = find_header_start(clean_code, name_start)
        header = clean_code[header_start:name_start].strip()
        if not looks_like_method_header(header):
            i += 1
            continue

        brace_pos = t
        brace_depth = 0
        p = brace_pos
        body = None
        while p < n:
            if clean_code[p] == "{":
                brace_depth += 1
            elif clean_code[p] == "}":
                brace_depth -= 1
                if brace_depth == 0:
                    body = clean_code[brace_pos:p + 1]
                    break
            p += 1

        if body is None:
            i += 1
            continue

        params = clean_code[i + 1:params_end].strip()
        access = detect_access_level(header)
        line_number = clean_code.count("\n", 0, name_start) + 1
        is_constructor = name == class_name_guess

        methods.append(
            {
                "name": name,
                "params": params,
                "header": header,
                "access": access,
                "line_number": line_number,
                "body": body,
                "is_constructor": is_constructor,
            }
        )
        i = brace_pos + 1

    return methods


def find_header_start(clean_code: str, name_start: int) -> int:
    boundary = -1
    for token in (";", "{", "}"):
        boundary = max(boundary, clean_code.rfind(token, 0, name_start))
    return boundary + 1


def looks_like_method_header(header: str) -> bool:
    if not header:
        return False
    compact = " ".join(header.split())
    if not compact:
        return False
    if re.search(r"\b(new|return|throw|case)\b", compact):
        return False
    if "=" in compact:
        return False
    return True


def detect_access_level(header: str) -> str:
    match = re.search(r"\b(public|protected|private)\b", header)
    if match:
        return match.group(1)
    return "package-private"


def split_params(params_str: str) -> List[str]:
    params: List[str] = []
    buf: List[str] = []
    angle_depth = 0
    paren_depth = 0
    bracket_depth = 0

    for ch in params_str:
        if ch == "<":
            angle_depth += 1
        elif ch == ">":
            angle_depth = max(angle_depth - 1, 0)
        elif ch == "(":
            paren_depth += 1
        elif ch == ")":
            paren_depth = max(paren_depth - 1, 0)
        elif ch == "[":
            bracket_depth += 1
        elif ch == "]":
            bracket_depth = max(bracket_depth - 1, 0)
        elif ch == "," and angle_depth == 0 and paren_depth == 0 and bracket_depth == 0:
            params.append("".join(buf).strip())
            buf = []
            continue
        buf.append(ch)

    if buf:
        params.append("".join(buf).strip())
    return [item for item in params if item]


def normalize_param_type(raw: str) -> str:
    value = raw.strip()
    if not value:
        return ""

    value = re.sub(r"@\w+(?:\([^)]*\))?\s*", "", value)
    value = re.sub(r"\s+", " ", value).strip()

    if "..." in value:
        value = value.replace("...", "[]")

    if " " in value:
        type_part = value.rsplit(" ", 1)[0].strip()
    else:
        type_part = value

    tokens = [token for token in type_part.split(" ") if token and token not in MODIFIERS]
    type_part = " ".join(tokens)
    type_part = re.sub(r"\s*([<>?,&\[\]])\s*", r"\1", type_part)
    return type_part.strip()


def params_to_types(params_str: str) -> str:
    if not params_str.strip():
        return ""
    normalized = []
    for param in split_params(params_str):
        param_type = normalize_param_type(param)
        if param_type:
            normalized.append(param_type)
    return ",".join(normalized)


def build_method_fen(package_name: str, class_name_guess: str, method_name: str, params: str) -> str:
    fqcn = class_name_guess if not package_name else package_name + "." + class_name_guess
    return "{0}.{1}({2})".format(fqcn, method_name, params)


def analyze_project(project_key: str) -> Dict[str, object]:
    project_root = ensure_project_root(project_key)
    source_roots = guess_source_roots(project_root)

    access_levels = set(CONFIG["access_levels"])
    min_cc = int(CONFIG["min_cc"])
    include_constructors = bool(CONFIG["include_constructors"])

    matched_rows: List[Dict[str, object]] = []
    total_methods = 0
    total_files = 0
    seen_files = set()

    for src_root in source_roots:
        for java_file in iter_java_files(src_root):
            real_path = str(java_file.resolve())
            if real_path in seen_files:
                continue
            seen_files.add(real_path)
            total_files += 1

            code = read_text(java_file)
            package_name = read_package(code)
            clean_code = strip_comments_and_strings(code)
            class_name_guess = java_file.stem
            methods = extract_methods(clean_code, class_name_guess)
            total_methods += len(methods)

            rel_path = java_file.relative_to(project_root).as_posix()

            for method in methods:
                if not include_constructors and method["is_constructor"]:
                    continue
                if access_levels and method["access"] not in access_levels:
                    continue

                cc_value = compute_cc(str(method["body"]))
                if cc_value < min_cc:
                    continue

                params_types = params_to_types(str(method["params"]))
                method_fen = build_method_fen(
                    package_name=package_name,
                    class_name_guess=class_name_guess,
                    method_name=str(method["name"]),
                    params=params_types,
                )
                matched_rows.append(
                    {
                        "project": project_key,
                        "access": method["access"],
                        "cc": cc_value,
                        "is_constructor": method["is_constructor"],
                        "method_fen": method_fen,
                        "class_name_guess": class_name_guess,
                        "method_name": method["name"],
                        "params_types": params_types,
                        "file": rel_path,
                        "line_number": method["line_number"],
                    }
                )

    matched_rows.sort(key=lambda row: (-int(row["cc"]), str(row["method_fen"])))
    return {
        "project": project_key,
        "project_root": str(project_root),
        "source_roots": [str(path) for path in source_roots],
        "min_cc": min_cc,
        "access_levels": sorted(access_levels),
        "include_constructors": include_constructors,
        "scanned_java_files": total_files,
        "recognized_methods": total_methods,
        "matched_methods": len(matched_rows),
        "rows": matched_rows,
    }


def write_outputs(result: Dict[str, object]) -> Dict[str, Path]:
    output_dir = Path(CONFIG["output_dir"]).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    project_key = str(result["project"])
    access_label = "-".join(result["access_levels"]) if result["access_levels"] else "all-access"
    cc_label = "cc_ge_{0}".format(result["min_cc"])
    base_name = "{0}_{1}_{2}".format(project_key, access_label, cc_label)

    csv_path = output_dir / "{0}_methods.csv".format(base_name)
    json_path = output_dir / "{0}_summary.json".format(base_name)

    with csv_path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(
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
            ]
        )
        for row in result["rows"]:
            writer.writerow(
                [
                    row["project"],
                    row["access"],
                    row["cc"],
                    row["is_constructor"],
                    row["method_fen"],
                    row["class_name_guess"],
                    row["method_name"],
                    row["params_types"],
                    row["file"],
                    row["line_number"],
                ]
            )

    summary_payload = {
        "project": result["project"],
        "project_root": result["project_root"],
        "source_roots": result["source_roots"],
        "min_cc": result["min_cc"],
        "access_levels": result["access_levels"],
        "include_constructors": result["include_constructors"],
        "scanned_java_files": result["scanned_java_files"],
        "recognized_methods": result["recognized_methods"],
        "matched_methods": result["matched_methods"],
        "csv_path": str(csv_path),
    }
    json_path.write_text(json.dumps(summary_payload, indent=2, ensure_ascii=False), encoding="utf-8")

    return {"csv": csv_path, "json": json_path}


def main() -> None:
    project_key = str(CONFIG["active_project"])
    result = analyze_project(project_key)
    outputs = write_outputs(result)

    print("=== 方法统计完成 ===")
    print("project: {0}".format(result["project"]))
    print("project_root: {0}".format(result["project_root"]))
    print("access_levels: {0}".format(", ".join(result["access_levels"]) or "all"))
    print("min_cc: >= {0}".format(result["min_cc"]))
    print("include_constructors: {0}".format(result["include_constructors"]))
    print("scanned_java_files: {0}".format(result["scanned_java_files"]))
    print("recognized_methods: {0}".format(result["recognized_methods"]))
    print("matched_methods: {0}".format(result["matched_methods"]))
    print("methods_csv: {0}".format(outputs["csv"]))
    print("summary_json: {0}".format(outputs["json"]))


if __name__ == "__main__":
    main()
