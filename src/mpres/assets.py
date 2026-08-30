from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any
from xml.etree import ElementTree

from PIL import Image

from mpres.util import (
    MPresError,
    ensure_within,
    read_json,
    read_yaml,
    relative_display,
    run_command,
    task_path,
    virtualenv_python,
    write_json_atomic,
)

RASTER_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
VECTOR_SUFFIXES = {".svg"}
ALLOWED_GENERATORS = {"python", "manual", "external", "none"}


def _task_policy(root: Path, slug: str) -> dict[str, Any]:
    value = read_yaml(task_path(root, slug) / "EXECUTION-POLICY.yaml") or {}
    if not isinstance(value, dict):
        raise MPresError("EXECUTION-POLICY.yaml must be a mapping.")
    return value


def _asset_registry(source_root: Path) -> dict[str, Any]:
    path = source_root / "ASSET-DECISIONS.yaml"
    value = read_yaml(path)
    if not isinstance(value, dict):
        raise MPresError(f"ASSET-DECISIONS.yaml must be a mapping: {path}")
    assets = value.get("assets")
    if not isinstance(assets, list):
        raise MPresError("ASSET-DECISIONS.yaml must contain an assets list.")
    return value


def _svg_text_report(path: Path, minimum_pt: float) -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []
    text_nodes = 0
    minimum_seen: float | None = None
    try:
        root = ElementTree.fromstring(path.read_text(encoding="utf-8", errors="replace"))
    except ElementTree.ParseError as exc:
        return {"ok": False, "errors": [f"Invalid SVG XML: {exc}"], "warnings": []}
    for node in root.iter():
        if not node.tag.lower().endswith("text"):
            continue
        text_nodes += 1
        raw = node.attrib.get("font-size")
        style = node.attrib.get("style", "")
        if raw is None:
            match = re.search(r"(?:^|;)\s*font-size\s*:\s*([^;]+)", style, re.IGNORECASE)
            raw = match.group(1).strip() if match else None
        if raw is None:
            warnings.append("An SVG text element has no explicit font-size.")
            continue
        match = re.search(r"([0-9]+(?:\.[0-9]+)?)\s*(pt|px|em|rem)?", raw)
        if not match:
            warnings.append(f"Could not parse SVG font-size {raw!r}.")
            continue
        value = float(match.group(1))
        unit = (match.group(2) or "px").lower()
        points = value if unit == "pt" else value * 0.75 if unit == "px" else value * 12
        minimum_seen = points if minimum_seen is None else min(minimum_seen, points)
        if points < minimum_pt:
            errors.append(
                f"SVG text font size {points:.1f}pt is below the required {minimum_pt:.1f}pt."
            )
    return {
        "ok": not errors,
        "errors": errors,
        "warnings": warnings,
        "text_nodes": text_nodes,
        "minimum_text_pt": minimum_seen,
    }


def _raster_report(path: Path, contains_text: bool) -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []
    try:
        with Image.open(path) as image:
            width, height = image.size
            mode = image.mode
    except Exception as exc:
        return {"ok": False, "errors": [f"Cannot read raster image: {type(exc).__name__}: {exc}"], "warnings": []}
    if width < 800 or height < 450:
        warnings.append(f"Raster asset is only {width}x{height}; it may be soft on a 16:9 slide.")
    if contains_text:
        errors.append("Generated raster assets containing text are forbidden; use SVG or native Marp text.")
    return {
        "ok": not errors,
        "errors": errors,
        "warnings": warnings,
        "width": width,
        "height": height,
        "mode": mode,
    }


def validate_assets(
    root: Path,
    slug: str,
    presentation_id: str,
    *,
    source_root: Path,
    stage: str,
) -> dict[str, Any]:
    source_root = source_root.resolve()
    policy = _task_policy(root, slug)
    asset_policy = policy.get("assets", {}) if isinstance(policy, dict) else {}
    task_python_setting = str(asset_policy.get("python_generated", "disabled"))
    minimum_svg_pt = float(asset_policy.get("generated_svg_min_font_pt", 18) or 18)
    registry = _asset_registry(source_root)
    registry_policy = registry.get("policy", {}) if isinstance(registry.get("policy"), dict) else {}
    registry_python_setting = str(registry_policy.get("python_generated", task_python_setting))
    errors: list[str] = []
    warnings: list[str] = []
    entries: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    seen_paths: set[str] = set()
    for raw in registry.get("assets", []):
        if not isinstance(raw, dict):
            errors.append("Every asset decision must be a mapping.")
            continue
        asset_id = str(raw.get("id", "")).strip()
        path_value = str(raw.get("path", "")).strip()
        entry_errors: list[str] = []
        entry_warnings: list[str] = []
        if not asset_id:
            entry_errors.append("Asset ID is required.")
        elif asset_id in seen_ids:
            entry_errors.append(f"Duplicate asset ID: {asset_id}")
        else:
            seen_ids.add(asset_id)
        if not path_value:
            entry_errors.append("Asset path is required.")
            asset_path = source_root / "__missing__"
        else:
            if path_value in seen_paths:
                entry_warnings.append(f"Asset path is reused: {path_value}")
            seen_paths.add(path_value)
            asset_path = (source_root / path_value).resolve()
            try:
                ensure_within(asset_path, source_root, label="asset path")
            except MPresError as exc:
                entry_errors.append(str(exc))
        generated_by = str(raw.get("generated_by", "none")).lower()
        if generated_by not in ALLOWED_GENERATORS:
            entry_errors.append(f"Unsupported generated_by value: {generated_by}")
        approved = raw.get("approved") is True
        purpose = str(raw.get("purpose", "")).strip()
        if not purpose:
            entry_errors.append("Asset purpose is required.")
        if not asset_path.is_file():
            entry_errors.append(f"Asset file does not exist: {path_value}")
        suffix = asset_path.suffix.lower()
        contains_text = bool(raw.get("contains_text"))
        structural: dict[str, Any] = {"ok": True, "errors": [], "warnings": []}
        if asset_path.is_file() and suffix in VECTOR_SUFFIXES:
            structural = _svg_text_report(asset_path, minimum_svg_pt)
        elif asset_path.is_file() and suffix in RASTER_SUFFIXES:
            structural = _raster_report(asset_path, contains_text and generated_by == "python")
        elif asset_path.is_file() and suffix not in {".pdf"}:
            entry_warnings.append(f"Asset type {suffix or '<none>'} has no specialized inspection.")
        entry_errors.extend(structural.get("errors", []))
        entry_warnings.extend(structural.get("warnings", []))

        if generated_by == "python":
            if task_python_setting != "enabled" or registry_python_setting != "enabled":
                entry_errors.append(
                    "Python-generated assets are disabled by task policy or asset-registry policy."
                )
            if not approved:
                entry_errors.append("Python-generated asset must use approved: true.")
            alternatives = raw.get("alternatives_considered")
            if not isinstance(alternatives, list) or len(alternatives) < 2:
                entry_errors.append(
                    "Python-generated asset must document at least two alternatives considered."
                )
            if not str(raw.get("why_image_needed", "")).strip():
                entry_errors.append("Python-generated asset needs why_image_needed.")
            generator_value = str(raw.get("generator", "")).strip()
            report_value = str(raw.get("report", "")).strip()
            if not generator_value or not report_value:
                entry_errors.append("Python-generated asset needs generator and report paths.")
            else:
                generator = (source_root / generator_value).resolve()
                report = (source_root / report_value).resolve()
                for label, candidate in (("generator", generator), ("report", report)):
                    try:
                        ensure_within(candidate, source_root, label=label)
                    except MPresError as exc:
                        entry_errors.append(str(exc))
                if not generator.is_file():
                    entry_errors.append(f"Python generator is missing: {generator_value}")
                if not report.is_file():
                    entry_errors.append(f"Python asset report is missing: {report_value}")
                else:
                    try:
                        report_data = read_json(report)
                    except MPresError as exc:
                        entry_errors.append(str(exc))
                    else:
                        if report_data.get("success") is not True:
                            entry_errors.append("Python asset report does not declare success: true.")
                        if report_data.get("asset_path") not in {path_value, str(asset_path)}:
                            entry_warnings.append(
                                "Python asset report does not identify the registry path exactly."
                            )
                        if report_data.get("arrow_text_overlap_count", 0):
                            entry_errors.append(
                                "Python asset report found arrow/text overlaps; fix the diagram."
                            )
                        if report_data.get("minimum_text_pt") is not None and float(
                            report_data["minimum_text_pt"]
                        ) < minimum_svg_pt:
                            entry_errors.append(
                                "Python asset report found text below the configured minimum."
                            )
        elif approved is False and generated_by not in {"none", "manual", "external"}:
            entry_warnings.append("Unapproved asset is present in the registry.")

        entries.append(
            {
                "id": asset_id,
                "path": path_value,
                "generated_by": generated_by,
                "approved": approved,
                "structural": structural,
                "errors": entry_errors,
                "warnings": entry_warnings,
            }
        )
        errors.extend(f"asset {asset_id or '<missing-id>'}: {item}" for item in entry_errors)
        warnings.extend(f"asset {asset_id or '<missing-id>'}: {item}" for item in entry_warnings)

    report = {
        "schema_version": 1,
        "task_slug": slug,
        "presentation_id": presentation_id,
        "stage": stage,
        "source_root": relative_display(source_root, root),
        "task_python_generated": task_python_setting,
        "registry_python_generated": registry_python_setting,
        "assets": entries,
        "errors": errors,
        "warnings": warnings,
        "success": not errors,
    }
    return report


def run_python_asset(
    root: Path,
    slug: str,
    presentation_id: str,
    *,
    source_root: Path,
    asset_id: str,
    timeout: int = 600,
) -> dict[str, Any]:
    source_root = source_root.resolve()
    policy = _task_policy(root, slug)
    asset_policy = policy.get("assets", {}) if isinstance(policy, dict) else {}
    registry = _asset_registry(source_root)
    if str(asset_policy.get("python_generated", "disabled")) != "enabled":
        raise MPresError("Python-generated assets are disabled in EXECUTION-POLICY.yaml.")
    entry = next(
        (
            item
            for item in registry.get("assets", [])
            if isinstance(item, dict) and str(item.get("id")) == asset_id
        ),
        None,
    )
    if entry is None:
        raise MPresError(f"Unknown asset ID: {asset_id}")
    if entry.get("generated_by") != "python" or entry.get("approved") is not True:
        raise MPresError("Only approved Python-generated assets may be executed.")
    generator = (source_root / str(entry.get("generator", ""))).resolve()
    ensure_within(generator, source_root, label="Python generator")
    if not generator.is_file():
        raise MPresError(f"Python generator is missing: {generator}")
    python = virtualenv_python(root)
    command = [str(python or "python"), str(generator)]
    process = run_command(command, cwd=source_root, timeout=timeout)
    log_path = source_root / "assets" / "reports" / f"{asset_id}-generator.json"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    result = {
        "schema_version": 1,
        "task_slug": slug,
        "presentation_id": presentation_id,
        "asset_id": asset_id,
        "command": command,
        "returncode": process.returncode,
        "stdout": process.stdout[-8000:],
        "stderr": process.stderr[-8000:],
        "success": process.returncode == 0,
    }
    write_json_atomic(log_path, result)
    if process.returncode:
        raise MPresError(f"Python asset generator failed; see {log_path}")
    return result
