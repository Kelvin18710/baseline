#!/usr/bin/env python3
"""Prefetch all stable project assets for offline execution.

What this script downloads:
- project source archives -> baseline/shared_project_packages/project_archives
- EvoSuite/JUnit/Hamcrest/JaCoCo runtime deps -> evosuite/cache/lib

After this, run.py can prepare per-tool workspaces only from the shared archive directory.
"""

import argparse
from pathlib import Path
import urllib.request

import run as runner


def project_archive_path(project: str, artifact: str, version: str) -> Path:
    archive_dir = runner.SHARED_PROJECT_ARCHIVES_DIR
    archive_dir.mkdir(parents=True, exist_ok=True)
    return archive_dir / f"{project.lower()}-{artifact}-{version}-sources.jar"


def download_project_archive(project: str, artifact: str, version: str, group: str) -> Path:
    dst = project_archive_path(project, artifact, version)
    if dst.exists():
        return dst
    url = runner.maven_url(group, artifact, version, classifier="sources")
    print(f"[i] Downloading shared archive from {url}")
    urllib.request.urlretrieve(url, dst)
    return dst


def prefetch_project(project: str) -> None:
    artifact, version, group = runner.STABLE_COORDS[project]
    print(f"\n=== prefetch {project} ({group}:{artifact}:{version}) ===")
    archive = download_project_archive(project, artifact, version, group)
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
    print("[i] shared/project_archives:", runner.SHARED_PROJECT_ARCHIVES_DIR)

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
    print("All requested assets are cached for offline-friendly runs.")


if __name__ == "__main__":
    main()
