#!/usr/bin/env python3
"""Prefetch all stable project assets for offline execution.

What this script downloads into cache:
- project binary jars -> cache/lib
- project source jars -> cache/lib
- source archives (copied from source jars) -> cache/project_archives
- EvoSuite/JUnit/Hamcrest/JaCoCo runtime deps -> cache/lib

After this, run.py can use local archives/jars directly without runtime project downloads.
"""

import argparse
import shutil
from pathlib import Path

import run as runner


def copy_source_jar_to_archives(project: str, artifact: str, version: str) -> Path:
    src_jar = runner.local_artifact_path(artifact, version, classifier="sources")
    archive_dir = runner.PROJECT_TAR_DIR
    archive_dir.mkdir(parents=True, exist_ok=True)
    dst = archive_dir / f"{project.lower()}-{artifact}-{version}-sources.jar"
    if not dst.exists():
        shutil.copy2(src_jar, dst)
    return dst


def prefetch_project(project: str) -> None:
    artifact, version, group = runner.STABLE_COORDS[project]
    print(f"\n=== prefetch {project} ({group}:{artifact}:{version}) ===")
    bin_jar = runner.download_artifact(group, artifact, version)
    src_jar = runner.download_artifact(group, artifact, version, classifier="sources")
    archive = copy_source_jar_to_archives(project, artifact, version)
    print("[OK] binary:", bin_jar)
    print("[OK] sources:", src_jar)
    print("[OK] archive:", archive)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Prefetch stable assets for offline EvoSuite runs")
    parser.add_argument(
        "--projects",
        default="all",
        help="逗号分隔项目名，默认 all（全部）。例如: Lang,Math,CSV",
    )
    return parser.parse_args()


def resolve_projects(spec: str):
    if spec.strip().lower() == "all":
        return list(runner.DEFAULT_PROJECTS)
    names = [x.strip() for x in spec.split(",") if x.strip()]
    invalid = [x for x in names if x not in runner.STABLE_COORDS]
    if invalid:
        raise RuntimeError(f"Unknown project(s): {', '.join(invalid)}")
    return names


def main() -> None:
    args = parse_args()
    projects = resolve_projects(args.projects)

    print("[i] projects:", ", ".join(projects))
    print("[i] cache/lib:", runner.LIB_DIR)
    print("[i] cache/project_archives:", runner.PROJECT_TAR_DIR)

    # runtime deps
    evo = runner.ensure_evosuite()
    junit, hamcrest = runner.ensure_junit_hamcrest()
    jacoco_agent, jacoco_cli = runner.ensure_jacoco()
    print("\n=== runtime deps ===")
    print("[OK] evosuite:", evo)
    print("[OK] junit:", junit)
    print("[OK] hamcrest:", hamcrest)
    print("[OK] jacoco-agent:", jacoco_agent)
    print("[OK] jacoco-cli:", jacoco_cli)

    for project in projects:
        prefetch_project(project)

    print("\n=== done ===")
    print("All requested assets are cached locally for offline-friendly runs.")


if __name__ == "__main__":
    main()
