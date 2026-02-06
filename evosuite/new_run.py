#!/usr/bin/env python3
"""
精简版 EvoSuite + JaCoCo 运行脚本（stable Maven 版）。

特点：
- 仅针对单个 target-class 生成测试
- 支持 target-method / target-method-signature 方法过滤
- 自动尝试：方法签名 -> JVM 描述符 -> （可选）无过滤回退
- 输出 HTML + XML 覆盖率，并打印方法级行/指令/分支覆盖
"""

import argparse
import os
import re
import shutil
import subprocess
import sys
import urllib.request
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import List, Optional, Tuple

# ------------------------- Constants -------------------------
DEFAULT_PROJECTS = ["Lang", "Math", "Cli", "Codec", "Collections", "CSV"]
BASE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BASE_DIR / "project"
LIB_DIR = BASE_DIR / "lib"

STABLE_COORDS = {
    "Lang": ("commons-lang3", "3.14.0", "org.apache.commons"),
    "Math": ("commons-math3", "3.6.1", "org.apache.commons"),
    "Cli": ("commons-cli", "1.6.0", "commons-cli"),
    "Codec": ("commons-codec", "1.16.0", "commons-codec"),
    "Collections": ("commons-collections4", "4.4", "org.apache.commons"),
    "CSV": ("commons-csv", "1.10.0", "org.apache.commons"),
}

JUNIT_COORD = ("junit", "4.13.2", "junit")
HAMCREST_COORD = ("hamcrest-core", "1.3", "org.hamcrest")
JACOCO_VERSION = "0.8.8"
EVOSUITE_VERSION = "1.2.0"


# ------------------------- Utils -------------------------

def run_cmd(cmd: List[str], cwd: Optional[Path] = None, check: bool = True) -> subprocess.CompletedProcess:
    print("[*] exec:", " ".join(cmd))
    res = subprocess.run(cmd, cwd=str(cwd) if cwd else None, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if res.stdout:
        print(res.stdout.strip())
    if res.stderr:
        print(res.stderr.strip(), file=sys.stderr)
    if check and res.returncode != 0:
        raise RuntimeError("Command failed (rc={0}): {1}".format(res.returncode, " ".join(cmd)))
    return res


def run_cmd_logged(cmd: List[str], log_path: Path, cwd: Optional[Path] = None, check: bool = True) -> int:
    print("[*] exec:", " ".join(cmd))
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("w", encoding="utf-8") as f:
        proc = subprocess.Popen(cmd, cwd=str(cwd) if cwd else None, stdout=f, stderr=subprocess.STDOUT, text=True)
        rc = proc.wait()
    if check and rc != 0:
        raise RuntimeError("Command failed (rc={0}): {1}".format(rc, " ".join(cmd)))
    return rc


def fqcn_to_path(fqcn: str) -> str:
    return fqcn.replace(".", "/")


def find_first(root: Path, predicate):
    for dirpath, _, filenames in os.walk(root):
        for fn in filenames:
            p = Path(dirpath) / fn
            if predicate(p):
                return p
    return None


def has_evosuite_tests(tests_dir: Path) -> bool:
    return tests_dir.exists() and any(tests_dir.rglob("*.java"))


def find_evosuite_test_file(tests_dir: Path, target_class: str) -> Optional[Path]:
    simple = target_class.split(".")[-1]
    return find_first(tests_dir, lambda p: p.name == f"{simple}_ESTest.java")


def disable_evorunner_separate_classloader(test_file: Optional[Path]) -> bool:
    if (not test_file) or (not test_file.exists()):
        return False
    content = test_file.read_text(encoding="utf-8")
    if "separateClassLoader = true" not in content:
        return False
    test_file.write_text(content.replace("separateClassLoader = true", "separateClassLoader = false"), encoding="utf-8")
    return True


def count_tests_in_file(test_file: Optional[Path]) -> int:
    if (not test_file) or (not test_file.exists()):
        return 0
    content = test_file.read_text(encoding="utf-8", errors="ignore")
    return len(re.findall(r"\bvoid\s+test\d+\s*\(", content))


def count_method_calls_in_test(test_file: Optional[Path], target_class: str, method_name: str) -> int:
    if (not test_file) or (not test_file.exists()):
        return 0
    simple = target_class.split(".")[-1]
    pattern = r"\b{0}\s*\.\s*{1}\s*\(".format(re.escape(simple), re.escape(method_name))
    content = test_file.read_text(encoding="utf-8", errors="ignore")
    return len(re.findall(pattern, content))


def parse_evosuite_log(log_path: Path) -> Tuple[Optional[int], Optional[int]]:
    total_goals = None
    generated_tests = None
    if not log_path.exists():
        return total_goals, generated_tests
    for line in log_path.read_text(encoding="utf-8", errors="ignore").splitlines():
        if "Total number of test goals for DYNAMOSA" in line:
            try:
                total_goals = int(line.strip().split(":")[-1].strip())
            except Exception:
                pass
        if "Generated" in line and "tests" in line and "total length" in line:
            try:
                parts = line.strip().split("Generated", 1)[-1]
                num_str = parts.strip().split(" ", 1)[0]
                generated_tests = int(num_str)
            except Exception:
                pass
    return total_goals, generated_tests


def mark_ignored_tests_by_call(test_file: Optional[Path], target_class: str, method_name: str) -> int:
    if (not test_file) or (not test_file.exists()):
        return 0
    simple = target_class.split(".")[-1]
    call_pattern = re.compile(r"\b{0}\s*\.\s*{1}\s*\(".format(re.escape(simple), re.escape(method_name)))
    method_pattern = re.compile(r"^\s*public\s+void\s+(test\d+)\s*\(")

    lines = test_file.read_text(encoding="utf-8", errors="ignore").splitlines()
    has_ignore_import = any("org.junit.Ignore" in line for line in lines)

    output = []
    in_method = False
    brace_depth = 0
    started_body = False
    current = []
    current_has_call = False
    kept_count = 0

    def flush_current():
        nonlocal kept_count
        if not current:
            return
        if current_has_call:
            kept_count += 1
            output.extend(current)
            return
        # 标记忽略
        inserted = False
        for idx, line in enumerate(current):
            if method_pattern.match(line):
                output.extend(current[:idx])
                output.append("@Ignore(\"filtered\")")
                output.extend(current[idx:])
                inserted = True
                break
        if not inserted:
            output.extend(current)

    for line in lines:
        if not in_method:
            if method_pattern.match(line):
                in_method = True
                current = [line]
                brace_depth = line.count("{") - line.count("}")
                started_body = "{" in line
                current_has_call = bool(call_pattern.search(line))
                continue
            output.append(line)
            continue

        current.append(line)
        brace_depth += line.count("{") - line.count("}")
        if "{" in line:
            started_body = True
        if call_pattern.search(line):
            current_has_call = True
        if started_body and brace_depth <= 0:
            flush_current()
            in_method = False
            current = []
            current_has_call = False
            started_body = False

    if in_method:
        flush_current()

    if (not has_ignore_import) and any("@Ignore" in line for line in output):
        last_import = None
        package_line = None
        for i, line in enumerate(output):
            if line.startswith("package "):
                package_line = i
            if line.startswith("import "):
                last_import = i
        if last_import is not None:
            output.insert(last_import + 1, "import org.junit.Ignore;")
        elif package_line is not None:
            output.insert(package_line + 1, "import org.junit.Ignore;")
        else:
            output.insert(0, "import org.junit.Ignore;")

    test_file.write_text("\n".join(output) + "\n", encoding="utf-8")
    return kept_count


# ------------------------- Maven / Download -------------------------

def maven_url(group: str, artifact: str, version: str, classifier: Optional[str] = None) -> str:
    path = "/".join([group.replace(".", "/"), artifact, version])
    name = f"{artifact}-{version}"
    if classifier:
        name += f"-{classifier}"
    name += ".jar"
    return f"https://repo1.maven.org/maven2/{path}/{name}"


def download_artifact(group: str, artifact: str, version: str, classifier: Optional[str] = None) -> Path:
    LIB_DIR.mkdir(exist_ok=True)
    filename = f"{artifact}-{version}-{classifier}.jar" if classifier else f"{artifact}-{version}.jar"
    dest = LIB_DIR / filename
    if dest.exists():
        return dest
    url = maven_url(group, artifact, version, classifier)
    print(f"[i] Downloading {artifact}:{version}{' '+classifier if classifier else ''} ...")
    urllib.request.urlretrieve(url, dest)
    return dest


def unzip_jar(jar_path: Path, target_dir: Path):
    target_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(jar_path, "r") as zf:
        zf.extractall(target_dir)


def ensure_evosuite() -> Path:
    jar = LIB_DIR / f"evosuite-{EVOSUITE_VERSION}.jar"
    if jar.exists():
        return jar
    url = f"https://github.com/EvoSuite/evosuite/releases/download/v{EVOSUITE_VERSION}/evosuite-{EVOSUITE_VERSION}.jar"
    print(f"[i] Downloading EvoSuite {EVOSUITE_VERSION} ...")
    urllib.request.urlretrieve(url, jar)
    return jar


def ensure_junit_hamcrest() -> Tuple[Path, Path]:
    junit = download_artifact(JUNIT_COORD[2], JUNIT_COORD[0], JUNIT_COORD[1])
    hamcrest = download_artifact(HAMCREST_COORD[2], HAMCREST_COORD[0], HAMCREST_COORD[1])
    return junit, hamcrest


def ensure_jacoco() -> Tuple[Path, Path]:
    LIB_DIR.mkdir(exist_ok=True)
    agent = LIB_DIR / "jacocoagent.jar"
    cli = LIB_DIR / "jacococli.jar"
    if not agent.exists():
        print("[i] Downloading JaCoCo agent ...")
        urllib.request.urlretrieve(
            f"https://repo1.maven.org/maven2/org/jacoco/org.jacoco.agent/{JACOCO_VERSION}/org.jacoco.agent-{JACOCO_VERSION}-runtime.jar",
            agent,
        )
    if not cli.exists():
        print("[i] Downloading JaCoCo CLI ...")
        urllib.request.urlretrieve(
            f"https://repo1.maven.org/maven2/org/jacoco/org.jacoco.cli/{JACOCO_VERSION}/org.jacoco.cli-{JACOCO_VERSION}-nodeps.jar",
            cli,
        )
    return agent, cli


def prepare_stable_project(project: str) -> Tuple[Path, Path, str]:
    if project not in STABLE_COORDS:
        raise RuntimeError(f"Unknown project {project}")
    artifact, version, group = STABLE_COORDS[project]
    workdir = PROJECT_ROOT / f"{project}_stable"
    classes_dir = workdir / "classes"
    src_dir = workdir / "sources"
    version_file = workdir / ".version"
    expected_version = f"{group}:{artifact}:{version}"

    refresh = True
    if classes_dir.exists() and src_dir.exists() and version_file.exists():
        if version_file.read_text().strip() == expected_version:
            refresh = False

    if refresh:
        if workdir.exists():
            shutil.rmtree(workdir)
        workdir.mkdir(parents=True, exist_ok=True)
        jar = download_artifact(group, artifact, version)
        src_jar = download_artifact(group, artifact, version, classifier="sources")
        unzip_jar(jar, classes_dir)
        unzip_jar(src_jar, src_dir)
        version_file.write_text(expected_version, encoding="utf-8")
    else:
        print(f"[i] Using cached stable artifact for {project} at {workdir}")

    junit, hamcrest = ensure_junit_hamcrest()
    cp = os.pathsep.join([str(classes_dir), str(junit), str(hamcrest)])
    return workdir, src_dir, cp


# ------------------------- Method Parsing -------------------------

def extract_method_name(signature: str) -> str:
    head = signature.split("(")[0].strip()
    if not head:
        return ""
    parts = head.split()
    return parts[-1] if parts else ""


def method_name_from_filter(name: str) -> str:
    s = name.strip()
    if "(" in s:
        return s.split("(", 1)[0].strip()
    return s


def signature_to_evosuite_method(signature: str) -> Optional[str]:
    if not signature:
        return None
    s = signature.strip()
    if " throws " in s:
        s = s.split(" throws ", 1)[0].strip()
    if s.endswith(";"):
        s = s[:-1].strip()
    name = extract_method_name(s)
    if not name or "(" not in s or ")" not in s:
        return None
    params_str = s[s.find("(") + 1:s.rfind(")")]
    params = [p.strip() for p in params_str.split(",") if p.strip()]
    return f"{name}({','.join(params)})"


def java_type_to_descriptor(type_name: str) -> str:
    t = type_name.strip()
    if not t:
        return ""
    array_dim = 0
    while t.endswith("[]"):
        array_dim += 1
        t = t[:-2].strip()
    primitives = {
        "byte": "B",
        "char": "C",
        "double": "D",
        "float": "F",
        "int": "I",
        "long": "J",
        "short": "S",
        "boolean": "Z",
        "void": "V",
    }
    base = primitives.get(t) or ("L" + t.replace(".", "/") + ";")
    return ("[" * array_dim) + base


def signature_to_descriptor_method(signature: str) -> Optional[str]:
    if not signature:
        return None
    s = signature.strip()
    if " throws " in s:
        s = s.split(" throws ", 1)[0].strip()
    if s.endswith(";"):
        s = s[:-1].strip()
    if "(" not in s or ")" not in s:
        return None
    head = s.split("(", 1)[0].strip()
    parts = head.split()
    if len(parts) < 2:
        return None
    method_name = parts[-1]
    return_type = parts[-2]
    params_str = s[s.find("(") + 1:s.rfind(")")]
    params = [p.strip() for p in params_str.split(",") if p.strip()]
    params_desc = "".join(java_type_to_descriptor(p) for p in params)
    ret_desc = java_type_to_descriptor(return_type)
    return f"{method_name}({params_desc}){ret_desc}"


def run_javap(classes_dir: Path, target_fqcn: str) -> list:
    cmd = ["javap", "-classpath", str(classes_dir), "-c", "-l", target_fqcn]
    res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if res.returncode != 0:
        raise RuntimeError(f"javap failed: {res.stderr}")
    return res.stdout.splitlines()


def parse_javap(lines: list) -> list:
    methods = []
    cur = None
    in_code = False
    in_lnt = False

    for raw in lines:
        line = raw.rstrip("\n")
        is_method_header = (
            (not in_code)
            and ("(" in line)
            and line.strip().endswith(";")
            and (not line.strip().startswith("Compiled from"))
            and (not line.strip().startswith("LineNumberTable"))
            and (not line.strip().startswith("Code:"))
        )
        if is_method_header:
            if cur:
                methods.append(cur)
            cur = {"signature": line.strip(), "line_table": {}}
            in_code = False
            in_lnt = False
            continue

        if cur is None:
            continue

        if line.strip() == "Code:":
            in_code = True
            in_lnt = False
            continue

        if line.strip() == "LineNumberTable:":
            in_lnt = True
            in_code = False
            continue

        if in_lnt:
            s = line.strip()
            if s.startswith("line "):
                try:
                    s2 = s[len("line "):]
                    parts = s2.split(":")
                    lno = int(parts[0].strip())
                    pc = int(parts[1].strip())
                    cur["line_table"][pc] = lno
                except Exception:
                    pass
            continue

    if cur:
        methods.append(cur)
    return methods


def collect_method_lines(methods: list, method_names=None, method_signatures=None) -> dict:
    method_names = method_names or []
    method_signatures = method_signatures or []
    target_names = set(method_names)
    target_sigs = set(method_signatures)
    method_lines = {key: set() for key in (target_sigs or target_names)}

    for m in methods:
        sig = m.get("signature", "")
        name = extract_method_name(sig)
        lines = set(m.get("line_table", {}).values())
        if target_sigs:
            if sig in target_sigs:
                method_lines.setdefault(sig, set()).update(lines)
        else:
            if name in target_names:
                method_lines.setdefault(name, set()).update(lines)
    return method_lines


def load_line_coverage(xml_report: Path, target_fqcn: str) -> dict:
    target_path = fqcn_to_path(target_fqcn)
    target_pkg = target_path.rsplit("/", 1)[0] if "/" in target_path else target_path
    simple = target_fqcn.split(".")[-1]
    source_file_name = simple + ".java"

    tree = ET.parse(xml_report)
    root = tree.getroot()
    coverage = {}

    def collect_from_pkg(pkg):
        for sf in pkg.findall("sourcefile"):
            if sf.get("name") != source_file_name:
                continue
            for line in sf.findall("line"):
                nr = line.get("nr")
                mi = line.get("mi")
                ci = line.get("ci")
                mb = line.get("mb")
                cb = line.get("cb")
                try:
                    coverage[int(nr)] = {
                        "mi": int(mi) if mi is not None else 0,
                        "ci": int(ci) if ci is not None else 0,
                        "mb": int(mb) if mb is not None else 0,
                        "cb": int(cb) if cb is not None else 0,
                    }
                except Exception:
                    pass

    matched = False
    for pkg in root.findall("package"):
        pkg_name = pkg.get("name") or ""
        if pkg_name and (pkg_name == target_pkg):
            collect_from_pkg(pkg)
            matched = True
            break

    if not matched:
        for pkg in root.findall("package"):
            collect_from_pkg(pkg)

    return coverage


# ------------------------- Core Flow -------------------------

def build_method_filters(classes_dir: Path, target_class: str, target_method: Optional[str],
                         target_method_signature: Optional[str], method_filter_mode: str):
    resolved_method_list = None
    descriptor_method_list = None

    if method_filter_mode in ("name", "post-filter"):
        return None, None

    if target_method_signature:
        resolved_method_list = signature_to_evosuite_method(target_method_signature) or target_method_signature.strip()
        descriptor_method_list = signature_to_descriptor_method(target_method_signature)
    elif target_method:
        methods_for_filters = parse_javap(run_javap(classes_dir, target_class))
        candidates = []
        descriptor_candidates = []
        for m in methods_for_filters:
            sig = m.get("signature", "")
            if extract_method_name(sig) == target_method:
                evo_sig = signature_to_evosuite_method(sig)
                if evo_sig:
                    candidates.append(evo_sig)
                desc_sig = signature_to_descriptor_method(sig)
                if desc_sig:
                    descriptor_candidates.append(desc_sig)
        if candidates:
            resolved_method_list = ":".join(sorted(set(candidates)))
            print("[INFO] 解析到方法签名列表：", resolved_method_list)
        if descriptor_candidates:
            descriptor_method_list = ":".join(sorted(set(descriptor_candidates)))
            print("[INFO] 解析到方法描述符列表：", descriptor_method_list)

    return resolved_method_list, descriptor_method_list


def run_evosuite_for_class(workdir: Path, evosuite_jar: Path, cp: str, classes_dir: Path,
                           target_class: str, time_limit: int, seed: Optional[int], criteria: str,
                           method_list: Optional[str] = None, method_name: Optional[str] = None,
                           log_path: Optional[Path] = None):
    cmd = [
        "java", "-Xmx2g", "-jar", str(evosuite_jar),
        "-class", target_class,
        "-target", str(classes_dir),
        "-projectCP", cp,
        "-base_dir", str(workdir),
        f"-Dsearch_budget={time_limit}",
        f"-Dglobal_timeout={time_limit}",
        "-criterion", criteria,
    ]
    if seed is not None:
        cmd.append(f"-seed={seed}")
    if method_list:
        cmd.append(f"-Dtarget_method_list={method_list}")
    elif method_name:
        cmd.append(f"-Dtarget_method={method_name}")
    if log_path:
        run_cmd_logged(cmd, log_path=log_path, cwd=workdir)
    else:
        run_cmd(cmd, cwd=workdir)


def compile_tests(tests_dir: Path, test_bin: Path, cp: str):
    java_files = list(tests_dir.rglob("*.java"))
    if not java_files:
        raise RuntimeError(f"No EvoSuite tests generated in {tests_dir}")
    test_bin.mkdir(exist_ok=True)
    cmd = ["javac", "-g", "-d", str(test_bin), "-cp", cp] + [str(f) for f in java_files]
    run_cmd(cmd)


def test_class_from_file(tests_dir: Path, test_file: Path) -> str:
    rel = test_file.relative_to(tests_dir).with_suffix("")
    return ".".join(rel.parts)


def run_coverage(workdir: Path, jacoco_agent: Path, jacoco_cli: Path, cp: str,
                 test_class: str, class_files: Path, src_dir: Path,
                 target_class: str, target_method: Optional[str], target_method_signature: Optional[str]):
    exec_file = workdir / "jacoco.exec"
    agent_opt = f"-javaagent:{jacoco_agent}=destfile={exec_file}"
    cmd = ["java", agent_opt, "-cp", cp, "org.junit.runner.JUnitCore", test_class]
    print("[*] exec:", " ".join(cmd))
    res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if res.stdout:
        print(res.stdout.strip())
    if res.stderr:
        print(res.stderr.strip(), file=sys.stderr)
    if res.returncode != 0:
        print(f"[!] JUnit exited with code {res.returncode}, continuing to generate coverage report")

    report_dir = workdir / "jacoco-report"
    report_dir.mkdir(exist_ok=True)
    xml_report = report_dir / "report.xml"
    cmd_report = [
        "java", "-jar", str(jacoco_cli), "report", str(exec_file),
        "--classfiles", str(class_files),
        "--sourcefiles", str(src_dir),
        "--html", str(report_dir),
        "--xml", str(xml_report),
    ]
    run_cmd(cmd_report)
    print(f"[✓] Coverage report: {report_dir}/index.html")

    if not xml_report.exists():
        return
    if not (target_method or target_method_signature):
        return

    coverage_map = load_line_coverage(xml_report, target_class)
    methods = parse_javap(run_javap(class_files, target_class))
    method_signatures = [target_method_signature] if target_method_signature else []
    method_names = [method_name_from_filter(target_method)] if target_method else []
    method_lines_map = collect_method_lines(methods, method_names, method_signatures)

    for name in (method_signatures or method_names):
        lines = method_lines_map.get(name, set())
        if not lines:
            print("[WARN] 未找到方法行号：", name)
            continue

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

        total = len(lines)
        known_total = total - unknown
        if known_total <= 0:
            print("[WARN] 方法覆盖率无法计算：", name)
            continue

        line_covered = fully_covered + partially_covered
        line_ratio = (line_covered / float(known_total)) * 100.0
        instr_ratio = (covered_instr / float(total_instr) * 100.0) if total_instr > 0 else 0.0
        branch_ratio = (covered_branch / float(total_branch) * 100.0) if total_branch > 0 else 0.0

        print(
            "[INFO] 方法行覆盖率 {0}: {1:.1f}% (fully={2}, partial={3}, missed={4}, total={5}, unknown={6})".format(
                name, line_ratio, fully_covered, partially_covered, missed, known_total, unknown
            )
        )
        print(
            "[INFO] 方法指令覆盖率 {0}: {1:.1f}% (covered={2}, total={3})".format(
                name, instr_ratio, covered_instr, total_instr
            )
        )
        print(
            "[INFO] 方法分支覆盖率 {0}: {1:.1f}% (covered={2}, total={3})".format(
                name, branch_ratio, covered_branch, total_branch
            )
        )


def is_low_goals(total_goals: Optional[int], generated_tests: Optional[int], min_goals: int,
                 min_generated_tests: int) -> bool:
    if total_goals is not None and total_goals <= min_goals:
        return True
    if generated_tests is not None and generated_tests <= min_generated_tests:
        return True
    return False


def main():
    ap = argparse.ArgumentParser(description="Minimal EvoSuite runner (stable Maven artifacts)")
    ap.add_argument("--project", default="Lang", choices=DEFAULT_PROJECTS, help="项目名（默认 Lang）")
    ap.add_argument("--time-limit", type=int, default=60, help="EvoSuite 搜索预算（秒）")
    ap.add_argument("--seed", type=int, default=None, help="随机种子（可选，不传则使用 EvoSuite 默认）")
    ap.add_argument("--target-class", required=True, help="目标类全限定名")
    ap.add_argument("--target-method", default=None, help="目标方法名")
    ap.add_argument("--target-method-signature", default=None, help="目标方法签名（javap 格式）")
    ap.add_argument("--no-fallback", action="store_true", help="方法过滤失败时不回退到无过滤生成")
    ap.add_argument(
        "--method-filter-mode",
        choices=["signature", "name", "post-filter"],
        default="signature",
        help="方法过滤模式：signature(默认，签名列表) / name(仅方法名) / post-filter(类级生成后过滤)",
    )
    ap.add_argument(
        "--evosuite-criteria",
        default="LINE:BRANCH:EXCEPTION:OUTPUT:METHOD:METHODNOEXCEPTION:CBRANCH",
        help="EvoSuite 覆盖准则（冒号分隔）。默认不包含 WEAKMUTATION 以避免 NPE。",
    )
    ap.add_argument("--min-tests", type=int, default=1, help="最少测试数（低于则尝试提高预算重跑）")
    ap.add_argument("--min-tests-retry-mult", type=int, default=3, help="最少测试不足时的预算放大倍数")
    ap.add_argument("--min-goals", type=int, default=2, help="方法过滤后最少测试目标数（低于则触发重试）")
    ap.add_argument("--min-generated-tests", type=int, default=1, help="方法过滤后最少生成测试数（低于则触发重试）")
    args = ap.parse_args()

    workdir, src_dir, cp_base = prepare_stable_project(args.project)
    classes_dir = workdir / "classes"

    evosuite_jar = ensure_evosuite()
    jacoco_agent, jacoco_cli = ensure_jacoco()

    tests_dir = workdir / "evosuite-tests"
    if tests_dir.exists():
        shutil.rmtree(tests_dir)

    resolved_method_list, descriptor_method_list = build_method_filters(
        classes_dir, args.target_class, args.target_method, args.target_method_signature, args.method_filter_mode
    )

    run_evosuite_for_class(
        workdir, evosuite_jar, cp_base, classes_dir, args.target_class, args.time_limit, args.seed,
        args.evosuite_criteria,
        method_list=resolved_method_list or (args.target_method_signature if args.method_filter_mode != "post-filter" else None),
        method_name=args.target_method if (not resolved_method_list and args.method_filter_mode == "name") else None,
        log_path=workdir / "evosuite.log",
    )

    if (args.target_method or args.target_method_signature) and args.method_filter_mode != "post-filter":
        total_goals, generated_tests = parse_evosuite_log(workdir / "evosuite.log")
        if is_low_goals(total_goals, generated_tests, args.min_goals, args.min_generated_tests):
            if descriptor_method_list and args.method_filter_mode == "signature":
                print("[WARN] 方法过滤后目标过少，尝试使用 JVM 描述符格式重跑 EvoSuite。")
                if tests_dir.exists():
                    shutil.rmtree(tests_dir)
                run_evosuite_for_class(
                    workdir, evosuite_jar, cp_base, classes_dir, args.target_class, args.time_limit, args.seed,
                    args.evosuite_criteria,
                    method_list=descriptor_method_list,
                    log_path=workdir / "evosuite_descriptor.log",
                )
                total_goals, generated_tests = parse_evosuite_log(workdir / "evosuite_descriptor.log")

            if is_low_goals(total_goals, generated_tests, args.min_goals, args.min_generated_tests):
                if args.no_fallback:
                    print("[WARN] 方法过滤目标不足，但已禁用回退。")
                else:
                    print("[WARN] 方法过滤仍无效，尝试不使用方法过滤重跑 EvoSuite。")
                    if tests_dir.exists():
                        shutil.rmtree(tests_dir)
                    run_evosuite_for_class(
                        workdir, evosuite_jar, cp_base, classes_dir, args.target_class, args.time_limit, args.seed,
                        args.evosuite_criteria,
                        log_path=workdir / "evosuite_fallback.log",
                    )

    test_file = find_evosuite_test_file(tests_dir, args.target_class)
    if args.method_filter_mode == "post-filter" and args.target_method:
        kept = mark_ignored_tests_by_call(test_file, args.target_class, args.target_method)
        if kept == 0:
            raise RuntimeError("post-filter 模式下未找到调用目标方法的测试")
        print("[INFO] post-filter 保留测试数：", kept)
    test_count = count_tests_in_file(test_file)
    call_count = count_method_calls_in_test(test_file, args.target_class, args.target_method) if args.target_method else 0
    if (args.target_method or args.target_method_signature) and (test_count < args.min_tests):
        print("[WARN] 生成测试数过少({0})，提高预算重跑。".format(test_count))
        if tests_dir.exists():
            shutil.rmtree(tests_dir)
        run_evosuite_for_class(
            workdir, evosuite_jar, cp_base, classes_dir, args.target_class,
            args.time_limit * args.min_tests_retry_mult,
            args.seed,
            args.evosuite_criteria,
            method_list=resolved_method_list or (args.target_method_signature if args.method_filter_mode != "post-filter" else None),
            method_name=args.target_method if (not resolved_method_list and args.method_filter_mode == "name") else None,
            log_path=workdir / "evosuite_retry.log",
        )
        test_file = find_evosuite_test_file(tests_dir, args.target_class)
        test_count = count_tests_in_file(test_file)
        call_count = count_method_calls_in_test(test_file, args.target_class, args.target_method) if args.target_method else 0

    if (args.target_method or args.target_method_signature) and (not has_evosuite_tests(tests_dir)) and descriptor_method_list and args.method_filter_mode == "signature":
        print("[WARN] 方法过滤未生成测试，尝试使用 JVM 描述符格式重跑。")
        run_evosuite_for_class(
            workdir, evosuite_jar, cp_base, classes_dir, args.target_class, args.time_limit, args.seed,
            args.evosuite_criteria,
            method_list=descriptor_method_list,
            log_path=workdir / "evosuite_descriptor.log",
        )

    if (args.target_method or args.target_method_signature) and (not has_evosuite_tests(tests_dir)):
        if args.no_fallback:
            raise RuntimeError("未生成 EvoSuite 测试（已禁用无过滤回退）")
        print("[WARN] 未生成测试或测试为空，尝试不使用方法过滤重新生成。")
        run_evosuite_for_class(
            workdir, evosuite_jar, cp_base, classes_dir, args.target_class, args.time_limit, args.seed,
            args.evosuite_criteria,
            log_path=workdir / "evosuite_fallback.log",
        )

    if (args.target_method or args.target_method_signature) and (not args.no_fallback) and args.method_filter_mode != "post-filter":
        test_file = find_evosuite_test_file(tests_dir, args.target_class)
        test_count = count_tests_in_file(test_file)
        call_count = count_method_calls_in_test(test_file, args.target_class, args.target_method) if args.target_method else 0
        if (test_count < args.min_tests) or (args.target_method and call_count == 0):
            print("[WARN] 方法过滤结果不足（tests={0}, calls={1}），回退为类级生成。".format(test_count, call_count))
            if tests_dir.exists():
                shutil.rmtree(tests_dir)
            run_evosuite_for_class(
                workdir, evosuite_jar, cp_base, classes_dir, args.target_class, args.time_limit, args.seed,
                args.evosuite_criteria,
                log_path=workdir / "evosuite_method_retry.log",
            )

    if not has_evosuite_tests(tests_dir):
        raise RuntimeError("未生成 EvoSuite 测试")

    test_file = find_evosuite_test_file(tests_dir, args.target_class)
    if disable_evorunner_separate_classloader(test_file):
        print("[INFO] 已禁用 EvoRunner separateClassLoader 以增强 JaCoCo 覆盖记录。")

    test_bin = workdir / "evosuite-bin"
    if test_bin.exists():
        shutil.rmtree(test_bin)

    cp_compile = os.pathsep.join([str(classes_dir), str(evosuite_jar), cp_base])
    compile_tests(tests_dir, test_bin, cp_compile)

    if not test_file:
        raise RuntimeError("未找到 *_ESTest.java")

    test_class = test_class_from_file(tests_dir, test_file)
    cp_run = os.pathsep.join([str(classes_dir), str(test_bin), str(evosuite_jar), cp_base])

    run_coverage(
        workdir,
        jacoco_agent,
        jacoco_cli,
        cp_run,
        test_class,
        classes_dir,
        src_dir,
        args.target_class,
        args.target_method,
        args.target_method_signature,
    )


if __name__ == "__main__":
    main()
