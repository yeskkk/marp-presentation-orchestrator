from __future__ import annotations

import re
import shutil
from pathlib import Path
from typing import Any

from mpres.geogebra import aggregate_unit_geogebra_records, validate_unit_geogebra_registry
from mpres.logs import append_log
from mpres.state import REVIEW_CHANNELS, get_presentation, save_state
from mpres.tasks import require_gate
from mpres.util import (
    MPresError,
    copy_source_tree,
    read_yaml,
    relative_display,
    safe_id,
    task_path,
    text_placeholders,
    utc_now,
    write_json_atomic,
    write_yaml_atomic,
)

PRESENTATION_ID_RE = re.compile(r"[A-Za-z][A-Za-z0-9_-]{1,31}")
UNIT_ID_RE = re.compile(r"[A-Za-z][A-Za-z0-9_-]{0,31}")
ROLES = {
    "author-coordinator",
    "lesson-author",
    "review-coordinator",
    "specialist-reviewer",
    "release-coordinator",
}


def parse_presentation_specs(specs: list[str]) -> list[tuple[str, str]]:
    parsed: list[tuple[str, str]] = []
    seen: set[str] = set()
    for spec in specs:
        if "::" not in spec:
            raise MPresError(f"Presentation must use ID::Title syntax: {spec!r}")
        presentation_id, title = (part.strip() for part in spec.split("::", 1))
        if not PRESENTATION_ID_RE.fullmatch(presentation_id):
            raise MPresError(f"Invalid presentation ID: {presentation_id!r}")
        if not title:
            raise MPresError(f"Presentation title is empty for {presentation_id}.")
        if presentation_id in seen:
            raise MPresError(f"Duplicate presentation ID: {presentation_id}")
        seen.add(presentation_id)
        parsed.append((presentation_id, title))
    if not parsed:
        raise MPresError("At least one --presentation ID::Title is required.")
    return parsed


def parse_unit_specs(
    specs: list[str], presentation_ids: set[str]
) -> dict[str, list[tuple[str, str]]]:
    result: dict[str, list[tuple[str, str]]] = {item: [] for item in presentation_ids}
    seen: set[tuple[str, str]] = set()
    for spec in specs:
        parts = [part.strip() for part in spec.split("::", 2)]
        if len(parts) != 3:
            raise MPresError(f"Content unit must use PRESENTATION_ID::UNIT_ID::Title: {spec!r}")
        presentation_id, unit_id, title = parts
        if presentation_id not in presentation_ids:
            raise MPresError(f"Unit refers to unknown presentation: {presentation_id}")
        if not UNIT_ID_RE.fullmatch(unit_id):
            raise MPresError(f"Invalid content-unit ID: {unit_id!r}")
        if not title:
            raise MPresError(f"Content-unit title is empty for {presentation_id}/{unit_id}.")
        key = (presentation_id, unit_id)
        if key in seen:
            raise MPresError(f"Duplicate content unit: {presentation_id}/{unit_id}")
        seen.add(key)
        result[presentation_id].append((unit_id, title))
    missing = [presentation_id for presentation_id, units in result.items() if not units]
    if missing:
        raise MPresError(
            "Every presentation needs at least one lesson/content unit. Missing: " + ", ".join(missing)
        )
    return result


def _replace(text: str, values: dict[str, str]) -> str:
    for old, new in values.items():
        text = text.replace(old, new)
    return text


def _role_override(role: str) -> str:
    descriptions = {
        "author-coordinator": (
            "Coordinate one presentation, complete structured maps, supervise parallel lesson "
            "authors, assemble presentation.md, build PDF, inspect, and respond to findings."
        ),
        "lesson-author": (
            "Work only on the assigned content unit and hand off section.md plus structured evidence."
        ),
        "review-coordinator": (
            "Supervise five specialist channels over three rounds; do not edit author source."
        ),
        "specialist-reviewer": (
            "Review exactly one channel and round against a frozen request; do not edit source."
        ),
        "release-coordinator": (
            "Perform terminal closure and mechanical PDF release only; do not create new findings."
        ),
    }
    return (
        f"# {role} directory override\n\n"
        f"- {descriptions[role]}\n"
        "- Read the exact assignment supplied by the parent and the matching local skill.\n"
        "- Screenshots, PDF raster images, contact sheets, and model vision are forbidden.\n"
        "- No HTML artifact is generated or reviewed.\n"
        "- Log concise UTC progress and write durable checkpoints.\n"
        "- Do not alter TASK.md or another role's files.\n"
    )


def _templates(root: Path) -> dict[str, str]:
    mapping = {
        "author": "templates/assignments/TASK-author-coordinator.template.md",
        "lesson": "templates/assignments/TASK-lesson-author.template.md",
        "review": "templates/assignments/TASK-review-coordinator.template.md",
        "release": "templates/assignments/TASK-release-coordinator.template.md",
        "header": "templates/presentation-header.template.md",
        "section": "templates/section.template.md",
    }
    return {name: (root / path).read_text(encoding="utf-8") for name, path in mapping.items()}


def _write_structured_templates(
    root: Path,
    source: Path,
    presentation_id: str,
    title: str,
    units: list[tuple[str, str]],
) -> None:
    structured = {
        "DECK-MANIFEST.yaml": "DECK-MANIFEST.template.yaml",
        "PEDAGOGY-MAP.md": "PEDAGOGY-MAP.template.md",
        "EXAMPLE-MAP.md": "EXAMPLE-MAP.template.md",
        "TERMINOLOGY.md": "TERMINOLOGY.template.md",
        "SEMANTIC-OBJECTS.yaml": "SEMANTIC-OBJECTS.template.yaml",
        "ASSET-DECISIONS.yaml": "ASSET-DECISIONS.template.yaml",
        "GEOGEBRA-RESOURCES.yaml": "GEOGEBRA-RESOURCES.template.yaml",
        "SELF-CHECK.md": "SELF-CHECK.template.md",
        "RELEASE-RETROSPECTIVE.md": "RELEASE-RETROSPECTIVE.template.md",
    }
    unit_yaml = "\n".join(
        f"  - id: \"{unit_id}\"\n    title: \"{unit_title}\"\n    source: \"sections/{unit_id}/section.md\""
        for unit_id, unit_title in units
    )
    for destination, template_name in structured.items():
        text = (root / "templates" / "structured" / template_name).read_text(encoding="utf-8")
        text = _replace(
            text,
            {
                "[[PRESENTATION_ID]]": presentation_id,
                "[[PRESENTATION_TITLE]]": title,
                "[[CONTENT_UNITS_YAML]]": unit_yaml,
                "[[SCOPE_ID]]": presentation_id,
            },
        )
        (source / destination).write_text(text, encoding="utf-8", newline="\n")


def initialize_production(
    root: Path,
    slug: str,
    presentation_specs: list[str],
    unit_specs: list[str],
) -> dict[str, Any]:
    state = require_gate(root, slug)
    if state.get("presentations"):
        raise MPresError("Production units have already been initialized for this task.")
    if state.get("phase") != "confirmed":
        raise MPresError(f"Expected confirmed phase, got {state.get('phase')!r}.")

    presentations = parse_presentation_specs(presentation_specs)
    units_by_presentation = parse_unit_specs(unit_specs, {item[0] for item in presentations})
    task = task_path(root, slug)
    templates = _templates(root)

    role_dirs = {
        "author-coordinator": "author-coordinator",
        "lesson-authors": "lesson-author",
        "review-coordinator": "review-coordinator",
        "specialist-reviewers": "specialist-reviewer",
        "release-coordinator": "release-coordinator",
    }
    for directory_name, logical_role in role_dirs.items():
        role_root = task / "workers" / directory_name
        role_root.mkdir(parents=True, exist_ok=True)
        (role_root / "AGENTS.override.md").write_text(
            _role_override(logical_role), encoding="utf-8", newline="\n"
        )

    state_presentations: list[dict[str, Any]] = []
    for presentation_id, title in presentations:
        units = units_by_presentation[presentation_id]
        author_root = task / "workers" / "author-coordinator"
        author_assignment = author_root / "assignments" / presentation_id / "TASK-AUTHOR-COORDINATOR.md"
        author_source = author_root / "drafts" / presentation_id / "source"
        author_build = author_root / "drafts" / presentation_id / "build"
        lesson_root = task / "workers" / "lesson-authors" / presentation_id
        review_root = task / "reviews" / presentation_id
        review_assignment = (
            task
            / "workers"
            / "review-coordinator"
            / "assignments"
            / presentation_id
            / "TASK-REVIEW-COORDINATOR.md"
        )
        release_assignment = (
            task
            / "workers"
            / "release-coordinator"
            / "assignments"
            / presentation_id
            / "TASK-RELEASE-COORDINATOR.md"
        )
        for directory in [
            author_assignment.parent,
            author_source / "sections",
            author_source / "assets",
            author_build,
            author_root / "checkpoints" / presentation_id,
            review_root,
            review_assignment.parent,
            release_assignment.parent,
            task / "workers" / "release-coordinator" / "approved" / presentation_id,
            task / "deliverables" / presentation_id,
        ]:
            directory.mkdir(parents=True, exist_ok=True)

        unit_table = "\n".join(f"- `{unit_id}` — {unit_title}" for unit_id, unit_title in units)
        author_assignment.write_text(
            _replace(
                templates["author"],
                {
                    "[[PRESENTATION_ID]]": presentation_id,
                    "[[PRESENTATION_TITLE]]": title,
                    "[[TASK_MD_PATH]]": relative_display(task / "TASK.md", root),
                    "[[CONTENT_UNIT_TABLE]]": unit_table,
                    "[[AUTHOR_SOURCE_PATH]]": relative_display(author_source, root),
                    "[[AUTHOR_BUILD_PATH]]": relative_display(author_build, root),
                    "[[LESSON_AUTHOR_ROOT]]": relative_display(lesson_root, root),
                    "[[REVIEW_ROOT]]": relative_display(review_root, root),
                },
            ),
            encoding="utf-8",
            newline="\n",
        )
        review_assignment.write_text(
            _replace(
                templates["review"],
                {
                    "[[PRESENTATION_ID]]": presentation_id,
                    "[[PRESENTATION_TITLE]]": title,
                    "[[REVIEW_ROOT]]": relative_display(review_root, root),
                    "[[FINDINGS_REGISTRY_PATH]]": relative_display(review_root / "findings.yaml", root),
                    "[[TASK_MD_PATH]]": relative_display(task / "TASK.md", root),
                },
            ),
            encoding="utf-8",
            newline="\n",
        )
        release_assignment.write_text(
            _replace(
                templates["release"],
                {
                    "[[PRESENTATION_ID]]": presentation_id,
                    "[[PRESENTATION_TITLE]]": title,
                    "[[CLOSURE_REQUEST_PATH]]": relative_display(
                        review_root / "terminal" / "request" / "request.json", root
                    ),
                    "[[FINDINGS_REGISTRY_PATH]]": relative_display(review_root / "findings.yaml", root),
                    "[[APPROVED_SOURCE_PATH]]": relative_display(
                        task
                        / "workers"
                        / "release-coordinator"
                        / "approved"
                        / presentation_id
                        / "source",
                        root,
                    ),
                    "[[RELEASE_BUILD_PATH]]": relative_display(
                        task
                        / "workers"
                        / "release-coordinator"
                        / "approved"
                        / presentation_id
                        / "build",
                        root,
                    ),
                    "[[DELIVERABLE_PATH]]": relative_display(
                        task / "deliverables" / presentation_id, root
                    ),
                },
            ),
            encoding="utf-8",
            newline="\n",
        )

        header = _replace(
            templates["header"],
            {
                "[[PRESENTATION_ID]]": presentation_id,
                "[[PRESENTATION_TITLE]]": title,
            },
        )
        (author_source / "HEADER.md").write_text(header, encoding="utf-8", newline="\n")
        shutil.copy2(root / "themes" / "mathist-academic.css", author_source / "theme.css")
        (author_source / "README.md").write_text(
            f"# Integrated Marp source — {presentation_id}: {title}\n\n"
            "Lesson fragments are assembled into presentation.md. The standard build produces PDF only.\n",
            encoding="utf-8",
            newline="\n",
        )
        _write_structured_templates(root, author_source, presentation_id, title, units)

        unit_state: list[dict[str, Any]] = []
        for unit_id, unit_title in units:
            unit_dir = lesson_root / unit_id
            unit_source = unit_dir / "source"
            for directory in [unit_source / "assets", unit_dir / "logs", unit_dir / "checkpoints"]:
                directory.mkdir(parents=True, exist_ok=True)
            assignment = _replace(
                templates["lesson"],
                {
                    "[[PRESENTATION_ID]]": presentation_id,
                    "[[UNIT_ID]]": unit_id,
                    "[[UNIT_TITLE]]": unit_title,
                    "[[TERMINOLOGY_PATH]]": relative_display(author_source / "TERMINOLOGY.md", root),
                    "[[SEMANTIC_OBJECTS_PATH]]": relative_display(
                        author_source / "SEMANTIC-OBJECTS.yaml", root
                    ),
                    "[[DECK_MANIFEST_PATH]]": relative_display(
                        author_source / "DECK-MANIFEST.yaml", root
                    ),
                    "[[EXAMPLE_MAP_PATH]]": relative_display(author_source / "EXAMPLE-MAP.md", root),
                    "[[ASSET_DECISIONS_PATH]]": relative_display(
                        author_source / "ASSET-DECISIONS.yaml", root
                    ),
                    "[[GEOGEBRA_UNIT_RESOURCES_PATH]]": relative_display(
                        unit_source / "GEOGEBRA-RESOURCES.yaml", root
                    ),
                    "[[UNIT_SOURCE_PATH]]": relative_display(unit_source, root),
                    "[[UNIT_CHECKPOINT_PATH]]": relative_display(unit_dir / "checkpoints", root),
                },
            )
            (unit_dir / "TASK-LESSON-AUTHOR.md").write_text(
                assignment, encoding="utf-8", newline="\n"
            )
            first_slide_id = f"{presentation_id}-{unit_id}-s01"
            section = _replace(
                templates["section"],
                {
                    "[[SLIDE_ID]]": first_slide_id,
                    "[[SLIDE_TITLE]]": unit_title,
                },
            )
            (unit_source / "section.md").write_text(section, encoding="utf-8", newline="\n")
            unit_manifest = (
                root / "templates" / "structured" / "UNIT-MANIFEST.template.yaml"
            ).read_text(encoding="utf-8")
            unit_manifest = _replace(
                unit_manifest,
                {
                    "[[PRESENTATION_ID]]": presentation_id,
                    "[[UNIT_ID]]": unit_id,
                    "[[UNIT_TITLE]]": unit_title,
                    "[[SLIDE_ID]]": first_slide_id,
                },
            )
            (unit_source / "UNIT-MANIFEST.yaml").write_text(
                unit_manifest, encoding="utf-8", newline="\n"
            )
            geogebra_unit = (
                root / "templates" / "structured" / "GEOGEBRA-UNIT-RESOURCES.template.yaml"
            ).read_text(encoding="utf-8")
            geogebra_unit = _replace(
                geogebra_unit,
                {
                    "[[PRESENTATION_ID]]": presentation_id,
                    "[[UNIT_ID]]": unit_id,
                },
            )
            (unit_source / "GEOGEBRA-RESOURCES.yaml").write_text(
                geogebra_unit, encoding="utf-8", newline="\n"
            )
            self_check = (
                root / "templates" / "structured" / "SELF-CHECK.template.md"
            ).read_text(encoding="utf-8")
            self_check = self_check.replace("[[SCOPE_ID]]", f"{presentation_id}/{unit_id}")
            (unit_source / "SELF-CHECK.md").write_text(
                self_check, encoding="utf-8", newline="\n"
            )
            checkpoint = (
                root / "templates" / "structured" / "CHECKPOINT.template.json"
            ).read_text(encoding="utf-8")
            checkpoint = _replace(
                checkpoint,
                {
                    "[[UTC]]": utc_now(),
                    "[[ROLE]]": "lesson-author",
                    "[[PRESENTATION_ID]]": presentation_id,
                    "[[UNIT_ID_OR_NULL]]": unit_id,
                },
            )
            (unit_dir / "checkpoints" / "latest.json").write_text(
                checkpoint, encoding="utf-8", newline="\n"
            )
            unit_state.append(
                {"id": unit_id, "title": unit_title, "status": "assigned", "integrated_utc": None}
            )

        write_json_atomic(
            review_root / "rounds.json",
            {"schema_version": 1, "presentation_id": presentation_id, "rounds": {}},
        )
        (review_root / "findings.yaml").write_text(
            f"schema_version: 1\npresentation_id: {presentation_id}\nfindings: []\n",
            encoding="utf-8",
            newline="\n",
        )
        state_presentations.append(
            {
                "id": presentation_id,
                "title": title,
                "status": "authoring",
                "active": False,
                "content_units": unit_state,
                "active_round": None,
                "rounds": {},
                "finalized_utc": None,
                "delivery_sequence": None,
                "artifacts": {},
            }
        )

    policy = read_yaml(task / "EXECUTION-POLICY.yaml") or {}
    authoring = policy.get("authoring", {}) if isinstance(policy, dict) else {}
    max_parallel = int(authoring.get("max_parallel_presentations", 2) or 2)
    initial_active = 1 if state.get("stop_mode") in {"pilot", "each"} else max(1, max_parallel)
    for item in state_presentations[:initial_active]:
        item["active"] = True
    state["presentations"] = state_presentations
    state["phase"] = "working"
    state["production_initialized_utc"] = utc_now()
    save_state(root, slug, state)
    append_log(
        root,
        slug,
        actor="planner",
        kind="decision",
        message=(
            "Initialized role-based Marp production. Each course meeting/content unit has its own "
            "lesson-author directory; presentations and lesson authors may run in bounded parallel."
        ),
        data={
            "presentations": [item[0] for item in presentations],
            "review_channels": list(REVIEW_CHANNELS),
        },
    )
    return state


def assignment_path(
    root: Path,
    slug: str,
    role: str,
    presentation_id: str,
    *,
    unit_id: str | None = None,
    round_name: str | None = None,
    channel: str | None = None,
) -> Path:
    task = task_path(root, slug)
    safe_id(presentation_id, label="presentation ID")
    if role == "author-coordinator":
        return task / "workers" / role / "assignments" / presentation_id / "TASK-AUTHOR-COORDINATOR.md"
    if role == "lesson-author":
        if not unit_id:
            raise MPresError("lesson-author assignment requires --unit.")
        safe_id(unit_id, label="content-unit ID")
        return task / "workers" / "lesson-authors" / presentation_id / unit_id / "TASK-LESSON-AUTHOR.md"
    if role == "review-coordinator":
        return task / "workers" / role / "assignments" / presentation_id / "TASK-REVIEW-COORDINATOR.md"
    if role == "release-coordinator":
        return task / "workers" / role / "assignments" / presentation_id / "TASK-RELEASE-COORDINATOR.md"
    if role == "specialist-reviewer":
        if not round_name or not channel:
            raise MPresError("specialist-reviewer assignment requires --round and --channel.")
        return (
            task
            / "workers"
            / "specialist-reviewers"
            / presentation_id
            / round_name
            / channel
            / "TASK-SPECIALIST-REVIEWER.md"
        )
    raise MPresError(f"Unknown role: {role}")


def check_assignment(
    root: Path,
    slug: str,
    role: str,
    presentation_id: str,
    *,
    unit_id: str | None = None,
    round_name: str | None = None,
    channel: str | None = None,
) -> dict[str, Any]:
    path = assignment_path(
        root,
        slug,
        role,
        presentation_id,
        unit_id=unit_id,
        round_name=round_name,
        channel=channel,
    )
    if not path.is_file():
        return {"ready": False, "path": relative_display(path, root), "placeholders": ["missing"]}
    placeholders = text_placeholders(path)
    text = path.read_text(encoding="utf-8")
    minimum = 600 if role == "lesson-author" else 800
    return {
        "ready": not placeholders and len(text.strip()) >= minimum,
        "path": relative_display(path, root),
        "placeholders": placeholders,
        "characters": len(text),
    }


def activate_presentations(root: Path, slug: str, presentation_ids: list[str]) -> dict[str, Any]:
    state = require_gate(root, slug)
    if state.get("phase") != "working":
        raise MPresError(f"Cannot activate presentations in phase {state.get('phase')!r}.")
    activated: list[str] = []
    for presentation_id in presentation_ids:
        presentation = get_presentation(state, presentation_id)
        if presentation.get("status") == "finalized":
            raise MPresError(f"Presentation {presentation_id} is already finalized.")
        presentation["active"] = True
        activated.append(presentation_id)
    save_state(root, slug, state)
    append_log(
        root,
        slug,
        actor="planner",
        kind="decision",
        message="Activated presentation coordinators for production.",
        data={"presentations": activated},
    )
    return {"activated": activated, "phase": state.get("phase")}


def _clean_fragment(text: str, path: Path) -> str:
    stripped = text.strip()
    if stripped.startswith("---"):
        raise MPresError(f"Lesson fragment must not contain YAML frontmatter: {path}")
    return stripped.strip("\n")


def assemble_units(root: Path, slug: str, presentation_id: str) -> dict[str, Any]:
    state = require_gate(root, slug)
    presentation = get_presentation(state, presentation_id)
    if presentation.get("status") not in {
        "authoring",
        "initial_changes",
        "incremental_changes",
        "terminal_revision",
    }:
        raise MPresError(f"Cannot assemble units in status {presentation.get('status')!r}.")
    author_check = check_assignment(root, slug, "author-coordinator", presentation_id)
    if not author_check["ready"]:
        raise MPresError(
            f"Author coordinator assignment is incomplete: {author_check['placeholders'][:8]}"
        )
    task = task_path(root, slug)
    author_source = task / "workers" / "author-coordinator" / "drafts" / presentation_id / "source"
    integrated = author_source / "sections"
    fragments: list[str] = []
    header = author_source / "HEADER.md"
    if not header.is_file() or text_placeholders(header):
        raise MPresError("HEADER.md is missing or incomplete.")
    fragments.append(header.read_text(encoding="utf-8").strip())
    results: list[dict[str, Any]] = []
    geogebra_unit_records: list[dict[str, Any]] = []
    policy = read_yaml(task / "EXECUTION-POLICY.yaml") or {}
    geogebra_policy = (
        ((policy.get("online_resources") or {}).get("geogebra") or {})
        if isinstance(policy, dict)
        else {}
    )
    maximum_queries = int(geogebra_policy.get("max_search_queries_per_unit", 3) or 3)
    maximum_selected = int(geogebra_policy.get("max_selected_links_per_unit", 3) or 3)
    for unit in presentation.get("content_units", []):
        unit_id = unit["id"]
        assignment = check_assignment(root, slug, "lesson-author", presentation_id, unit_id=unit_id)
        if not assignment["ready"]:
            raise MPresError(
                f"Lesson-author assignment for {presentation_id}/{unit_id} is incomplete: "
                f"{assignment['placeholders'][:8]}"
            )
        source = task / "workers" / "lesson-authors" / presentation_id / unit_id / "source"
        for required in ("section.md", "UNIT-MANIFEST.yaml", "GEOGEBRA-RESOURCES.yaml", "SELF-CHECK.md"):
            path = source / required
            if not path.is_file():
                raise MPresError(f"Missing lesson-author handoff file: {path}")
            placeholders = text_placeholders(path)
            if placeholders:
                raise MPresError(f"{path} still contains placeholders: {placeholders[:8]}")
        geogebra_report = validate_unit_geogebra_registry(
            source / "GEOGEBRA-RESOURCES.yaml",
            source / "section.md",
            maximum_queries=maximum_queries,
            maximum_selected=maximum_selected,
        )
        if not geogebra_report.get("success"):
            raise MPresError(
                f"GeoGebra resource record for {presentation_id}/{unit_id} is invalid: "
                + "; ".join(geogebra_report.get("errors", [])[:6])
            )
        unit_record = read_yaml(source / "GEOGEBRA-RESOURCES.yaml")
        if not isinstance(unit_record, dict):
            raise MPresError(f"GeoGebra unit record must be a mapping: {source}")
        geogebra_unit_records.append(unit_record)
        destination = integrated / unit_id
        copy_source_tree(source, destination)
        fragments.append(_clean_fragment((destination / "section.md").read_text(encoding="utf-8"), destination / "section.md"))
        unit["status"] = "integrated"
        unit["integrated_utc"] = utc_now()
        results.append(
            {
                "unit_id": unit_id,
                "source": relative_display(source, root),
                "integrated": relative_display(destination, root),
            }
        )
    write_yaml_atomic(
        author_source / "GEOGEBRA-RESOURCES.yaml",
        aggregate_unit_geogebra_records(
            geogebra_unit_records,
            presentation_id=presentation_id,
        ),
    )
    canonical = "\n\n---\n\n".join(fragment for fragment in fragments if fragment.strip()) + "\n"
    (author_source / "presentation.md").write_text(canonical, encoding="utf-8", newline="\n")
    save_state(root, slug, state)
    append_log(
        root,
        slug,
        actor="author-coordinator",
        kind="handoff",
        presentation_id=presentation_id,
        message="Integrated all lesson/content-unit handoffs into canonical presentation.md.",
        data={"units": [item["unit_id"] for item in results]},
    )
    return {
        "presentation_id": presentation_id,
        "presentation_md": relative_display(author_source / "presentation.md", root),
        "units": results,
    }
