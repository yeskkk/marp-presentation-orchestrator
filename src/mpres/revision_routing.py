from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from mpres.util import MPresError, read_yaml, relative_display, task_path, write_yaml_atomic

SECTION_PATH_RE = re.compile(r"(?:^|/)sections/(?P<unit>[A-Za-z][A-Za-z0-9_-]{0,31})(?:/|$)")


def _as_strings(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [str(item) for item in value if str(item).strip()]
    return [str(value)]


def build_revision_routing(
    root: Path,
    slug: str,
    presentation_id: str,
    *,
    findings: list[dict[str, Any]],
    request_source: Path,
) -> dict[str, Any]:
    manifest_path = request_source / "DECK-MANIFEST.yaml"
    manifest = read_yaml(manifest_path)
    if not isinstance(manifest, dict) or not isinstance(manifest.get("slides"), list):
        raise MPresError("Frozen review source lacks a usable DECK-MANIFEST.yaml.")
    slide_to_unit = {
        str(row.get("id")): str(row.get("unit"))
        for row in manifest["slides"]
        if isinstance(row, dict) and row.get("id") and row.get("unit")
    }
    units = {
        str(row.get("id"))
        for row in (manifest.get("content_units") or [])
        if isinstance(row, dict) and row.get("id")
    }
    routes: list[dict[str, Any]] = []
    for finding in findings:
        finding_id = str(finding.get("id") or "").strip()
        location = finding.get("location")
        if not finding_id or not isinstance(location, dict):
            raise MPresError("Every finding needs an ID and structured location before routing.")
        target_units: set[str] = set()
        coordinator = False
        for key in ("unit_id", "lesson_id"):
            for value in _as_strings(location.get(key)):
                if value in units:
                    target_units.add(value)
                elif value in {"front", "deck", "global", "all"}:
                    coordinator = True
                else:
                    raise MPresError(f"Finding {finding_id} names unknown unit {value!r}.")
        for key in ("unit_ids", "lesson_ids"):
            for value in _as_strings(location.get(key)):
                if value in units:
                    target_units.add(value)
                elif value in {"front", "deck", "global", "all"}:
                    coordinator = True
                else:
                    raise MPresError(f"Finding {finding_id} names unknown unit {value!r}.")
        slide_values: list[str] = []
        for key in ("slide_id", "slide_ids"):
            slide_values.extend(_as_strings(location.get(key)))
        for slide_id in slide_values:
            unit = slide_to_unit.get(slide_id)
            if unit is None:
                raise MPresError(f"Finding {finding_id} names unknown slide {slide_id!r}.")
            if unit in units:
                target_units.add(unit)
            else:
                coordinator = True
        path_values: list[str] = []
        for key in ("source_path", "source_paths", "file", "files"):
            path_values.extend(_as_strings(location.get(key)))
        for source_path in path_values:
            match = SECTION_PATH_RE.search(source_path.replace("\\", "/"))
            if match:
                unit = match.group("unit")
                if unit not in units:
                    raise MPresError(f"Finding {finding_id} source path names unknown unit {unit!r}.")
                target_units.add(unit)
            elif any(token in source_path for token in ("HEADER.md", "presentation.md", "theme.css", "TERMINOLOGY", "COURSE-")):
                coordinator = True
        scope = str(location.get("scope") or "").strip().lower()
        if scope in {"deck", "global", "cross_unit", "course"}:
            coordinator = True
        if len(target_units) > 1:
            coordinator = True
        if not target_units and not coordinator:
            raise MPresError(
                f"Finding {finding_id} cannot be routed from its location; add slide_id, unit_id, source_path, or scope."
            )
        routes.append(
            {
                "finding_id": finding_id,
                "channel": finding.get("channel"),
                "target_units": sorted(target_units),
                "author_coordinator_reconciliation": coordinator,
                "location": location,
            }
        )
    return {
        "schema_version": 1,
        "presentation_id": presentation_id,
        "request_source": relative_display(request_source, root),
        "routes": routes,
        "routing_policy": "mechanical from frozen deck manifest and structured finding locations",
    }


def write_revision_work_queues(
    root: Path,
    slug: str,
    presentation_id: str,
    routing: dict[str, Any],
) -> dict[str, Any]:
    task = task_path(root, slug)
    review_root = task / "reviews" / presentation_id
    routing_path = review_root / "REVISION-ROUTING.yaml"
    write_yaml_atomic(routing_path, routing)
    by_unit: dict[str, list[str]] = {}
    coordinator_ids: list[str] = []
    for route in routing.get("routes", []):
        if not isinstance(route, dict):
            continue
        finding_id = str(route.get("finding_id"))
        for unit_id in route.get("target_units", []):
            by_unit.setdefault(str(unit_id), []).append(finding_id)
        if route.get("author_coordinator_reconciliation"):
            coordinator_ids.append(finding_id)
    template = (root / "templates" / "structured" / "POST-REVIEW-REVISION.template.md").read_text(
        encoding="utf-8"
    )
    queue_paths: list[str] = []
    for unit_id, finding_ids in sorted(by_unit.items()):
        unit_root = task / "workers" / "lesson-authors" / presentation_id / unit_id
        path = unit_root / "POST-REVIEW-REVISION.md"
        text = template.replace("[[PRESENTATION_ID]]", presentation_id)
        text = text.replace("[[TARGET]]", unit_id)
        text = text.replace("[[FINDING_IDS]]", "\n".join(f"- `{item}`" for item in sorted(finding_ids)))
        path.write_text(text, encoding="utf-8", newline="\n")
        write_yaml_atomic(
            unit_root / "REVISION-FINDINGS.yaml",
            {
                "schema_version": 1,
                "presentation_id": presentation_id,
                "unit_id": unit_id,
                "finding_ids": sorted(finding_ids),
                "routing_source": relative_display(routing_path, root),
            },
        )
        queue_paths.append(relative_display(path, root))
    coordinator_root = task / "workers" / "author-coordinator" / "drafts" / presentation_id
    coordinator_path = coordinator_root / "POST-REVIEW-REVISION.md"
    text = template.replace("[[PRESENTATION_ID]]", presentation_id)
    text = text.replace("[[TARGET]]", "author-coordinator")
    text = text.replace(
        "[[FINDING_IDS]]",
        "\n".join(f"- `{item}`" for item in sorted(set(coordinator_ids))) or "- none",
    )
    coordinator_path.write_text(text, encoding="utf-8", newline="\n")
    queue_paths.append(relative_display(coordinator_path, root))
    return {
        "routing": relative_display(routing_path, root),
        "unit_queues": queue_paths,
        "coordinator_finding_ids": sorted(set(coordinator_ids)),
    }
