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
    """Resolve affected units while routing every finding to one deck revision author.

    Lesson authors may already be closed. Unit/slide resolution remains useful as a compact context
    index, but it never reopens or assigns work to the original lesson threads.
    """

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
    by_unit: dict[str, list[str]] = {}
    deck_wide: list[str] = []
    for finding in findings:
        finding_id = str(finding.get("id") or "").strip()
        location = finding.get("location")
        if not finding_id or not isinstance(location, dict):
            raise MPresError("Every finding needs an ID and structured location before routing.")
        target_units: set[str] = set()
        deck_scope = False
        for key in ("unit_id", "lesson_id", "unit_ids", "lesson_ids"):
            for value in _as_strings(location.get(key)):
                if value in units:
                    target_units.add(value)
                elif value in {"front", "deck", "global", "all"}:
                    deck_scope = True
                else:
                    raise MPresError(f"Finding {finding_id} names unknown unit {value!r}.")
        for key in ("slide_id", "slide_ids"):
            for slide_id in _as_strings(location.get(key)):
                unit = slide_to_unit.get(slide_id)
                if unit is None:
                    raise MPresError(f"Finding {finding_id} names unknown slide {slide_id!r}.")
                if unit in units:
                    target_units.add(unit)
                else:
                    deck_scope = True
        for key in ("source_path", "source_paths", "file", "files"):
            for source_path in _as_strings(location.get(key)):
                match = SECTION_PATH_RE.search(source_path.replace("\\", "/"))
                if match:
                    unit = match.group("unit")
                    if unit not in units:
                        raise MPresError(
                            f"Finding {finding_id} source path names unknown unit {unit!r}."
                        )
                    target_units.add(unit)
                elif any(
                    token in source_path
                    for token in (
                        "HEADER.md",
                        "presentation.md",
                        "theme.css",
                        "TERMINOLOGY",
                        "COURSE-",
                        "DECK-MANIFEST",
                    )
                ):
                    deck_scope = True
        if str(location.get("scope") or "").strip().lower() in {
            "deck",
            "global",
            "cross_unit",
            "course",
            "all",
        }:
            deck_scope = True
        if len(target_units) > 1:
            deck_scope = True
        if not target_units and not deck_scope:
            raise MPresError(
                f"Finding {finding_id} cannot be routed from its location; add slide_id, unit_id, source_path, or scope."
            )
        for unit in sorted(target_units):
            by_unit.setdefault(unit, []).append(finding_id)
        if deck_scope:
            deck_wide.append(finding_id)
        routes.append(
            {
                "finding_id": finding_id,
                "channel": finding.get("channel"),
                "affected_units": sorted(target_units),
                "deck_wide_or_cross_unit": deck_scope,
                "target_role": "deck-revision-author",
                "location": location,
            }
        )
    return {
        "schema_version": 2,
        "presentation_id": presentation_id,
        "request_source": relative_display(request_source, root),
        "routes": routes,
        "by_unit": {key: sorted(value) for key, value in sorted(by_unit.items())},
        "deck_wide_finding_ids": sorted(set(deck_wide)),
        "target_role": "deck-revision-author",
        "original_lesson_authors_reopened": False,
        "routing_policy": (
            "mechanically resolve affected units from the frozen deck, then route all findings to "
            "one deck-revision-author using a durable context packet"
        ),
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

    source = task / "workers" / "deck-revision-author" / "drafts" / presentation_id / "source"
    source.mkdir(parents=True, exist_ok=True)
    queue_yaml = source / "REVISION-FINDINGS.yaml"
    finding_ids = sorted(
        str(route.get("finding_id"))
        for route in routing.get("routes", [])
        if isinstance(route, dict) and route.get("finding_id")
    )
    write_yaml_atomic(
        queue_yaml,
        {
            "schema_version": 2,
            "presentation_id": presentation_id,
            "target_role": "deck-revision-author",
            "finding_ids": finding_ids,
            "by_unit": routing.get("by_unit", {}),
            "deck_wide_finding_ids": routing.get("deck_wide_finding_ids", []),
            "routing_source": relative_display(routing_path, root),
            "original_lesson_authors_reopened": False,
        },
    )
    template = (
        root / "compat" / "legacy" / "templates" / "structured" / "POST-REVIEW-REVISION.template.md"
    ).read_text(encoding="utf-8")
    queue_md = source / "POST-REVIEW-REVISION.md"
    text = template.replace("[[PRESENTATION_ID]]", presentation_id)
    text = text.replace("[[TARGET]]", "deck-revision-author")
    text = text.replace(
        "[[FINDING_IDS]]", "\n".join(f"- `{item}`" for item in finding_ids) or "- none"
    )
    text += (
        "\n\nThe original lesson-author threads may remain closed. Use `AUTHOR-CONTEXT-PACKET.yaml`, "
        "the frozen source, and this routing index to make all cross-unit revisions coherently.\n"
    )
    queue_md.write_text(text, encoding="utf-8", newline="\n")
    return {
        "routing": relative_display(routing_path, root),
        "revision_queue": relative_display(queue_yaml, root),
        "revision_instructions": relative_display(queue_md, root),
        "target_role": "deck-revision-author",
        "finding_ids": finding_ids,
    }
