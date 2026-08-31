#!/usr/bin/env python3
from __future__ import annotations

import argparse
import compileall
import json
import os
import re
import subprocess
import sys
import tomllib
from pathlib import Path
from typing import Any

import yaml

PLACEHOLDER_RE = re.compile(r"\[\[[A-Z0-9_]+\]\]")
EXPECTED_VERSION = "0.5.0"


class UniqueKeyLoader(yaml.SafeLoader):
    pass


def _construct_mapping(
    loader: UniqueKeyLoader, node: yaml.MappingNode, deep: bool = False
) -> dict[Any, Any]:
    mapping: dict[Any, Any] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in mapping:
            raise ValueError(
                f"duplicate YAML key {key!r} at line {key_node.start_mark.line + 1}"
            )
        mapping[key] = loader.construct_object(value_node, deep=deep)
    return mapping


UniqueKeyLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
    _construct_mapping,
)


def _filled_template_text(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    text = text.replace(
        "[[CONTENT_UNITS_YAML]]",
        '  - id: "u01"\n    title: "Example unit"\n    meeting_number: 1\n'
        '    meeting_label: "第 1 节课"\n    organization_basis: "course_meeting"\n'
        '    source: "sections/u01/section.md"',
    )
    text = text.replace("[[MCQ_ENABLED]]", "true")
    return PLACEHOLDER_RE.sub("example", text)


def _require_paths(root: Path, paths: list[str], errors: list[str]) -> None:
    for relative in paths:
        if not (root / relative).exists():
            errors.append(f"required path is missing: {relative}")


def _semantic_checks(root: Path, errors: list[str]) -> None:
    pyproject = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    project_version = str(pyproject.get("project", {}).get("version"))
    if project_version != EXPECTED_VERSION:
        errors.append(f"pyproject version is {project_version!r}, expected {EXPECTED_VERSION!r}")

    package = json.loads((root / "package.json").read_text(encoding="utf-8"))
    if str(package.get("version")) != EXPECTED_VERSION:
        errors.append("package.json version does not match v0.5.0")
    marp_version = package.get("devDependencies", {}).get("@marp-team/marp-cli")
    if marp_version != "latest":
        errors.append("Marp CLI must remain unpinned as @marp-team/marp-cli: latest")

    model_policy = yaml.safe_load((root / "MODEL-POLICY.yaml").read_text(encoding="utf-8"))
    if model_policy.get("planner") != {
        "model": "gpt-5.6-sol",
        "reasoning_effort": "max",
    }:
        errors.append("MODEL-POLICY.yaml planner runtime must be gpt-5.6-sol/max")
    if model_policy.get("workers") != {
        "model": "gpt-5.6-sol",
        "reasoning_effort": "high",
    }:
        errors.append("MODEL-POLICY.yaml worker runtime must be gpt-5.6-sol/high")

    codex = tomllib.loads((root / ".codex/config.toml").read_text(encoding="utf-8"))
    if codex.get("model") != "gpt-5.6-sol" or codex.get("model_reasoning_effort") != "max":
        errors.append(".codex/config.toml planner runtime does not match MODEL-POLICY.yaml")
    agents = codex.get("agents", {})
    if agents.get("default_subagent_model") != "gpt-5.6-sol" or agents.get(
        "default_subagent_reasoning_effort"
    ) != "high":
        errors.append(".codex/config.toml worker defaults do not match MODEL-POLICY.yaml")

    for path in sorted((root / ".codex/agents").glob("*.toml")):
        value = tomllib.loads(path.read_text(encoding="utf-8"))
        if value.get("model") != "gpt-5.6-sol" or value.get("model_reasoning_effort") != "high":
            errors.append(f"worker runtime mismatch in {path.relative_to(root)}")

    required = [
        "src/mpres/log_daemon.py",
        "src/mpres/logs.py",
        "src/mpres/stages.py",
        "src/mpres/orchestration.py",
        "src/mpres/revision_routing.py",
        "src/mpres/course_consistency.py",
        "src/mpres/density.py",
        "src/mpres/math_inspection.py",
        "src/mpres/maintenance.py",
        ".agents/skills/mathematical-typesetting-inspection/SKILL.md",
        ".agents/skills/presentation-corrective-maintenance/SKILL.md",
        "templates/assignments/TASK-maintenance.template.md",
        "templates/structured/COURSE-TERMINOLOGY.template.yaml",
        "templates/structured/COURSE-SEMANTIC-OBJECTS.template.yaml",
        "templates/structured/CROSS-DECK-HANDOFFS.template.yaml",
        "templates/structured/PRESENTATION-CONTINUITY-MAP.template.yaml",
        "templates/structured/SLIDE-DENSITY-AUDIT.template.yaml",
        "templates/structured/MATH-SOURCE-INVENTORY.template.json",
        "templates/structured/MATH-RENDERER-PROBE.template.json",
    ]
    _require_paths(root, required, errors)

    if (root / "package-lock.json").exists():
        errors.append("package-lock.json is forbidden by the unpinned Marp policy")
    if list((root / "templates").rglob("STAGE-ASSIGNMENT*")):
        errors.append("stage-specific assignment templates are forbidden")
    if list(root.rglob("MATH-PDF-EVIDENCE*")):
        errors.append("MATH-PDF-EVIDENCE artifacts/templates are forbidden")

    forbidden_names = {
        "crash-recovery-and-resumption",
        "workflow-maintenance-safety",
    }
    for path in (root / ".agents/skills").iterdir():
        if path.name in forbidden_names:
            errors.append(f"forbidden heavyweight subsystem skill exists: {path.name}")
    for filename in ("recovery.py", "engine_migration.py", "workflow_freeze.py"):
        if (root / "src/mpres" / filename).exists():
            errors.append(f"forbidden heavyweight subsystem module exists: src/mpres/{filename}")

    logs_source = (root / "src/mpres/logs.py").read_text(encoding="utf-8")
    if "project_log_path" not in logs_source or "submit_log_record" not in logs_source:
        errors.append("logs.py must submit all production logs to the single project log daemon")
    daemon_source = (root / "src/mpres/log_daemon.py").read_text(encoding="utf-8")
    if '"daemon_sequence"' not in daemon_source or "project_log_path" not in daemon_source:
        errors.append("log daemon is missing serialized project-log sequencing")

    stage_source = (root / "src/mpres/stages.py").read_text(encoding="utf-8")
    if "start_stage_sequence" not in stage_source or "submit_stage" not in stage_source:
        errors.append("one-thread staged authoring API is incomplete")
    if "STAGE-ASSIGNMENT" in stage_source:
        errors.append("stages.py still creates stage-specific assignments")

    cli_source = (root / "src/mpres/cli.py").read_text(encoding="utf-8")
    if 'commands.add_parser("log-daemon")' not in cli_source:
        errors.append("CLI does not expose the persistent log daemon")
    if 'commands.add_parser("maintenance")' not in cli_source:
        errors.append("CLI does not expose corrective maintenance")
    if 'commands.add_parser("recover")' in cli_source:
        errors.append("crash-recovery CLI is intentionally out of scope")

    for path in (root / ".codex/agents").glob("*.toml"):
        if path.stem in {"worker1", "worker2"}:
            errors.append(f"numbered worker role is forbidden: {path.name}")


def _run_command(command: list[str], *, root: Path, timeout: int = 180) -> tuple[int, str]:
    try:
        result = subprocess.run(
            command,
            cwd=root,
            env={
                **os.environ,
                "PYTHONPATH": str(root / "src"),
                "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
            },
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        output = (exc.stdout or "") + (exc.stderr or "")
        return 124, f"timed out after {timeout}s\n{output}"
    return result.returncode, result.stdout + result.stderr


def validate(root: Path, *, run_tests: bool) -> list[str]:
    errors: list[str] = []
    ignored_parts = {".venv", "node_modules", ".pytest_cache", ".ruff_cache", "__pycache__"}

    for path in sorted(root.rglob("*.toml")):
        if any(part in ignored_parts for part in path.parts):
            continue
        try:
            with path.open("rb") as handle:
                tomllib.load(handle)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"TOML {path.relative_to(root)}: {exc}")

    for path in sorted(root.rglob("*.json")):
        if any(part in ignored_parts for part in path.parts):
            continue
        try:
            json.loads(_filled_template_text(path))
        except Exception as exc:  # noqa: BLE001
            errors.append(f"JSON {path.relative_to(root)}: {exc}")

    for path in sorted(root.rglob("*.yaml")):
        if any(part in ignored_parts for part in path.parts):
            continue
        try:
            yaml.load(_filled_template_text(path), Loader=UniqueKeyLoader)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"YAML {path.relative_to(root)}: {exc}")

    for script in (root / "start.sh", root / "start-safe.sh"):
        result = subprocess.run(
            ["bash", "-n", str(script)], capture_output=True, text=True, check=False
        )
        if result.returncode:
            errors.append(f"Shell {script.name}: {result.stderr.strip()}")

    if not compileall.compile_dir(root / "src", quiet=1):
        errors.append("compileall failed for src")
    if not compileall.compile_dir(root / "scripts", quiet=1):
        errors.append("compileall failed for scripts")
    if not compileall.compile_dir(root / "tests", quiet=1):
        errors.append("compileall failed for tests")

    try:
        _semantic_checks(root, errors)
    except Exception as exc:  # noqa: BLE001
        errors.append(f"semantic checks failed: {type(exc).__name__}: {exc}")

    help_commands = [
        [sys.executable, "-m", "mpres", "--help"],
        [sys.executable, "-m", "mpres", "log-daemon", "--help"],
        [sys.executable, "-m", "mpres", "stage", "--help"],
        [sys.executable, "-m", "mpres", "review", "--help"],
        [sys.executable, "-m", "mpres", "maintenance", "--help"],
    ]
    for command in help_commands:
        returncode, output = _run_command(command, root=root, timeout=30)
        if returncode:
            errors.append(f"CLI help failed ({' '.join(command[3:]) or 'root'}):\n{output}")

    if run_tests:
        returncode, output = _run_command(
            [sys.executable, "-m", "pytest", "-q"], root=root, timeout=900
        )
        if returncode:
            errors.append("pytest failed:\n" + output)
        else:
            print(output.strip())
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate v0.5.0 configs, templates, policies, CLI, source, and tests."
    )
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--skip-tests", action="store_true")
    args = parser.parse_args()
    root = args.root.resolve()
    errors = validate(root, run_tests=not args.skip_tests)
    if errors:
        for error in errors:
            print(error, file=sys.stderr)
        return 1
    print("Project validation passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
