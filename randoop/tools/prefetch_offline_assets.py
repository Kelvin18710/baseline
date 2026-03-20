#!/usr/bin/env python3
"""
Prefetch offline assets for network-poor environments.

使用方式：
  python3 prefetch_offline_assets.py [--projects all|Lang,Math,...]
  
从 Maven Central 下载项目源代码包到 baseline 共享目录，并下载运行依赖到 cache/lib。
"""

import argparse
import os
import shutil
import urllib.request
import zipfile
from pathlib import Path
from typing import List, Tuple

SCRIPT_DIR = Path(__file__).resolve().parent
RANDOOP_ROOT = SCRIPT_DIR.parent
BASELINE_ROOT = RANDOOP_ROOT.parent
LIB_DIR = RANDOOP_ROOT / "cache" / "lib"
SHARED_PROJECT_ARCHIVES_DIR = BASELINE_ROOT / "shared_project_packages" / "project_archives"

# Same coordinates as run.py
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


def maven_url(group: str, artifact: str, version: str, classifier: str = "") -> str:
    path = "/".join([group.replace(".", "/"), artifact, version])
    name = f"{artifact}-{version}"
    if classifier:
        name += f"-{classifier}"
    name += ".jar"
    return f"https://repo1.maven.org/maven2/{path}/{name}"


def download_file(url: str, dest: Path, description: str = "") -> bool:
    """Download file with error handling."""
    try:
        print(f"  [{description}] {url}")
        urllib.request.urlretrieve(url, dest)
        return True
    except Exception as e:
        print(f"  [FAIL] {e}")
        return False


def ensure_project(project: str, coords: Tuple[str, str, str]) -> bool:
    """Download sources for a project into baseline shared archive cache."""
    artifact, version, group = coords

    # Copy sources to baseline-shared project archives for offline extraction
    SHARED_PROJECT_ARCHIVES_DIR.mkdir(parents=True, exist_ok=True)
    archive_copy = SHARED_PROJECT_ARCHIVES_DIR / f"{project.lower()}-{artifact}-{version}-sources.jar"
    if not archive_copy.exists():
        try:
            src_url = maven_url(group, artifact, version, "sources")
            if not download_file(src_url, archive_copy, f"[SRC] {project}"):
                return False
            print(f"  [OK] archive: {archive_copy}")
        except Exception as e:
            print(f"  [FAIL] archiving: {e}")
            return False
    else:
        print(f"  [OK] archive: {archive_copy}")
    
    return True


def ensure_runtime_deps() -> bool:
    """Download runtime dependencies (Randoop, JUnit, Hamcrest, JaCoCo)."""
    print("\n=== runtime deps ===")
    
    # Randoop
    randoop_jar = LIB_DIR / f"randoop-all-{RANDOOP_VERSION}.jar"
    if not randoop_jar.exists():
        url = f"https://github.com/randoop/randoop/releases/download/v{RANDOOP_VERSION}/randoop-all-{RANDOOP_VERSION}.jar"
        if not download_file(url, randoop_jar, "[RANDOOP]"):
            return False
    else:
        print(f"  [OK] randoop: {randoop_jar}")
    
    # JUnit
    junit_jar = LIB_DIR / f"{JUNIT_COORD[0]}-{JUNIT_COORD[1]}.jar"
    if not junit_jar.exists():
        url = maven_url(JUNIT_COORD[2], JUNIT_COORD[0], JUNIT_COORD[1])
        if not download_file(url, junit_jar, "[JUNIT]"):
            return False
    else:
        print(f"  [OK] junit: {junit_jar}")
    
    # Hamcrest
    hamcrest_jar = LIB_DIR / f"{HAMCREST_COORD[0]}-{HAMCREST_COORD[1]}.jar"
    if not hamcrest_jar.exists():
        url = maven_url(HAMCREST_COORD[2], HAMCREST_COORD[0], HAMCREST_COORD[1])
        if not download_file(url, hamcrest_jar, "[HAMCREST]"):
            return False
    else:
        print(f"  [OK] hamcrest: {hamcrest_jar}")
    
    # JaCoCo agent
    jacoco_agent = LIB_DIR / f"jacocoagent-{JACOCO_VERSION}.jar"
    if not jacoco_agent.exists():
        url = f"https://repo1.maven.org/maven2/org/jacoco/org.jacoco.agent/{JACOCO_VERSION}/org.jacoco.agent-{JACOCO_VERSION}-runtime.jar"
        if not download_file(url, jacoco_agent, "[JACOCO-AGENT]"):
            return False
    else:
        print(f"  [OK] jacoco-agent: {jacoco_agent}")
    
    # JaCoCo CLI
    jacoco_cli = LIB_DIR / f"jacococli-{JACOCO_VERSION}.jar"
    if not jacoco_cli.exists():
        url = f"https://repo1.maven.org/maven2/org/jacoco/org.jacoco.cli/{JACOCO_VERSION}/org.jacoco.cli-{JACOCO_VERSION}-nodeps.jar"
        if not download_file(url, jacoco_cli, "[JACOCO-CLI]"):
            return False
    else:
        print(f"  [OK] jacoco-cli: {jacoco_cli}")
    
    return True


def main():
    parser = argparse.ArgumentParser(description="Prefetch offline assets")
    parser.add_argument("--projects", default="all", help="Comma-separated project list or 'all'")
    
    args = parser.parse_args()
    
    if args.projects.lower() == "all":
        projects = list(STABLE_COORDS.keys())
    else:
        projects = [p.strip() for p in args.projects.split(",")]
    
    # Validate projects
    invalid = [p for p in projects if p not in STABLE_COORDS]
    if invalid:
        print(f"[-] Unknown projects: {invalid}")
        return False
    
    print(f"[i] Prefetch for projects: {', '.join(projects)}")
    print(f"[i] shared project archives: {SHARED_PROJECT_ARCHIVES_DIR}")
    
    LIB_DIR.mkdir(parents=True, exist_ok=True)
    SHARED_PROJECT_ARCHIVES_DIR.mkdir(parents=True, exist_ok=True)
    
    # Download runtime deps
    if not ensure_runtime_deps():
        print("[-] Failed to download runtime dependencies")
        return False
    
    # Download projects
    failed = []
    for project in projects:
        print(f"\n=== prefetch {project} ({STABLE_COORDS[project][0]} {STABLE_COORDS[project][1]}) ===")
        if not ensure_project(project, STABLE_COORDS[project]):
            failed.append(project)
    
    if failed:
        print(f"\n[-] Failed: {', '.join(failed)}")
        return False
    
    print("\n=== done ===")
    print("[+] All requested assets are cached locally for offline-friendly runs.")
    return True


if __name__ == "__main__":
    import sys
    sys.exit(0 if main() else 1)
