#!/usr/bin/env python3
"""
精简版 Randoop + JaCoCo 运行脚本（stable Maven 版）。

特点：
- 针对单个 target-class 生成测试，支持方法过滤
- 利用 Randoop 生成 JUnit 测试
- 使用 JaCoCo 计算行/指令/分支覆盖率
- 输出方法级覆盖率统计
"""

import argparse
import os
import re
import shutil
import subprocess
import sys
import urllib.request
import zipfile
import tarfile
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import List, Optional, Tuple, Dict

# ======================== Constants ========================
DEFAULT_PROJECTS = [
    "Lang",
    "Math",
    "Cli",
    "Codec",
    "Collections",
    "CSV",
    "Compress",
    "JCore",
    "JDataBind",
    "JXML",
    "JxPath",
    "JodaTime",
]

SCRIPT_DIR = Path(__file__).resolve().parent
RANDOOP_ROOT = SCRIPT_DIR.parent
PROJECT_ROOT = RANDOOP_ROOT / "cache" / "project_workspace"
LIB_DIR = RANDOOP_ROOT / "cache" / "lib"
PROJECT_TAR_DIR = RANDOOP_ROOT / "cache" / "project_archives"

STABLE_COORDS = {
    "Lang": ("commons-lang3", "3.18.0", "org.apache.commons"),
    "Math": ("commons-math3", "3.6.1", "org.apache.commons"),
    "Cli": ("commons-cli", "1.6.0", "commons-cli"),
    "Codec": ("commons-codec", "1.21.0", "commons-codec"),
    "Collections": ("commons-collections4", "4.5.0", "org.apache.commons"),
    "CSV": ("commons-csv", "1.13.0", "org.apache.commons"),
    "Compress": ("commons-compress", "1.28.0", "org.apache.commons"),
    "JCore": ("jackson-core", "2.19.0", "com.fasterxml.jackson.core"),
    "JDataBind": ("jackson-databind", "2.19.0", "com.fasterxml.jackson.core"),
    "JXML": ("jackson-dataformat-xml", "2.19.0", "com.fasterxml.jackson.dataformat"),
    "JxPath": ("commons-jxpath", "1.4.0", "commons-jxpath"),
    "JodaTime": ("joda-time", "2.13.1", "joda-time"),
}

JUNIT_COORD = ("junit", "4.13.2", "junit")
HAMCREST_COORD = ("hamcrest-core", "1.3", "org.hamcrest")
JACOCO_VERSION = "0.8.8"
RANDOOP_VERSION = "4.3.0"

# Classes that cause problems with Randoop
EXCLUDE_CLASSES = {
    "org.apache.commons.lang3.DoubleRange",
    "org.apache.commons.lang3.IntegerRange",
    "org.apache.commons.lang3.LongRange",
    "org.apache.commons.lang3.NumberRange",
}


# ======================== Utils ========================

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


def slugify(text: str) -> str:
    out = []
    for ch in text:
        if ch.isalnum():
            out.append(ch)
        else:
            out.append("_")
    slug = "".join(out).strip("_")
    return slug[:160] if len(slug) > 160 else slug


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
        print(f"[*] {artifact}:{version}{f' {classifier}' if classifier else ''} already cached")
        return dest
    url = maven_url(group, artifact, version, classifier)
    print(f"[i] Downloading {artifact}:{version}{f' {classifier}' if classifier else ''} from {url}...")
    try:
        urllib.request.urlretrieve(url, dest)
        return dest
    except Exception as e:
        dest.unlink(missing_ok=True)
        raise RuntimeError(f"Failed to download {artifact}: {e}")


def unzip_jar(jar_path: Path, target_dir: Path):
    target_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(jar_path, 'r') as zf:
        zf.extractall(target_dir)


def prepare_stable_project(project: str, workdir: Path) -> Tuple[Path, Path, str]:
    """
    Prepare project workspace from stable Maven coordinates.
    Returns (bin_dir, src_dir, classpath)
    """
    if project not in STABLE_COORDS:
        raise ValueError(f"Unknown project: {project}")
    
    artifact, version, group = STABLE_COORDS[project]
    workdir.mkdir(parents=True, exist_ok=True)
    
    # Download binary
    bin_jar = download_artifact(group, artifact, version)
    bin_dir = workdir / "bin"
    bin_dir.mkdir(exist_ok=True)
    unzip_jar(bin_jar, bin_dir)
    
    # Download sources as jar and extract
    src_jar = download_artifact(group, artifact, version, "sources")
    src_dir = workdir / "src"
    src_dir.mkdir(exist_ok=True)
    unzip_jar(src_jar, src_dir)
    
    # Ensure JUnit and Hamcrest are available
    junit = download_artifact(JUNIT_COORD[2], JUNIT_COORD[0], JUNIT_COORD[1])
    hamcrest = download_artifact(HAMCREST_COORD[2], HAMCREST_COORD[0], HAMCREST_COORD[1])
    
    classpath = os.pathsep.join([str(bin_jar), str(junit), str(hamcrest)])
    return bin_dir, src_dir, classpath


def ensure_randoop() -> Path:
    jar = LIB_DIR / f"randoop-all-{RANDOOP_VERSION}.jar"
    if jar.exists():
        return jar
    LIB_DIR.mkdir(exist_ok=True)
    url = f"https://github.com/randoop/randoop/releases/download/v{RANDOOP_VERSION}/randoop-all-{RANDOOP_VERSION}.jar"
    print(f"[i] Downloading Randoop {RANDOOP_VERSION}...")
    try:
        urllib.request.urlretrieve(url, jar)
        return jar
    except Exception as e:
        jar.unlink(missing_ok=True)
        raise RuntimeError(f"Failed to download Randoop: {e}")


def ensure_jacoco() -> Tuple[Path, Path]:
    LIB_DIR.mkdir(exist_ok=True)
    agent = LIB_DIR / f"jacocoagent-{JACOCO_VERSION}.jar"
    cli = LIB_DIR / f"jacococli-{JACOCO_VERSION}.jar"
    
    if not agent.exists():
        print("[i] Downloading JaCoCo agent...")
        url = f"https://repo1.maven.org/maven2/org/jacoco/org.jacoco.agent/{JACOCO_VERSION}/org.jacoco.agent-{JACOCO_VERSION}-runtime.jar"
        try:
            urllib.request.urlretrieve(url, agent)
        except Exception as e:
            agent.unlink(missing_ok=True)
            raise RuntimeError(f"Failed to download JaCoCo agent: {e}")
    
    if not cli.exists():
        print("[i] Downloading JaCoCo CLI...")
        url = f"https://repo1.maven.org/maven2/org/jacoco/org.jacoco.cli/{JACOCO_VERSION}/org.jacoco.cli-{JACOCO_VERSION}-nodeps.jar"
        try:
            urllib.request.urlretrieve(url, cli)
        except Exception as e:
            cli.unlink(missing_ok=True)
            raise RuntimeError(f"Failed to download JaCoCo CLI: {e}")
    
    return agent, cli


def build_classlist(bin_dir: Path, out_file: Path, target_class: Optional[str] = None) -> List[str]:
    """
    Build classlist from binary directory.
    If target_class is specified, only include that class.
    Returns list of class names.
    """
    classes = []
    
    if target_class:
        # Only add the target class
        classes.append(target_class)
    else:
        # Find all classes
        for cls_file in bin_dir.rglob("*.class"):
            rel = cls_file.relative_to(bin_dir)
            if rel.parts and rel.parts[0].upper() == "META-INF":
                continue
            if "$" in rel.name:
                continue  # Skip inner classes
            if rel.name == "package-info.class":
                continue
            fqcn = ".".join(rel.with_suffix("").parts)
            if fqcn in EXCLUDE_CLASSES:
                continue
            classes.append(fqcn)
    
    if not classes:
        raise RuntimeError(f"No classes to test (target_class={target_class})")
    
    classes = sorted(set(classes))
    out_file.write_text("\n".join(classes), encoding="utf-8")
    print(f"[+] classlist -> {out_file} ({len(classes)} classes)")
    return classes


def run_randoop(workdir: Path, randoop_jar: Path, cp_test: str, classlist: Path, time_limit: int) -> Path:
    """
    Run Randoop to generate tests for classes in classlist.
    time_limit is in seconds; 0 means use Randoop default (10 seconds).
    """
    out_dir = workdir / "randoop-tests" / "src"
    out_dir.mkdir(parents=True, exist_ok=True)
    
    cmd = [
        "java", "-Xmx4g",
        "-classpath", f"{randoop_jar}{os.pathsep}{cp_test}",
        "randoop.main.Main", "gentests",
        f"--classlist={classlist}",
        "--usethreads",
        "--call-timeout=1",
        "--junit-output-dir", str(out_dir),
        "--randomseed=42",
    ]
    if time_limit and time_limit > 0:
        cmd.insert(cmd.index("--usethreads"), f"--time-limit={time_limit}")
    
    log_file = workdir / "randoop.log"
    run_cmd_logged(cmd, log_file, cwd=workdir)
    
    return out_dir


def filter_randoop_tests_by_method(test_src_dir: Path, target_class: str, target_method: str) -> int:
    """
    Filter Randoop tests to keep only those calling target_method.
    Returns count of kept tests.
    """
    simple = target_class.split(".")[-1]
    pattern = re.compile(r"\b{0}\s*\.\s*{1}\s*\(".format(re.escape(simple), re.escape(target_method)))
    kept_total = 0
    
    for test_file in test_src_dir.glob("*.java"):
        content = test_file.read_text(encoding="utf-8", errors="ignore")
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
        
        if output and any("public class" in ln for ln in output):
            test_file.write_text("\n".join(output) + "\n", encoding="utf-8")
        else:
            test_file.unlink(missing_ok=True)
    
    return kept_total


def compile_tests(test_src_dir: Path, test_bin_dir: Path, cp: str):
    """Compile generated tests."""
    java_files = list(test_src_dir.glob("*.java"))
    if not java_files:
        raise RuntimeError(f"No Randoop tests in {test_src_dir}")
    
    test_bin_dir.mkdir(exist_ok=True)
    cmd = [
        "javac", "-g",
        "-d", str(test_bin_dir),
        "-cp", cp,
    ] + [str(f) for f in java_files]
    run_cmd(cmd)


def collect_test_classes(test_bin_dir: Path) -> List[str]:
    """Collect compiled test class names."""
    names = []
    for cls in test_bin_dir.rglob("*.class"):
        rel = cls.relative_to(test_bin_dir)
        if "$" in rel.name or rel.name == "package-info.class":
            continue
        class_name = ".".join(rel.with_suffix("").parts)
        # Only run generated test classes, avoid passing production classes to JUnitCore.
        if class_name.endswith("Test") or class_name.startswith("RegressionTest"):
            names.append(class_name)
    if not names:
        raise RuntimeError("No compiled test classes found")
    return sorted(names)


def load_line_coverage(xml_report: Path, target_fqcn: str) -> Dict[int, Dict[str, int]]:
    target_path = fqcn_to_path(target_fqcn)
    target_pkg = target_path.rsplit("/", 1)[0] if "/" in target_path else target_path
    simple = target_fqcn.split(".")[-1]
    source_file_name = simple + ".java"

    tree = ET.parse(xml_report)
    root = tree.getroot()
    coverage: Dict[int, Dict[str, int]] = {}

    def collect_from_pkg(pkg_elem):
        for sf in pkg_elem.findall("sourcefile"):
            if sf.get("name") != source_file_name:
                continue
            for line in sf.findall("line"):
                try:
                    nr = int(line.get("nr") or 0)
                    coverage[nr] = {
                        "mi": int(line.get("mi") or 0),
                        "ci": int(line.get("ci") or 0),
                        "mb": int(line.get("mb") or 0),
                        "cb": int(line.get("cb") or 0),
                    }
                except Exception:
                    continue

    matched = False
    for pkg in root.findall("package"):
        pkg_name = pkg.get("name") or ""
        if pkg_name and pkg_name == target_pkg:
            collect_from_pkg(pkg)
            matched = True
            break

    if not matched:
        for pkg in root.findall("package"):
            collect_from_pkg(pkg)

    return coverage


def run_javap(classes_dir: Path, target_fqcn: str) -> List[str]:
    # Use -p to include private/package methods for method-level line mapping.
    cmd = ["javap", "-classpath", str(classes_dir), "-p", "-c", "-l", target_fqcn]
    res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if res.returncode != 0:
        raise RuntimeError(f"javap failed: {res.stderr}")
    return res.stdout.splitlines()


def parse_javap(lines: List[str]) -> List[Dict[str, Dict[int, int]]]:
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
                "line_table": {},
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

    if cur:
        methods.append(cur)
    return methods


def collect_method_lines(methods: List[Dict[str, Dict[int, int]]], method_name: str) -> List[int]:
    name = method_name_from_filter(method_name)
    lines = set()
    for m in methods:
        sig = m.get("signature", "")
        if extract_method_name(sig) == name:
            lines.update(set(m.get("line_table", {}).values()))
    return sorted(lines)


def compute_method_coverage_from_lines(line_cov: Dict[int, Dict[str, int]], method_lines: List[int]) -> Dict[str, Tuple[int, int]]:
    line_num = 0
    line_den = 0
    instr_num = 0
    instr_den = 0
    branch_num = 0
    branch_den = 0

    for lno in method_lines:
        stats = line_cov.get(lno)
        if not stats:
            continue
        ci = stats.get("ci", 0)
        mi = stats.get("mi", 0)
        cb = stats.get("cb", 0)
        mb = stats.get("mb", 0)

        line_den += 1
        if ci > 0:
            line_num += 1

        instr_num += ci
        instr_den += ci + mi

        branch_num += cb
        branch_den += cb + mb

    return {
        "line": (line_num, line_den),
        "instr": (instr_num, instr_den),
        "branch": (branch_num, branch_den),
    }


def run_jacoco_tests(workdir: Path, jacoco_agent: Path, jacoco_cli: Path, 
                     cp: str, test_classes: List[str], bin_dir: Path) -> Path:
    """
    Run JUnit tests with JaCoCo to generate coverage report.
    Returns path to report directory.
    """
    exec_file = workdir / "jacoco.exec"
    
    # Run tests with JaCoCo agent
    cp_parts = [str(bin_dir)] + cp.split(os.pathsep)
    cp_full = os.pathsep.join(cp_parts)
    
    cmd = [
        "java", "-Xmx4g",
        f"-javaagent:{jacoco_agent}=destfile={exec_file}",
        "-cp", cp_full,
        "org.junit.runner.JUnitCore",
    ] + test_classes
    
    log_file = workdir / "junit.log"
    run_cmd_logged(cmd, log_file, cwd=workdir, check=False)
    
    # Generate report
    report_dir = workdir / "jacoco-report"
    report_dir.mkdir(exist_ok=True)
    
    cmd = [
        "java", "-jar", str(jacoco_cli),
        "report", str(exec_file),
        "--classfiles", str(bin_dir),
        "--sourcefiles", str(workdir / "src"),
        "--html", str(report_dir),
        "--xml", str(report_dir / "jacoco.xml"),
    ]
    run_cmd(cmd)
    
    return report_dir


def load_coverage_from_xml(xml_report: Path, target_fqcn: str) -> Dict[str, Tuple[int, int]]:
    """
    Load coverage metrics from JaCoCo XML report for target class.
    Returns {"line": (cov, total), "instr": (cov, total), "branch": (cov, total)}
    """
    if not xml_report.exists():
        return {"line": (0, 0), "instr": (0, 0), "branch": (0, 0)}
    
    tree = ET.parse(xml_report)
    root = tree.getroot()
    
    # Find matching sourcefile or class
    def extract_coverage(elem):
        result = {}
        for counter in elem.findall("counter"):
            ctype = counter.get("type", "")
            covered = int(counter.get("covered", 0))
            missed = int(counter.get("missed", 0))
            result[ctype] = (covered, covered + missed)
        return result
    
    simple_name = target_fqcn.split(".")[-1]
    
    # Try to find in sourcefile
    for sourcefile in root.findall(".//sourcefile"):
        if sourcefile.get("name") == f"{simple_name}.java":
            cov = extract_coverage(sourcefile)
            return {
                "line": cov.get("LINE", (0, 0)),
                "instr": cov.get("INSTRUCTION", (0, 0)),
                "branch": cov.get("BRANCH", (0, 0)),
            }
    
    # Fallback: try to find by class
    for cls in root.findall(".//class"):
        if cls.get("name", "").split("/")[-1] == simple_name:
            cov = extract_coverage(cls)
            return {
                "line": cov.get("LINE", (0, 0)),
                "instr": cov.get("INSTRUCTION", (0, 0)),
                "branch": cov.get("BRANCH", (0, 0)),
            }
    
    return {"line": (0, 0), "instr": (0, 0), "branch": (0, 0)}


# ======================== Main ========================

def main():
    parser = argparse.ArgumentParser(description="Randoop + JaCoCo test generation and coverage")
    parser.add_argument("--project", default="Lang", help="Project name")
    parser.add_argument("--class", dest="target_class", required=True, help="Target class (fully qualified)")
    parser.add_argument("--method", help="Target method name (optional, for filtering)")
    parser.add_argument("--time-limit", type=int, default=0, help="Time limit in seconds (<=0 means Randoop default)")
    parser.add_argument("--no-artifacts", action="store_true", help="Don't save artifacts to reports/")
    
    args = parser.parse_args()
    
    project = args.project
    target_class = args.target_class
    target_method = args.method
    time_limit = args.time_limit
    save_artifacts = not args.no_artifacts
    
    # Ensure tools are available
    randoop_jar = ensure_randoop()
    jacoco_agent, jacoco_cli = ensure_jacoco()
    
    # Prepare project workspace
    workdir = PROJECT_ROOT / project
    bin_dir, src_dir, classpath = prepare_stable_project(project, workdir)
    
    # Build classlist
    classlist = workdir / "classlist.txt"
    build_classlist(bin_dir, classlist, target_class)
    
    # Run Randoop
    test_src_dir = run_randoop(workdir, randoop_jar, classpath, classlist, time_limit)
    
    # Filter tests by method if specified
    kept = None
    no_test_hit = False
    if target_method:
        kept = filter_randoop_tests_by_method(test_src_dir, target_class, target_method)
        print(f"[+] Kept {kept} tests calling {target_method}")
        if kept == 0:
            no_test_hit = True
    
    report_dir = workdir / "jacoco-report"
    xml_file = report_dir / "jacoco.xml"
    coverage = {"line": (0, 0), "instr": (0, 0), "branch": (0, 0)}

    if not no_test_hit:
        # Compile tests
        test_bin_dir = workdir / "randoop-tests" / "bin"
        cp_with_junit = os.pathsep.join([classpath, str(workdir / "src")])
        compile_tests(test_src_dir, test_bin_dir, cp_with_junit)

        # Run tests with JaCoCo coverage
        test_classes = collect_test_classes(test_bin_dir)
        report_dir = run_jacoco_tests(workdir, jacoco_agent, jacoco_cli,
                                      os.pathsep.join([str(test_bin_dir), classpath]),
                                      test_classes, bin_dir)

        # Extract coverage metrics
        xml_file = report_dir / "jacoco.xml"
        coverage = load_coverage_from_xml(xml_file, target_class)
        if target_method:
            try:
                javap_lines = run_javap(bin_dir, target_class)
                methods = parse_javap(javap_lines)
                method_lines = collect_method_lines(methods, target_method)
                if method_lines:
                    line_cov = load_line_coverage(xml_file, target_class)
                    method_cov = compute_method_coverage_from_lines(line_cov, method_lines)
                    # Prefer method-level metrics when available.
                    coverage = method_cov
                else:
                    print(f"[!] No line mapping found for method {target_method}, fallback to class-level coverage")
            except Exception as e:
                print(f"[!] Method-level coverage extraction failed ({e}), fallback to class-level coverage")
    
    # Print results
    print("\n" + "="*60)
    print(f"Randoop coverage for {target_class}:")
    print("="*60)
    
    for metric in ["line", "instr", "branch"]:
        cov, total = coverage[metric]
        pct = 100.0 * cov / total if total > 0 else 0.0
        print(f"  {metric:8s}: {cov:6d}/{total:6d} ({pct:6.2f}%)")
    
    print("="*60)
    
    # Save artifacts if requested
    if save_artifacts:
        class_dir = target_class.replace(".", "/")
        method_dir = slugify(target_method) if target_method else "_class_scope"
        artifact_dir = RANDOOP_ROOT / "reports" / "method_coverage" / project / class_dir / method_dir
        artifact_dir.mkdir(parents=True, exist_ok=True)
        
        # Copy report
        for item in report_dir.glob("*"):
            if item.is_file():
                shutil.copy2(item, artifact_dir / item.name)
        
        # Save test source
        tests_dir = artifact_dir / "tests"
        tests_dir.mkdir(exist_ok=True)
        for f in test_src_dir.glob("*.java"):
            shutil.copy2(f, tests_dir / f.name)
        
        print(f"[+] Artifacts saved to {artifact_dir}")


if __name__ == "__main__":
    main()
