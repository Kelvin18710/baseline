#!/usr/bin/env python3
"""
Randoop + JaCoCo 自动化脚本。

模式
----
- stable（默认）：从 Maven Central 下载稳定版 jar（含 sources），不依赖 defects4j。
- d4j：沿用 Defects4J bug1 fixed 版本。

特性
----
* Lang/Math/Cli/Codec/Collections 一键生成 Randoop 测试并产出 Jacoco 覆盖率报告。
* 缺少依赖工具（Randoop、Jacoco、Junit/Hamcrest）时会自动下载到 `baseline/randoop/lib`。

用法
----
python3 run.py                                           # 默认 stable 模式跑全部项目
python3 run.py --project Lang --time-limit 60            # 只跑 Lang，稳定版
python3 run.py --mode d4j --project Lang                 # 切回 defects4j 模式
python3 run.py --mode humaneval --time-limit 30          # 跑 HumanEval-Java（优先 baseline/randoop/project/human-eval-java）
python3 run.py --mode humaneval --class-limit 10         # 仅采样前 10 个 humaneval.buggy 类
python3 run.py --mode humaneval --humaneval-path /path   # 自定义 humaneval 目录
"""

import argparse
import os
import shutil
import subprocess
import sys
import urllib.request
import zipfile
import xml.etree.ElementTree as ET
import re
from pathlib import Path
from typing import List, Optional, Tuple

# ------------------------- 常量 -------------------------
DEFAULT_PROJECTS = ["Lang", "Math", "Cli", "Codec", "Collections"]
BUG_ID = 1
VERSION = "f"  # 用于 d4j 模式
BASE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BASE_DIR / "project"
LIB_DIR = BASE_DIR / "lib"

# HumanEval-Java 默认路径
HUMAN_EVAL_LOCAL = (BASE_DIR / "project" / "human-eval-java").resolve()
HUMAN_EVAL_FALLBACK = (BASE_DIR.parent.parent / "symbolic_tool" / "test" / "human-eval-java").resolve()
# 稳定版坐标（artifactId, version, groupId）
STABLE_COORDS = {
    "Lang": ("commons-lang3", "3.14.0", "org.apache.commons"),
    "Math": ("commons-math3", "3.6.1", "org.apache.commons"),
    "Cli": ("commons-cli", "1.6.0", "commons-cli"),
    "Codec": ("commons-codec", "1.16.0", "commons-codec"),
    "Collections": ("commons-collections4", "4.4", "org.apache.commons"),
}

JUNIT_COORD = ("junit", "4.13.2", "junit")
HAMCREST_COORD = ("hamcrest-core", "1.3", "org.hamcrest")
EXCLUDE_CLASSES = {
    # Lang：会触发 Randoop 3.1.x 的类路径解析问题
    "org.apache.commons.lang3.DoubleRange",
    "org.apache.commons.lang3.IntegerRange",
    "org.apache.commons.lang3.LongRange",
    "org.apache.commons.lang3.NumberRange",
}


# ------------------------- 辅助函数 ---------------------------
def run_cmd(cmd: List[str], cwd: Optional[Path] = None, check: bool = True) -> str:
    print(f"[*] exec: {' '.join(cmd)}" + (f" (cwd={cwd})" if cwd else ""))
    res = subprocess.run(cmd, cwd=str(cwd) if cwd else None, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if check and res.returncode != 0:
        raise RuntimeError(f"Command failed: {' '.join(cmd)}\nstdout:\n{res.stdout}\nstderr:\n{res.stderr}")
    if res.stdout:
        out = res.stdout.strip()
        if out:
            print(out)
    return res.stdout.strip()


def fqcn_to_path(fqcn: str) -> str:
    return fqcn.replace(".", "/")


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
            cur = {
                "signature": line.strip(),
                "line_table": {}
            }
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


def filter_randoop_tests_by_method(test_src_dir: Path, target_class: str, target_method: str) -> int:
    simple = target_class.split(".")[-1]
    pattern = re.compile(r"\b{0}\s*\.\s*{1}\s*\(".format(re.escape(simple), re.escape(target_method)))
    kept_total = 0

    for test_file in test_src_dir.glob("*.java"):
        content = test_file.read_text(encoding="utf-8")
        lines = content.splitlines()
    output = []
        in_method = False
        brace_depth = 0
        method_lines = []
        method_has_call = False
        pending_annotations = []
    kept_in_file = 0

        for line in lines:
            if not in_method:
                if line.strip().startswith("@Test"):
                    pending_annotations.append(line)
                    continue
                if re.search(r"public void test\d+\s*\(", line):
                    in_method = True
                    brace_depth = line.count("{") - line.count("}")
                    method_lines = pending_annotations + [line]
                    pending_annotations = []
                    method_has_call = bool(pattern.search(line))
                    if brace_depth == 0:
                        brace_depth = 1
                    continue
                output.extend(pending_annotations)
                pending_annotations = []
                output.append(line)
                continue

            method_lines.append(line)
            method_has_call = method_has_call or bool(pattern.search(line))
            brace_depth += line.count("{") - line.count("}")
            if brace_depth <= 0:
                if method_has_call:
                    output.extend(method_lines)
                    kept_total += 1
                    kept_in_file += 1
                in_method = False

        if kept_in_file == 0:
            if pattern.search(content):
                kept_total += 1
                kept_in_file = 1

        if output and any("public class" in ln for ln in output):
            test_file.write_text("\n".join(output) + "\n", encoding="utf-8")
        else:
            test_file.unlink(missing_ok=True)

    return kept_total


def resolve_humaneval_path(custom: Optional[Path]) -> Path:
    if custom:
        p = custom.resolve()
        if not p.exists():
            raise RuntimeError(f"HumanEval-Java path not found: {p}")
        return p
    if HUMAN_EVAL_LOCAL.exists():
        return HUMAN_EVAL_LOCAL
    if HUMAN_EVAL_FALLBACK.exists():
        return HUMAN_EVAL_FALLBACK
    raise RuntimeError(f"HumanEval-Java path not found. Tried {HUMAN_EVAL_LOCAL} and {HUMAN_EVAL_FALLBACK}")


def defects4j_export(prop: str, workdir: Path) -> str:
    return run_cmd(["defects4j", "export", "-p", prop, "-w", str(workdir)])


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
    with zipfile.ZipFile(jar_path, 'r') as zf:
        zf.extractall(target_dir)


def infer_d4j_home(cp_hint: Optional[str]) -> Optional[Path]:
    env = os.environ.get("D4J_HOME") or os.environ.get("DEFECTS4J_HOME")
    if env:
        return Path(env)

    which = shutil.which("defects4j")
    if which:
        p = Path(which).resolve()
        try:
            idx = p.parts.index("framework")
            home = Path(*p.parts[:idx])
            if (home / "framework").exists():
                return home
        except ValueError:
            pass

    if cp_hint:
        for part in cp_hint.split(os.pathsep):
            path = Path(part)
            if "defects4j" in path.parts:
                try:
                    idx = path.parts.index("defects4j")
                    home = Path(*path.parts[:idx + 1])
                    if (home / "framework").exists():
                        return home
                except ValueError:
                    continue
    return None


def ensure_jacoco_local() -> Tuple[Path, Path]:
    LIB_DIR.mkdir(exist_ok=True)
    agent = LIB_DIR / "jacocoagent.jar"
    cli = LIB_DIR / "jacococli.jar"
    if not agent.exists():
        print("[i] Downloading JaCoCo agent ...")
        urllib.request.urlretrieve("https://repo1.maven.org/maven2/org/jacoco/org.jacoco.agent/0.8.8/org.jacoco.agent-0.8.8-runtime.jar", agent)
    if not cli.exists():
        print("[i] Downloading JaCoCo CLI ...")
        urllib.request.urlretrieve("https://repo1.maven.org/maven2/org/jacoco/org.jacoco.cli/0.8.8/org.jacoco.cli-0.8.8-nodeps.jar", cli)
    return agent, cli


def ensure_randoop(cp_hint: Optional[str]) -> Path:
    jar = LIB_DIR / "randoop-all-4.3.0.jar"
    if jar.exists():
        return jar
    LIB_DIR.mkdir(exist_ok=True)
    url = "https://github.com/randoop/randoop/releases/download/v4.3.0/randoop-all-4.3.0.jar"
    print("[i] Downloading Randoop 4.3.0 ...")
    urllib.request.urlretrieve(url, jar)
    return jar


def ensure_tools(cp_hint: Optional[str]) -> tuple[Path, Path, Path]:
    randoop = ensure_randoop(cp_hint)
    jacoco_agent = None
    jacoco_cli = None
    d4j_home = infer_d4j_home(cp_hint)
    if d4j_home:
        lib_dir = Path(d4j_home) / "framework" / "lib"
        jacoco_agent = next((p for p in lib_dir.rglob("jacocoagent*.jar")), None)
        jacoco_cli = next((p for p in lib_dir.rglob("jacococli*.jar")), None)
    if not (jacoco_agent and jacoco_cli):
        jacoco_agent, jacoco_cli = ensure_jacoco_local()
    return randoop, jacoco_agent, jacoco_cli


def ensure_junit_hamcrest() -> Tuple[Path, Path]:
    junit = download_artifact(JUNIT_COORD[2], JUNIT_COORD[0], JUNIT_COORD[1])
    hamcrest = download_artifact(HAMCREST_COORD[2], HAMCREST_COORD[0], HAMCREST_COORD[1])
    return junit, hamcrest


def abs_classpath(cp_str: str, workdir: Path) -> str:
    parts = cp_str.split(os.pathsep)
    abs_parts = []
    for p in parts:
        if not p:
            continue
        path = Path(p)
        if not path.is_absolute():
            path = workdir / p
        abs_parts.append(str(path.resolve()))
    return os.pathsep.join(abs_parts)


def checkout_project(project: str, workdir: Path):
    if workdir.exists():
        print(f"[i] Workspace exists, skip checkout: {workdir}")
        return
    workdir.parent.mkdir(parents=True, exist_ok=True)
    run_cmd(["defects4j", "checkout", "-p", project, "-v", f"{BUG_ID}{VERSION}", "-w", str(workdir)])


def compile_project(workdir: Path):
    run_cmd(["defects4j", "compile", "-w", str(workdir)])


def build_classlist(bin_dir: Path, out_file: Path, only_prefix: Optional[str] = None):
    classes = []
    for cls_file in bin_dir.rglob("*.class"):
        rel = cls_file.relative_to(bin_dir)
        if rel.parts and rel.parts[0].upper() == "META-INF":
            continue
        if "$" in rel.name:
            continue  # 跳过内部类/匿名类
        if rel.name == "package-info.class":
            continue
        fqcn = ".".join(rel.with_suffix("").parts)
        if only_prefix and not fqcn.startswith(only_prefix):
            continue
        if fqcn in EXCLUDE_CLASSES:
            continue
        classes.append(fqcn)
    if not classes:
        raise RuntimeError(f"No .class files found under {bin_dir}")
    out_file.write_text("\n".join(sorted(classes)), encoding="utf-8")
    print(f"[+] classlist -> {out_file} ({len(classes)} classes)")


def run_randoop(workdir: Path, randoop_jar: Path, cp_test: str, classlist: Path, time_limit: int, seed: int) -> Path:
    out_dir = workdir / "randoop-tests"
    out_dir.mkdir(exist_ok=True)
    cmd = [
        "java", "-Xmx4g",
        "-classpath", f"{randoop_jar}:{cp_test}",
        "randoop.main.Main", "gentests",
        f"--classlist={classlist}",
        f"--time-limit={time_limit}",
        "--usethreads",
        "--call-timeout=1",
        "--junit-output-dir", str(out_dir),
        f"--randomseed={seed}",
    ]
    run_cmd(cmd, cwd=workdir)
    return out_dir


def compile_tests(test_src_dir: Path, test_bin_dir: Path, cp: str):
    java_files = list(test_src_dir.glob("*.java"))
    if not java_files:
        raise RuntimeError(f"No Randoop tests generated in {test_src_dir}")
    test_bin_dir.mkdir(exist_ok=True)
    cmd = [
        "javac", "-g",
        "-d", str(test_bin_dir),
        "-cp", f"{cp}",
    ] + [str(f) for f in java_files]
    run_cmd(cmd)


def collect_test_classes(test_bin_dir: Path) -> List[str]:
    names = []
    for cls in test_bin_dir.rglob("*.class"):
        rel = cls.relative_to(test_bin_dir)
        if "$" in rel.name:
            continue
        names.append(".".join(rel.with_suffix("").parts))
    if not names:
        raise RuntimeError("No compiled test classes found")
    return names


def run_coverage(workdir: Path, jacoco_agent: Path, jacoco_cli: Path, cp: str, test_classes: List[str],
                 class_files: Path, src_dir: Path, target_class: Optional[str] = None,
                 target_method: Optional[str] = None, target_method_signature: Optional[str] = None):
    exec_file = workdir / "jacoco.exec"
    agent_opt = f"-javaagent:{jacoco_agent}=destfile={exec_file}"
    cmd = [
        "java", agent_opt,
        "-cp", cp,
        "org.junit.runner.JUnitCore",
    ] + test_classes
    run_cmd(cmd)

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

    if target_class and target_method and xml_report.exists():
        coverage_map = load_line_coverage(xml_report, target_class)
        methods = parse_javap(run_javap(class_files, target_class))
        method_signatures = [target_method_signature] if target_method_signature else []
        method_names = [method_name_from_filter(target_method)]
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


# ------------------------- 流程 -------------------------
def limit_classlist(classlist_file: Path, class_limit: Optional[int]) -> Path:
    if not class_limit:
        return classlist_file
    classes = classlist_file.read_text().splitlines()
    selected = classes[:class_limit]
    limited_file = classlist_file.with_name(f"{classlist_file.stem}_top{class_limit}{classlist_file.suffix}")
    limited_file.write_text("\n".join(selected), encoding="utf-8")
    print(f"[i] Limited to {len(selected)} classes -> {limited_file}")
    return limited_file


def filter_classlist_to_target(classlist_file: Path, target_class: str) -> Path:
    classes = classlist_file.read_text().splitlines()
    if target_class not in classes:
        raise RuntimeError(f"Target class not found in classlist: {target_class}")
    target_file = classlist_file.with_name(f"{classlist_file.stem}_target{classlist_file.suffix}")
    target_file.write_text(target_class + "\n", encoding="utf-8")
    print(f"[i] Using target class only -> {target_file}")
    return target_file


def process_project_d4j(project: str, time_limit: int, seed: int, class_limit: Optional[int],
                        target_class: Optional[str], target_method: Optional[str],
                        target_method_signature: Optional[str]):
    print(f"\n===== Project {project} (bug {BUG_ID}{VERSION}) =====")
    workdir = PROJECT_ROOT / f"{project}_{BUG_ID}_fix"

    checkout_project(project, workdir)
    compile_project(workdir)

    src_rel = defects4j_export("dir.src.classes", workdir).strip()
    bin_rel = defects4j_export("dir.bin.classes", workdir).strip()
    cp_test_rel = defects4j_export("cp.test", workdir).strip()

    src_dir = (workdir / src_rel).resolve()
    bin_dir = (workdir / bin_rel).resolve()
    cp_test = abs_classpath(cp_test_rel, workdir)

    randoop_jar, jacoco_agent, jacoco_cli = ensure_tools(cp_test)

    classlist_file = workdir / "classlist.txt"
    build_classlist(bin_dir, classlist_file)
    if target_class:
        classlist_file = filter_classlist_to_target(classlist_file, target_class)
    else:
        classlist_file = limit_classlist(classlist_file, class_limit)

    test_src_dir = run_randoop(workdir, randoop_jar, cp_test, classlist_file, time_limit, seed)
    if target_class and target_method:
        kept = filter_randoop_tests_by_method(test_src_dir, target_class, target_method)
        if kept == 0:
            print("[WARN] 未找到调用目标方法的测试：", target_method)
    test_bin_dir = workdir / "randoop-bin"
    compile_tests(test_src_dir, test_bin_dir, f"{cp_test}:{randoop_jar}:{test_bin_dir}")
    test_classes = collect_test_classes(test_bin_dir)
    full_cp = f"{cp_test}:{test_bin_dir}"
    run_coverage(
        workdir,
        jacoco_agent,
        jacoco_cli,
        full_cp,
        test_classes,
        bin_dir,
        src_dir,
        target_class=target_class,
        target_method=target_method,
        target_method_signature=target_method_signature,
    )


def prepare_stable_project(project: str) -> Tuple[Path, Path, str]:
    if project not in STABLE_COORDS:
        raise RuntimeError(f"Unknown project {project} for stable mode")
    artifact, version, group = STABLE_COORDS[project]
    workdir = PROJECT_ROOT / f"{project}_stable"
    classes_dir = workdir / "classes"
    src_dir = workdir / "sources"
    version_file = workdir / ".version"
    expected_version = f"{group}:{artifact}:{version}"

    need_refresh = True
    if classes_dir.exists() and src_dir.exists() and version_file.exists():
        if version_file.read_text().strip() == expected_version:
            need_refresh = False

    if need_refresh:
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


def process_project_stable(project: str, time_limit: int, seed: int, class_limit: Optional[int],
                           target_class: Optional[str], target_method: Optional[str],
                           target_method_signature: Optional[str]):
    print(f"\n===== Project {project} (stable) =====")
    workdir, src_dir, cp_base = prepare_stable_project(project)
    classes_dir = workdir / "classes"

    randoop_jar, jacoco_agent, jacoco_cli = ensure_tools(cp_base)

    classlist_file = workdir / "classlist.txt"
    build_classlist(classes_dir, classlist_file)
    if target_class:
        classlist_file = filter_classlist_to_target(classlist_file, target_class)
    else:
        classlist_file = limit_classlist(classlist_file, class_limit)

    test_src_dir = run_randoop(workdir, randoop_jar, cp_base, classlist_file, time_limit, seed)
    if target_class and target_method:
        kept = filter_randoop_tests_by_method(test_src_dir, target_class, target_method)
        if kept == 0:
            print("[WARN] 未找到调用目标方法的测试：", target_method)
    test_bin_dir = workdir / "randoop-bin"
    compile_tests(test_src_dir, test_bin_dir, f"{cp_base}:{randoop_jar}:{test_bin_dir}")
    test_classes = collect_test_classes(test_bin_dir)
    full_cp = f"{cp_base}:{test_bin_dir}"
    run_coverage(
        workdir,
        jacoco_agent,
        jacoco_cli,
        full_cp,
        test_classes,
        classes_dir,
        src_dir,
        target_class=target_class,
        target_method=target_method,
        target_method_signature=target_method_signature,
    )


def process_humaneval(humaneval_root: Path, time_limit: int, seed: int, class_limit: Optional[int],
                      target_class: Optional[str], target_method: Optional[str],
                      target_method_signature: Optional[str]):
    if not humaneval_root.exists():
        raise RuntimeError(f"HumanEval-Java path not found: {humaneval_root}")

    print(f"\n===== HumanEval-Java ({humaneval_root}) =====")
    # 确保已编译 class（buggy 版本位于 humaneval.buggy）
    run_cmd(["mvn", "-q", "test-compile"], cwd=humaneval_root)

    classes_dir = humaneval_root / "target" / "classes"
    src_dir = humaneval_root / "src" / "main" / "java"
    junit, hamcrest = ensure_junit_hamcrest()
    cp_base = os.pathsep.join([str(classes_dir), str(junit), str(hamcrest)])

    randoop_jar, jacoco_agent, jacoco_cli = ensure_tools(cp_base)

    classlist_file = humaneval_root / "classlist.txt"
    build_classlist(classes_dir, classlist_file, only_prefix="humaneval.buggy")
    if target_class:
        classlist_file = filter_classlist_to_target(classlist_file, target_class)
    else:
        classlist_file = limit_classlist(classlist_file, class_limit)

    test_src_dir = run_randoop(humaneval_root, randoop_jar, cp_base, classlist_file, time_limit, seed)
    if target_class and target_method:
        kept = filter_randoop_tests_by_method(test_src_dir, target_class, target_method)
        if kept == 0:
            print("[WARN] 未找到调用目标方法的测试：", target_method)
    test_bin_dir = humaneval_root / "randoop-bin"
    compile_tests(test_src_dir, test_bin_dir, f"{cp_base}{os.pathsep}{randoop_jar}{os.pathsep}{test_bin_dir}")
    test_classes = collect_test_classes(test_bin_dir)
    full_cp = os.pathsep.join([str(classes_dir), str(test_bin_dir), str(junit), str(hamcrest)])
    run_coverage(
        humaneval_root,
        jacoco_agent,
        jacoco_cli,
        full_cp,
        test_classes,
        classes_dir,
        src_dir,
        target_class=target_class,
        target_method=target_method,
        target_method_signature=target_method_signature,
    )


# ------------------------- 命令行参数 -------------------------
def main():
    parser = argparse.ArgumentParser(description="Generate Randoop tests and Jacoco coverage")
    parser.add_argument("--project", action="append", dest="projects", help="Project name(s). Default: Lang,Math,Cli,Codec,Collections")
    parser.add_argument("--time-limit", type=int, default=60, help="Randoop time limit per project (seconds)")
    parser.add_argument("--seed", type=int, default=42, help="Random seed for Randoop")
    parser.add_argument("--mode", choices=["stable", "d4j", "humaneval"], default="stable", help="Use stable Maven artifacts, Defects4J bug1 fixed, or HumanEval-Java")
    parser.add_argument("--class-limit", type=int, default=None, help="Sample only the first N classes from classlist")
    parser.add_argument("--humaneval-path", type=Path, default=None, help="Path to human-eval-java root (for mode=humaneval); default searches local project then fallback copy")
    parser.add_argument("--target-class", default=None, help="目标类全限定名，例如 org.apache.commons.lang3.math.NumberUtils")
    parser.add_argument("--target-method", default=None, help="目标方法名，例如 createNumber")
    parser.add_argument("--target-method-signature", default=None, help="目标方法签名（javap 格式）")
    args = parser.parse_args()

    if args.target_method and not args.target_class:
        print("[WARN] 指定了 target-method 但未提供 target-class，将忽略方法过滤与单方法覆盖统计。")

    if args.mode == "humaneval":
        try:
            humaneval_root = resolve_humaneval_path(args.humaneval_path)
            process_humaneval(
                humaneval_root,
                args.time_limit,
                args.seed,
                args.class_limit,
                args.target_class,
                args.target_method,
                args.target_method_signature,
            )
        except Exception as exc:
            print(f"[!] HumanEval failed: {exc}", file=sys.stderr)
        return

    projects = args.projects or DEFAULT_PROJECTS
    for p in projects:
        try:
            if args.mode == "d4j":
                process_project_d4j(
                    p,
                    args.time_limit,
                    args.seed,
                    args.class_limit,
                    args.target_class,
                    args.target_method,
                    args.target_method_signature,
                )
            else:
                process_project_stable(
                    p,
                    args.time_limit,
                    args.seed,
                    args.class_limit,
                    args.target_class,
                    args.target_method,
                    args.target_method_signature,
                )
        except Exception as exc:
            print(f"[!] {p} failed: {exc}", file=sys.stderr)
            continue


if __name__ == "__main__":
    main()
