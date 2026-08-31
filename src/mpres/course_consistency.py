from __future__ import annotations

from pathlib import Path
from typing import Any

from mpres.state import get_presentation, load_state
from mpres.tasks import require_gate
from mpres.util import MPresError, read_yaml, relative_display, task_path, write_json_atomic

COURSE_FILES = (
    "COURSE-TERMINOLOGY.yaml",
    "COURSE-SEMANTIC-OBJECTS.yaml",
    "CROSS-DECK-HANDOFFS.yaml",
)


def initialize_course_registries(root: Path, task: Path) -> None:
    templates = root / "templates" / "structured"
    mapping = {
        "COURSE-TERMINOLOGY.yaml": "COURSE-TERMINOLOGY.template.yaml",
        "COURSE-SEMANTIC-OBJECTS.yaml": "COURSE-SEMANTIC-OBJECTS.template.yaml",
        "CROSS-DECK-HANDOFFS.yaml": "CROSS-DECK-HANDOFFS.template.yaml",
    }
    for destination, template in mapping.items():
        path = task / destination
        if not path.exists():
            path.write_text((templates / template).read_text(encoding="utf-8"), encoding="utf-8", newline="\n")


def _mapping(path: Path, list_key: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    value = read_yaml(path)
    if not isinstance(value, dict):
        raise MPresError(f"{path.name} must contain a mapping.")
    rows = value.get(list_key)
    if not isinstance(rows, list) or any(not isinstance(item, dict) for item in rows):
        raise MPresError(f"{path.name} must contain a {list_key} list of mappings.")
    return value, list(rows)


def validate_course_consistency(
    root: Path,
    slug: str,
    presentation_id: str,
    *,
    source: Path,
    write_report: bool = False,
    stage: str | None = None,
) -> dict[str, Any]:
    state = require_gate(root, slug)
    if state.get("kind") != "course":
        return {
            "schema_version": 1,
            "task_slug": slug,
            "presentation_id": presentation_id,
            "applicable": False,
            "errors": [],
            "warnings": [],
            "success": True,
        }
    task = task_path(root, slug)
    errors: list[str] = []
    warnings: list[str] = []
    for name in COURSE_FILES:
        if not (task / name).is_file():
            errors.append(f"Missing course-level registry: {name}")
    if errors:
        return {
            "schema_version": 1,
            "task_slug": slug,
            "presentation_id": presentation_id,
            "applicable": True,
            "errors": errors,
            "warnings": warnings,
            "success": False,
        }

    _, course_terms = _mapping(task / "COURSE-TERMINOLOGY.yaml", "terms")
    _, course_objects = _mapping(task / "COURSE-SEMANTIC-OBJECTS.yaml", "objects")
    _, handoffs = _mapping(task / "CROSS-DECK-HANDOFFS.yaml", "handoffs")
    term_ids = {str(item.get("id")) for item in course_terms if item.get("id")}
    object_ids = {str(item.get("id")) for item in course_objects if item.get("id")}
    if len(term_ids) != len([item for item in course_terms if item.get("id")]):
        errors.append("COURSE-TERMINOLOGY.yaml contains duplicate term IDs.")
    if len(object_ids) != len([item for item in course_objects if item.get("id")]):
        errors.append("COURSE-SEMANTIC-OBJECTS.yaml contains duplicate object IDs.")

    terminology_path = source / "TERMINOLOGY.yaml"
    semantic_path = source / "SEMANTIC-OBJECTS.yaml"
    continuity_path = source / "PRESENTATION-CONTINUITY-MAP.yaml"
    if not terminology_path.is_file():
        errors.append("Presentation source is missing TERMINOLOGY.yaml.")
        deck_terms: list[dict[str, Any]] = []
    else:
        _, deck_terms = _mapping(terminology_path, "terms")
    if not semantic_path.is_file():
        errors.append("Presentation source is missing SEMANTIC-OBJECTS.yaml.")
        deck_objects: list[dict[str, Any]] = []
    else:
        _, deck_objects = _mapping(semantic_path, "objects")
    if not continuity_path.is_file():
        errors.append("Presentation source is missing PRESENTATION-CONTINUITY-MAP.yaml.")
        continuity: dict[str, Any] = {}
    else:
        value = read_yaml(continuity_path)
        continuity = value if isinstance(value, dict) else {}
        if not continuity:
            errors.append("PRESENTATION-CONTINUITY-MAP.yaml must contain a mapping.")

    for item in deck_terms:
        local_id = str(item.get("id") or "").strip()
        course_id = str(item.get("course_term_id") or "").strip()
        if not local_id:
            errors.append("Every presentation terminology entry needs an id.")
        if not course_id:
            errors.append(f"Presentation term {local_id or '<unknown>'} needs course_term_id.")
        elif course_id not in term_ids:
            errors.append(f"Presentation term {local_id} refers to unknown course term {course_id}.")

    for item in deck_objects:
        object_id = str(item.get("id") or "").strip()
        scope = str(item.get("scope") or "").strip()
        if not object_id:
            errors.append("Every semantic object needs an id.")
            continue
        if scope not in {"course", "presentation_local"}:
            errors.append(f"Semantic object {object_id} needs scope: course or presentation_local.")
        if scope == "course" and object_id not in object_ids:
            errors.append(f"Course-scoped object {object_id} is absent from COURSE-SEMANTIC-OBJECTS.yaml.")

    presentations = [item for item in state.get("presentations", []) if isinstance(item, dict)]
    position = next((index for index, item in enumerate(presentations) if item.get("id") == presentation_id), None)
    if position is None:
        errors.append(f"Presentation {presentation_id} is absent from task state.")
    else:
        previous_id = str(presentations[position - 1].get("id")) if position > 0 else None
        incoming = continuity.get("incoming_from")
        if previous_id is None:
            if incoming not in {None, "", "null"}:
                warnings.append("The first presentation normally has incoming_from: null.")
        else:
            if str(incoming or "") != previous_id:
                errors.append(
                    f"PRESENTATION-CONTINUITY-MAP.yaml must declare incoming_from: {previous_id}."
                )
            matching = [
                row
                for row in handoffs
                if str(row.get("from_presentation")) == previous_id
                and str(row.get("to_presentation")) == presentation_id
            ]
            if not matching:
                errors.append(
                    f"CROSS-DECK-HANDOFFS.yaml lacks a {previous_id} -> {presentation_id} handoff."
                )
            elif not any(
                row.get("terms_to_reactivate") or row.get("objects_to_reactivate") or row.get("bridge")
                for row in matching
            ):
                errors.append(
                    f"The {previous_id} -> {presentation_id} handoff must specify reactivation or a bridge."
                )

    reactivated_terms = continuity.get("reactivated_terms") or []
    reactivated_objects = continuity.get("reactivated_objects") or []
    unknown_terms = sorted(str(item) for item in reactivated_terms if str(item) not in term_ids)
    unknown_objects = sorted(str(item) for item in reactivated_objects if str(item) not in object_ids)
    if unknown_terms:
        errors.append("Continuity map names unknown course terms: " + ", ".join(unknown_terms))
    if unknown_objects:
        errors.append("Continuity map names unknown course objects: " + ", ".join(unknown_objects))

    report = {
        "schema_version": 1,
        "task_slug": slug,
        "presentation_id": presentation_id,
        "applicable": True,
        "source": relative_display(source, root),
        "course_term_count": len(course_terms),
        "course_object_count": len(course_objects),
        "presentation_term_count": len(deck_terms),
        "presentation_object_count": len(deck_objects),
        "errors": errors,
        "warnings": warnings,
        "success": not errors,
    }
    if write_report:
        target_stage = stage or "author"
        build = (
            task
            / "workers"
            / ("author-coordinator" if target_stage == "author" else "release-coordinator")
            / ("drafts" if target_stage == "author" else "release-ready")
            / presentation_id
            / "build"
        )
        build.mkdir(parents=True, exist_ok=True)
        write_json_atomic(build / f"course-consistency-{target_stage}.json", report)
    return report
