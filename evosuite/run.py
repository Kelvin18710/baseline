#!/usr/bin/env python3
"""
EvoSuite + JaCoCo automation（stable 版）。

特点
----
* 支持 Lang/Math/Cli/Codec/Collections 稳定 Maven 版本（不依赖 Defects4J）。
* 自动下载：项目 jar + sources、EvoSuite、JUnit/Hamcrest、JaCoCo。
* 生成 EvoSuite 测试、编译、运行并输出 HTML 覆盖率报告。

用法
----
python3 run.py                                  # 默认跑全部项目，search_budget=60s
python3 run.py --project Lang --time-limit 120  # 只跑 Lang，搜索 120s
python3 run.py --seed 123                       # 指定随机种子
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


# ------------------------- Constants -------------------------
DEFAULT_PROJECTS = ["Lang", "Math", "Cli", "Codec", "Collections"]
BASE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BASE_DIR / "project"
LIB_DIR = BASE_DIR / "lib"

STABLE_COORDS = {
    "Lang": ("commons-lang3", "3.14.0", "org.apache.commons"),
    "Math": ("commons-math3", "3.6.1", "org.apache.commons"),
    "Cli": ("commons-cli", "1.6.0", "commons-cli"),
    "Codec": ("commons-codec", "1.16.0", "commons-codec"),
    "Collections": ("commons-collections4", "4.4", "org.apache.commons"),
}
STABLE_PREFIX = {
    "Lang": "org.apache.commons.lang3",
    "Math": "org.apache.commons.math3",
    "Cli": "org.apache.commons.cli",
    "Codec": "org.apache.commons.codec",
    "Collections": "org.apache.commons.collections4",
}

JUNIT_COORD = ("junit", "4.13.2", "junit")
HAMCREST_COORD = ("hamcrest-core", "1.3", "org.hamcrest")
JACOCO_VERSION = "0.8.8"
EVOSUITE_VERSION = "1.2.0"


# ------------------------- Helpers ---------------------------
def run_cmd(cmd: List[str], cwd: Optional[Path] = None, check: bool = True, timeout: Optional[int] = None) -> str:
    print(f"[*] exec: {' '.join(cmd)}" + (f" (cwd={cwd})" if cwd else ""))
    try:
        res = subprocess.run(cmd, cwd=str(cwd) if cwd else None, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"Command timed out: {' '.join(cmd)}")
    if check and res.returncode != 0:
        raise RuntimeError(f"Command failed: {' '.join(cmd)}\nstdout:\n{res.stdout}\nstderr:\n{res.stderr}")
    if res.stdout:
        out = res.stdout.strip()
        if out:
            print(out)
    return res.stdout.strip()


def fqcn_to_path(fqcn: str) -> str:
    return fqcn.replace(".", "/")


def find_first(root: Path, predicate):
    for dirpath, _, filenames in os.walk(root):
        for fn in filenames:
            p = Path(dirpath) / fn
            if predicate(p):
                return p
    return None


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
    if not name:
        return None
    if "(" not in s or ")" not in s:
        return None
    params_str = s[s.find("(") + 1:s.rfind(")")]
    params = [p.strip() for p in params_str.split(",") if p.strip()]
    return "{0}({1})".format(name, ",".join(params))


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
    if t in primitives:
        base = primitives[t]
    else:
        base = "L" + t.replace(".", "/") + ";"
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
    return "{0}({1}){2}".format(method_name, params_desc, ret_desc)


def disable_evorunner_separate_classloader(test_file: Path) -> bool:
    if (not test_file) or (not test_file.exists()):
        return False
    content = test_file.read_text(encoding="utf-8")
    if "separateClassLoader = true" not in content:
        return False
    test_file.write_text(content.replace("separateClassLoader = true", "separateClassLoader = false"), encoding="utf-8")
    return True


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


def ensure_junit_hamcrest() -> Tuple[Path, Path]:
    junit = download_artifact(JUNIT_COORD[2], JUNIT_COORD[0], JUNIT_COORD[1])
    hamcrest = download_artifact(HAMCREST_COORD[2], HAMCREST_COORD[0], HAMCREST_COORD[1])
    return junit, hamcrest


def ensure_evosuite() -> Path:
    jar = LIB_DIR / f"evosuite-{EVOSUITE_VERSION}.jar"
    if jar.exists():
        return jar
    LIB_DIR.mkdir(exist_ok=True)
    url = f"https://github.com/EvoSuite/evosuite/releases/download/v{EVOSUITE_VERSION}/evosuite-{EVOSUITE_VERSION}.jar"
    print(f"[i] Downloading EvoSuite {EVOSUITE_VERSION} ...")
    urllib.request.urlretrieve(url, jar)
    return jar


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


def find_evosuite_test_file(tests_dir: Path, target_class: str) -> Optional[Path]:
    simple = target_class.split(".")[-1]
    target = simple + "_ESTest.java"
    return find_first(tests_dir, lambda p: p.name == target)


def has_evosuite_tests(tests_dir: Path) -> bool:
    if not tests_dir.exists():
        return False
    return any(tests_dir.rglob("*.java"))


def build_classlist(bin_dir: Path, out_file: Path):
    classes = []
    for cls_file in bin_dir.rglob("*.class"):
        rel = cls_file.relative_to(bin_dir)
        if rel.parts and rel.parts[0].upper() == "META-INF":
            continue
        if "$" in rel.name:
            continue
        if rel.name == "package-info.class":
            continue
        fqcn = ".".join(rel.with_suffix("").parts)
        classes.append(fqcn)
    if not classes:
        raise RuntimeError(f"No .class files found under {bin_dir}")
    out_file.write_text("\n".join(sorted(classes)), encoding="utf-8")
    print(f"[+] classlist -> {out_file} ({len(classes)} classes)")


def prepare_stable_project(project: str) -> Tuple[Path, Path, str]:
    if project not in STABLE_COORDS:
        raise RuntimeError(f"Unknown project {project} for stable mode")
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


def run_evosuite(project: str, workdir: Path, evosuite_jar: Path, cp: str, classes_dir: Path, time_limit: int, seed: int) -> Path:
    prefix = STABLE_PREFIX[project]
    # EvoSuite will emit to ./evosuite-tests by default in cwd
    cmd = [
        "java", "-Xmx4g", "-jar", str(evosuite_jar),
        "-prefix", prefix,
        "-target", str(classes_dir),
        "-projectCP", cp,
        "-base_dir", str(workdir),
        f"-Dsearch_budget={time_limit}",
        f"-Dglobal_timeout={time_limit}",
        f"-seed={seed}",
    ]
    run_cmd(cmd, cwd=workdir)
    return workdir / "evosuite-tests"


def run_evosuite_for_class(class_name: str, workdir: Path, evosuite_jar: Path, cp: str, classes_dir: Path,
                           time_limit: int, seed: int, target_method: Optional[str] = None,
                           target_method_signature: Optional[str] = None):
    cmd = [
        "java", "-Xmx2g", "-jar", str(evosuite_jar),
        "-class", class_name,
        "-target", str(classes_dir),
        "-projectCP", cp,
        "-base_dir", str(workdir),
        f"-Dsearch_budget={time_limit}",
        f"-seed={seed}",
    ]
    if target_method_signature:
        cmd.append(f"-Dtarget_method_list={target_method_signature}")
    elif target_method:
        cmd.append(f"-Dtarget_method={target_method}")
    run_cmd(cmd, cwd=workdir)


def compile_tests(tests_dir: Path, test_bin: Path, cp: str):
    java_files = list(tests_dir.rglob("*.java"))
    if not java_files:
        raise RuntimeError(f"No EvoSuite tests generated in {tests_dir}")
    test_bin.mkdir(exist_ok=True)
    cmd = [
        "javac", "-g",
        "-d", str(test_bin),
        "-cp", cp,
    ] + [str(f) for f in java_files]
    run_cmd(cmd)


def collect_test_classes(test_bin: Path) -> List[str]:
    names = []
    for cls in test_bin.rglob("*.class"):
        rel = cls.relative_to(test_bin)
        if "$" in rel.name:
            continue
        fqcn = ".".join(rel.with_suffix("").parts)
        if fqcn.endswith("_scaffolding"):
            continue
        names.append(fqcn)
    if not names:
        raise RuntimeError("No compiled EvoSuite test classes found")
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
    print("[*] exec: " + " ".join(cmd))
    junit_res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if junit_res.stdout:
        print(junit_res.stdout.strip())
    if junit_res.stderr:
        print(junit_res.stderr.strip(), file=sys.stderr)
    if junit_res.returncode != 0:
        print(f"[!] JUnit exited with code {junit_res.returncode}, continuing to generate coverage report")

    if not exec_file.exists():
        print("[!] jacoco.exec not found, skipping report generation")
        return

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

    if target_class and (target_method or target_method_signature) and xml_report.exists():
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


# ------------------------- Pipeline -------------------------
def process_project(project: str, time_limit: int, seed: int, class_limit: Optional[int],
                    target_class: Optional[str], target_method: Optional[str],
                    target_method_signature: Optional[str], no_fallback: bool):
    print(f"\n===== Project {project} (stable) =====")
    if target_method and not target_class:
        print("[WARN] 指定了 target-method 但未提供 target-class，将忽略方法过滤与单方法覆盖统计。")
    workdir, src_dir, cp_base = prepare_stable_project(project)
    classes_dir = workdir / "classes"

    evosuite_jar = ensure_evosuite()
    jacoco_agent, jacoco_cli = ensure_jacoco()

    classlist_file = workdir / "classlist.txt"
    build_classlist(classes_dir, classlist_file)

    tests_dir = workdir / "evosuite-tests"
    resolved_method_list = None
    descriptor_method_list = None
    if target_method_signature:
        resolved_method_list = signature_to_evosuite_method(target_method_signature) or target_method_signature.strip()
        descriptor_method_list = signature_to_descriptor_method(target_method_signature)
    elif target_method:
        try:
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
        except Exception as e:
            print("[WARN] 解析方法签名失败，使用原始方法名过滤：", target_method, "err:", e)

    if target_class:
        if tests_dir.exists():
            shutil.rmtree(tests_dir)
        run_evosuite_for_class(
            target_class,
            workdir,
            evosuite_jar,
            cp_base,
            classes_dir,
            time_limit,
            seed,
            target_method=target_method if not resolved_method_list else None,
            target_method_signature=resolved_method_list or target_method_signature,
        )
        if (target_method or target_method_signature) and (not has_evosuite_tests(tests_dir)) and descriptor_method_list:
            print("[WARN] 方法过滤未生成测试，尝试使用 JVM 描述符格式重跑。")
            run_evosuite_for_class(
                target_class,
                workdir,
                evosuite_jar,
                cp_base,
                classes_dir,
                time_limit,
                seed,
                target_method_signature=descriptor_method_list,
            )
        if (target_method or target_method_signature) and (not has_evosuite_tests(tests_dir)):
            if no_fallback:
                raise RuntimeError("未生成 EvoSuite 测试（已禁用无过滤回退）")
            print("[WARN] 未生成测试或测试为空，尝试不使用方法过滤重新生成。")
            run_evosuite_for_class(
                target_class,
                workdir,
                evosuite_jar,
                cp_base,
                classes_dir,
                time_limit,
                seed,
            )
        if (target_method or target_method_signature) and (not has_evosuite_tests(tests_dir)):
            raise RuntimeError("未生成 EvoSuite 测试（目标方法过滤与回退均失败）")
    elif class_limit:
        classes = classlist_file.read_text().splitlines()
        selected = classes[:class_limit]
        print(f"[i] Running EvoSuite on {len(selected)} classes (sample)")
        for cls in selected:
            run_evosuite_for_class(cls, workdir, evosuite_jar, cp_base, classes_dir, time_limit, seed)
    else:
        tests_dir = run_evosuite(project, workdir, evosuite_jar, cp_base, classes_dir, time_limit, seed)

    if target_class:
        test_file = find_evosuite_test_file(tests_dir, target_class)
        if disable_evorunner_separate_classloader(test_file):
            print("[INFO] 已禁用 EvoRunner separateClassLoader 以增强 JaCoCo 覆盖记录。")

    test_bin = workdir / "evosuite-bin"
    if target_class and test_bin.exists():
        shutil.rmtree(test_bin)
    cp_compile = os.pathsep.join([str(classes_dir), str(evosuite_jar), cp_base])
    compile_tests(tests_dir, test_bin, cp_compile)

    test_classes = collect_test_classes(test_bin)
    cp_run = os.pathsep.join([str(classes_dir), str(test_bin), str(evosuite_jar), cp_base])
    run_coverage(
        workdir,
        jacoco_agent,
        jacoco_cli,
        cp_run,
        test_classes,
        classes_dir,
        src_dir,
        target_class=target_class,
        target_method=target_method,
        target_method_signature=target_method_signature,
    )


# ------------------------- CLI -------------------------
def main():
    parser = argparse.ArgumentParser(description="Generate EvoSuite tests and Jacoco coverage (stable Maven artifacts)")
    parser.add_argument("--project", action="append", dest="projects", help="Project name(s). Default: Lang,Math,Cli,Codec,Collections")
    parser.add_argument("--time-limit", type=int, default=60, help="EvoSuite search_budget per class (seconds)")
    parser.add_argument("--seed", type=int, default=42, help="Random seed for EvoSuite")
    parser.add_argument("--class-limit", type=int, default=None, help="Sample only the first N classes from classlist for quicker runs")
    parser.add_argument("--target-class", default=None, help="目标类全限定名，例如 org.apache.commons.lang3.math.NumberUtils")
    parser.add_argument("--target-method", default=None, help="目标方法名，例如 createNumber")
    parser.add_argument("--target-method-signature", default=None, help="目标方法签名（javap 格式）")
    parser.add_argument("--no-fallback", action="store_true", help="方法过滤失败时不回退到无过滤生成")
    args = parser.parse_args()

    projects = args.projects or DEFAULT_PROJECTS
    for p in projects:
        try:
            process_project(
                p,
                args.time_limit,
                args.seed,
                args.class_limit,
                args.target_class,
                args.target_method,
                args.target_method_signature,
                args.no_fallback,
            )
        except Exception as exc:
            print(f"[!] {p} failed: {exc}", file=sys.stderr)
            continue


if __name__ == "__main__":
    main()
