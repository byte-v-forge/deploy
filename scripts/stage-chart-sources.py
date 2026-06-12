#!/usr/bin/env python3
"""Stage owner repository migrations and workflow JSON into the Helm chart files."""

from __future__ import annotations

import argparse
import json
import pathlib
import shutil
import sys
from typing import Any


def load_manifest(path: pathlib.Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"{path}: invalid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError("chart source manifest root must be an object")
    if data.get("version") != 1:
        raise ValueError("chart source manifest version must be 1")
    for key in ("migrations", "n8n_workflows"):
        if not isinstance(data.get(key, []), list):
            raise ValueError(f"{key} must be a list")
    return data


def safe_relative(value: Any, field: str) -> pathlib.PurePosixPath:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{field} is required")
    path = pathlib.PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError(f"{field} must be a safe relative path: {value}")
    return path


def ensure_empty_dir(path: pathlib.Path) -> None:
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True, exist_ok=True)


def validate_migrations(source_root: pathlib.Path, entries: list[Any]) -> list[tuple[pathlib.Path, str]]:
    migrations: list[tuple[pathlib.Path, str]] = []
    targets: set[str] = set()
    for index, entry in enumerate(entries, start=1):
        if not isinstance(entry, dict):
            raise ValueError(f"migrations[{index}] must be an object")
        source = source_root / pathlib.Path(safe_relative(entry.get("source"), f"migrations[{index}].source"))
        target_path = safe_relative(entry.get("target"), f"migrations[{index}].target")
        if len(target_path.parts) != 1 or target_path.suffix != ".sql":
            raise ValueError(f"migrations[{index}].target must be a SQL filename")
        target = target_path.as_posix()
        if target in targets:
            raise ValueError(f"duplicate migration target: {target}")
        if not source.is_file():
            raise ValueError(f"missing migration source: {source}")
        targets.add(target)
        migrations.append((source, target))
    return migrations


def validate_workflow_dirs(source_root: pathlib.Path, entries: list[Any]) -> list[pathlib.Path]:
    workflow_dirs: list[pathlib.Path] = []
    for index, entry in enumerate(entries, start=1):
        if not isinstance(entry, dict):
            raise ValueError(f"n8n_workflows[{index}] must be an object")
        source = source_root / pathlib.Path(safe_relative(entry.get("source"), f"n8n_workflows[{index}].source"))
        required = bool(entry.get("required", False))
        if not source.exists():
            if required:
                raise ValueError(f"missing workflow source directory: {source}")
            continue
        if not source.is_dir():
            raise ValueError(f"workflow source is not a directory: {source}")
        workflow_dirs.append(source)
    return workflow_dirs


def copy_workflows(workflow_dirs: list[pathlib.Path], target_dir: pathlib.Path) -> int:
    copied = 0
    for workflow_dir in workflow_dirs:
        for source in sorted(workflow_dir.rglob("*.workflow.json")):
            relative = source.relative_to(workflow_dir)
            target = target_dir / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
            copied += 1
    return copied


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--source-root", required=True)
    parser.add_argument("--chart-files-dir", required=True)
    parser.add_argument("--validate-only", action="store_true")
    args = parser.parse_args()

    try:
        manifest = load_manifest(pathlib.Path(args.manifest).resolve())
        source_root = pathlib.Path(args.source_root).resolve()
        chart_files_dir = pathlib.Path(args.chart_files_dir).resolve()
        migrations = validate_migrations(source_root, manifest.get("migrations", []))
        workflow_dirs = validate_workflow_dirs(source_root, manifest.get("n8n_workflows", []))

        if args.validate_only:
            print("chart source manifest validated")
            return 0

        migrations_dir = chart_files_dir / "migrations"
        workflows_dir = chart_files_dir / "n8n-workflows"
        ensure_empty_dir(migrations_dir)
        ensure_empty_dir(workflows_dir)

        for source, target in migrations:
            shutil.copy2(source, migrations_dir / target)
        workflow_count = copy_workflows(workflow_dirs, workflows_dir)
    except (OSError, ValueError) as exc:
        print(f"chart source staging failed: {exc}", file=sys.stderr)
        return 1

    print(f"staged {len(migrations)} migrations and {workflow_count} workflow files")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
