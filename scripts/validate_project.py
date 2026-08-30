#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tomllib
from pathlib import Path
from typing import Any

import yaml

PLACEHOLDER_RE = re.compile(r"\[\[[A-Z0-9_]+\]\]")


class UniqueKeyLoader(yaml.SafeLoader):
    pass


def _construct_mapping(loader: UniqueKeyLoader, node: yaml.MappingNode, deep: bool = False) -> dict[Any, Any]:
    mapping: dict[Any, Any] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in mapping:
            raise ValueError(f"duplicate YAML key {key!r} at line {key_node.start_mark.line + 1}")
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
        '  - id: "u01"\n    title: "Example unit"\n    source: "sections/u01/section.md"',
    )
    text = text.replace("[[MCQ_ENABLED]]", "true")
    return PLACEHOLDER_RE.sub("example", text)


def validate(root: Path, *, run_tests: bool) -> list[str]:
    errors: list[str] = []
    for path in sorted(root.rglob("*.toml")):
        if any(part in {".venv", "node_modules"} for part in path.parts):
            continue
        try:
            with path.open("rb") as handle:
                tomllib.load(handle)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"TOML {path.relative_to(root)}: {exc}")

    for path in sorted(root.rglob("*.json")):
        if any(part in {".venv", "node_modules", ".pytest_cache", "__pycache__"} for part in path.parts):
            continue
        try:
            json.loads(_filled_template_text(path))
        except Exception as exc:  # noqa: BLE001
            errors.append(f"JSON {path.relative_to(root)}: {exc}")

    for path in sorted(root.rglob("*.yaml")):
        if any(part in {".venv", "node_modules", ".pytest_cache", "__pycache__"} for part in path.parts):
            continue
        try:
            yaml.load(_filled_template_text(path), Loader=UniqueKeyLoader)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"YAML {path.relative_to(root)}: {exc}")

    for script in (root / "start.sh", root / "start-safe.sh"):
        result = subprocess.run(["bash", "-n", str(script)], capture_output=True, text=True, check=False)
        if result.returncode:
            errors.append(f"Shell {script.name}: {result.stderr.strip()}")

    if (root / "package-lock.json").exists():
        errors.append("package-lock.json is forbidden by the unpinned Marp policy")

    if run_tests:
        result = subprocess.run(
            [sys.executable, "-m", "pytest", "-q"],
            cwd=root,
            env={**__import__("os").environ, "PYTHONPATH": str(root / "src")},
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode:
            errors.append("pytest failed:\n" + result.stdout + result.stderr)
        else:
            print(result.stdout.strip())
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate project templates, configs, scripts, and tests.")
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
