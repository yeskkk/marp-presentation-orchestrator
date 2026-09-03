from __future__ import annotations

import re
import shutil
from pathlib import Path
from typing import Any

from mpres.assignments import (
    apply_batch_contract,
    contract_paths,
    assignment_contract_status,
    batch_unit_instructions,
    initialize_batch_plan,
    scaffold_assignment_contract,
    ensure_assignment_taskbook,
)
from mpres.course_consistency import initialize_course_registries
from mpres.geogebra import aggregate_unit_geogebra_records, validate_unit_geogebra_registry
from mpres.interactions import (
    aggregate_unit_interactions,
    materialize_unit_interaction_views,
    validate_unit_interactions,
)
from mpres.logs import append_log
from mpres.milestones import record_milestone
from mpres.scheduling import current_allows_next_authoring, initialize_work_plan
from mpres.scaffolds import ScaffoldReport, ensure_copy, ensure_json, ensure_text, ensure_tree, ensure_yaml
from mpres.stages import all_stages_accepted, initialize_unit_stages, stage_state_path
from mpres.state import REVIEW_CHANNELS, get_content_unit, get_presentation, save_state
from mpres.tasks import require_gate
from mpres.time_planning import aggregate_lesson_time_plans, validate_lesson_time_plan
from mpres.tokens import require_collector_initialized
from mpres.toolchain import require_recent_smoke
from mpres.transactions import transactional_task_mutation
from mpres.util import (
    MPresError,
    copy_source_tree,
    make_tree_writable,
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
    "deck-revision-author",
    "specialist-reviewer",
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


def _list_text(values: list[Any] | None) -> str:
    rows = [str(value).strip() for value in (values or []) if str(value).strip()]
    return "\n".join(f"- {row}" for row in rows) if rows else "- none"


def _role_override(role: str) -> str:
    descriptions = {
        "author-coordinator": (
            "Coordinate one presentation, supervise only current-path lesson authors, assemble the "
            "canonical source, run author gates, freeze the full deck, then close after handoff."
        ),
        "lesson-author": (
            "Work only on one fixed lesson assignment, complete its selected stage profile, write a "
            "durable context-aware handoff, then close or release the thread."
        ),
        "deck-revision-author": (
            "Own the complete post-review revision from the frozen deck, five-channel findings, and "
            "AUTHOR-CONTEXT-PACKET; do not recall original lesson authors."
        ),
        "specialist-reviewer": (
            "Read the entire frozen deck in one specialist channel; do not edit source or inspect later revisions."
        ),
    }
    return (
        f"# {role} directory override\n\n"
        f"- {descriptions[role]}\n"
        "- Read the exact planner-approved assignment. It may have been deterministically expanded from a planner-approved batch plan.\n"
        "- The main agent alone writes or revises TASK.md; every other planner operation may be delegated to another planner.\n"
        "- Screenshots, PDF raster images, contact sheets, and model vision are forbidden.\n"
        "- Temporary Marp HTML is an author/release mechanical artifact and is deleted immediately.\n"
        "- Log only decisions, blockers, milestones, handoffs, and delivery; routine state transitions are written by Python.\n"
        "- Finish with a durable handoff, release or close the thread, and do not hold capacity speculatively.\n"
        "- A suspected workflow-engine bug must be recorded and converted into a TASK policy amendment; never hot-patch the engine inside the task.\n"
        "- Do not alter TASK.md or another role's files.\n"
    )


def _ensure_role_root(task: Path, directory_name: str, logical_role: str) -> Path:
    root = task / "workers" / directory_name
    root.mkdir(parents=True, exist_ok=True)
    ensure_text(root / "AGENTS.override.md", _role_override(logical_role))
    return root



def _templates(root: Path) -> dict[str, str]:
    mapping = {
        "author": "templates/assignments/TASK-author-coordinator.template.md",
        "lesson": "templates/assignments/TASK-lesson-author.template.md",
        "revision": "templates/assignments/TASK-deck-revision-author.template.md",
        "header": "templates/presentation-header.template.md",
        "section": "templates/section.template.md",
    }
    return {name: (root / path).read_text(encoding="utf-8") for name, path in mapping.items()}


def _content_unit_yaml(
    units: list[dict[str, Any]], *, task_kind: str
) -> str:
    rows: list[str] = []
    for unit in units:
        if task_kind == "course":
            rows.append(
                f'  - id: "{unit["id"]}"\n'
                f'    title: "{unit["title"]}"\n'
                f'    meeting_number: {unit["global_meeting_number"]}\n'
                f'    global_meeting_number: {unit["global_meeting_number"]}\n'
                f'    deck_local_ordinal: {unit["deck_local_ordinal"]}\n'
                f'    meeting_label: "{unit["meeting_label"]}"\n'
                f'    organization_basis: "course_meeting"\n'
                f'    source: "sections/{unit["id"]}/section.md"'
            )
        else:
            rows.append(
                f'  - id: "{unit["id"]}"\n'
                f'    title: "{unit["title"]}"\n'
                "    meeting_number: null\n"
                "    global_meeting_number: null\n"
                f'    deck_local_ordinal: {unit["deck_local_ordinal"]}\n'
                f'    meeting_label: "{unit["meeting_label"]}"\n'
                f'    organization_basis: "report_section"\n'
                f'    source: "sections/{unit["id"]}/section.md"'
            )
    return "\n".join(rows)


def _write_structured_templates(
    root: Path,
    source: Path,
    presentation_id: str,
    title: str,
    units: list[dict[str, Any]],
    *,
    task_kind: str,
    incoming_from: str | None,
) -> ScaffoldReport:
    """Fill only missing author-workspace templates.

    A recovery pass never resets a structured record that an author or planner
    has already edited. Existing files are preserved even when the repository
    template changed after the workspace was first created.
    """

    structured = {
        "DECK-MANIFEST.yaml": "DECK-MANIFEST.template.yaml",
        "PEDAGOGY-MAP.md": "PEDAGOGY-MAP.template.md",
        "EXAMPLE-MAP.md": "EXAMPLE-MAP.template.md",
        "TERMINOLOGY.md": "TERMINOLOGY.template.md",
        "TERMINOLOGY.yaml": "TERMINOLOGY-YAML.template.yaml",
        "SEMANTIC-OBJECTS.yaml": "SEMANTIC-OBJECTS.template.yaml",
        "PRESENTATION-CONTINUITY-MAP.yaml": "PRESENTATION-CONTINUITY-MAP.template.yaml",
        "SLIDE-DENSITY-AUDIT.yaml": "SLIDE-DENSITY-AUDIT.template.yaml",
        "ASSET-DECISIONS.yaml": "ASSET-DECISIONS.template.yaml",
        "GEOGEBRA-RESOURCES.yaml": "GEOGEBRA-RESOURCES.template.yaml",
        "LESSON-TIME-PLANS.yaml": "LESSON-TIME-PLANS.template.yaml",
        "AUTHOR-MODIFICATION-CHECKLIST.yaml": "AUTHOR-MODIFICATION-CHECKLIST.template.yaml",
        "AUTHOR-REVISION.md": "AUTHOR-REVISION.template.md",
        "SELF-CHECK.md": "SELF-CHECK.template.md",
        "RELEASE-RETROSPECTIVE.md": "RELEASE-RETROSPECTIVE.template.md",
    }
    unit_yaml = _content_unit_yaml(units, task_kind=task_kind)
    report = ScaffoldReport()
    for destination, template_name in structured.items():
        text = (root / "templates" / "structured" / template_name).read_text(encoding="utf-8")
        text = _replace(
            text,
            {
                "[[PRESENTATION_ID]]": presentation_id,
                "[[PRESENTATION_TITLE]]": title,
                "[[CONTENT_UNITS_YAML]]": unit_yaml,
                "[[SCOPE_ID]]": presentation_id,
                "[[TASK_KIND]]": task_kind,
                "[[INCOMING_FROM_OR_NULL]]": f'"{incoming_from}"' if incoming_from else "null",
            },
        )
        report.merge(ensure_text(source / destination, text))
    report.merge(
        ensure_yaml(
            source / "INTERACTION-RECORD.yaml",
            {
                "schema_version": 1,
                "presentation_id": presentation_id,
                "task_kind": task_kind,
                "canonical": True,
                "units": [],
            },
        )
    )
    report.merge(
        ensure_yaml(
            source / "INTERACTION-MANIFEST.yaml",
            {
                "schema_version": 1,
                "presentation_id": presentation_id,
                "task_kind": task_kind,
                "generated_from": "INTERACTION-RECORD.yaml",
                "units": [],
            },
        )
    )
    report.merge(
        ensure_yaml(
            source / "MCQ-AUDIT.yaml",
            {
                "schema_version": 1,
                "presentation_id": presentation_id,
                "task_kind": task_kind,
                "generated_from": "INTERACTION-RECORD.yaml",
                "quota": {
                    "course_minimum": 2,
                    "course_maximum": 3,
                    "academic_report_exempt": True,
                },
                "units": [],
            },
        )
    )
    return report



def _author_assignment(
    root: Path,
    task: Path,
    templates: dict[str, str],
    presentation: dict[str, Any],
) -> ScaffoldReport:
    presentation_id = str(presentation["id"])
    title = str(presentation["title"])
    units = presentation["content_units"]
    author_root = _ensure_role_root(task, "author-coordinator", "author-coordinator")
    lesson_root = task / "workers" / "lesson-authors" / presentation_id
    assignment = author_root / "assignments" / presentation_id / "TASK-AUTHOR-COORDINATOR.md"
    source = author_root / "drafts" / presentation_id / "source"
    build = author_root / "drafts" / presentation_id / "build"
    for directory in [
        assignment.parent,
        source / "sections",
        source / "assets",
        build,
        author_root / "checkpoints" / presentation_id,
    ]:
        directory.mkdir(parents=True, exist_ok=True)
    unit_table = "\n".join(
        (
            f"- {unit['meeting_label']}：`{unit['id']}` — {unit['title']}"
            if unit.get("meeting_label")
            else f"- `{unit['id']}` — {unit['title']}"
        )
        for unit in units
    )
    assignment_text = _replace(
        templates["author"],
        {
            "[[PRESENTATION_ID]]": presentation_id,
            "[[PRESENTATION_TITLE]]": title,
            "[[TASK_MD_PATH]]": relative_display(task / "TASK.md", root),
            "[[CONTENT_UNIT_TABLE]]": unit_table,
            "[[AUTHOR_SOURCE_PATH]]": relative_display(source, root),
            "[[AUTHOR_BUILD_PATH]]": relative_display(build, root),
            "[[LESSON_AUTHOR_ROOT]]": relative_display(lesson_root, root),
            "[[REVIEW_ROOT]]": relative_display(task / "reviews" / presentation_id, root),
        },
    )
    report = ScaffoldReport()
    assignment_result = ensure_assignment_taskbook(assignment, assignment_text)
    report.created.extend(assignment_result["created"])
    report.preserved.extend(assignment_result["preserved"])
    contract_result = scaffold_assignment_contract(
        root,
        assignment,
        assignment_id=f"{presentation_id}:author-coordinator",
        role="author-coordinator",
        presentation_id=presentation_id,
        requested_by="critical-path-scheduler",
        need="Coordinate the current deck, integrate lazy lesson handoffs, run gates, and freeze once.",
    )
    report.created.extend(contract_result["created"])
    report.preserved.extend(contract_result["preserved"])
    report.merge(
        ensure_text(
            source / "HEADER.md",
            _replace(
                templates["header"],
                {"[[PRESENTATION_ID]]": presentation_id, "[[PRESENTATION_TITLE]]": title},
            ),
        )
    )
    report.merge(ensure_copy(root / "themes" / "mathist-academic.css", source / "theme.css"))
    report.merge(
        ensure_text(
            source / "README.md",
            f"# Integrated Marp source — {presentation_id}: {title}\n\n"
            "Lesson workspaces are materialized only when queued on the critical path.\n",
        )
    )
    return report



def prepare_author_coordinator_workspace(
    root: Path,
    slug: str,
    presentation_id: str,
) -> dict[str, Any]:
    """Idempotently materialize or repair one active author workspace."""

    state = require_gate(root, slug)
    presentation = get_presentation(state, presentation_id)
    if presentation.get("status") != "authoring" or not presentation.get("active"):
        raise MPresError(
            "Author-coordinator workspaces may be materialized only for an active authoring presentation."
        )
    task = task_path(root, slug)
    assignment = assignment_path(root, slug, "author-coordinator", presentation_id)
    source = task / "workers" / "author-coordinator" / "drafts" / presentation_id / "source"
    required = [
        assignment,
        *contract_paths(assignment),
        source / "HEADER.md",
        source / "theme.css",
        source / "DECK-MANIFEST.yaml",
        source / "INTERACTION-RECORD.yaml",
    ]
    already_complete = all(path.is_file() for path in required)
    templates = _templates(root)
    report = _author_assignment(root, task, templates, presentation)
    rows = list(state.get("presentations", []))
    index = next(i for i, row in enumerate(rows) if row.get("id") == presentation_id)
    incoming_from = str(rows[index - 1].get("id")) if index > 0 else None
    report.merge(
        _write_structured_templates(
            root,
            source,
            presentation_id,
            str(presentation.get("title") or presentation_id),
            list(presentation.get("content_units", [])),
            task_kind=str(state.get("kind")),
            incoming_from=incoming_from,
        )
    )
    return {
        "presentation_id": presentation_id,
        "assignment": relative_display(assignment, root),
        "source": relative_display(source, root),
        "already_materialized": already_complete,
        "repaired_or_created": report.created,
        "preserved": report.preserved,
    }



def materialize_active_author_coordinators(
    root: Path,
    slug: str,
    *,
    state: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Materialize only the active authoring lanes selected by the critical-path scheduler."""

    state = state or load_state(root, slug)
    results: list[dict[str, Any]] = []
    for presentation in state.get("presentations", []):
        if presentation.get("active") and presentation.get("status") == "authoring":
            results.append(
                prepare_author_coordinator_workspace(root, slug, str(presentation.get("id")))
            )
    return results


@transactional_task_mutation
def initialize_production(
    root: Path,
    slug: str,
    presentation_specs: list[str],
    unit_specs: list[str],
) -> dict[str, Any]:
    state = require_gate(root, slug)
    from mpres.policy import policy_audit

    policy_report = policy_audit(root, slug)
    if not policy_report.get("ok"):
        raise MPresError(
            "Task policy is inconsistent and production cannot start: "
            + "; ".join(policy_report.get("errors", [])[:8])
        )
    require_recent_smoke(root)
    require_collector_initialized(root, slug)
    if state.get("presentations"):
        raise MPresError("Production units have already been initialized for this task.")
    if state.get("phase") != "confirmed":
        raise MPresError(f"Expected confirmed phase, got {state.get('phase')!r}.")

    presentations_spec = parse_presentation_specs(presentation_specs)
    units_by_presentation = parse_unit_specs(unit_specs, {item[0] for item in presentations_spec})
    task = task_path(root, slug)
    if state.get("kind") == "course":
        initialize_course_registries(root, task)

    state_presentations: list[dict[str, Any]] = []
    global_meeting = 0
    for presentation_index, (presentation_id, title) in enumerate(presentations_spec):
        unit_rows: list[dict[str, Any]] = []
        for deck_local_ordinal, (unit_id, unit_title) in enumerate(
            units_by_presentation[presentation_id], start=1
        ):
            if state.get("kind") == "course":
                global_meeting += 1
                meeting_label = f"第 {global_meeting} 节课"
                global_number: int | None = global_meeting
            else:
                meeting_label = f"报告部分 {deck_local_ordinal}"
                global_number = None
            unit_rows.append(
                {
                    "id": unit_id,
                    "title": unit_title,
                    "meeting_number": global_number,
                    "global_meeting_number": global_number,
                    "deck_local_ordinal": deck_local_ordinal,
                    "meeting_label": meeting_label,
                    "organization_basis": "course_meeting" if state.get("kind") == "course" else "report_section",
                    "status": "uninitialized",
                    "stage": None,
                    "stage_status": "uninitialized",
                    "queued_utc": None,
                    "integrated_utc": None,
                }
            )
        presentation = {
            "id": presentation_id,
            "title": title,
            "status": "authoring",
            "active": presentation_index == 0,
            "content_units": unit_rows,
            "active_round": None,
            "rounds": {},
            "finalized_utc": None,
            "delivery_sequence": None,
            "artifacts": {},
        }
        state_presentations.append(presentation)
        review_root = task / "reviews" / presentation_id
        review_root.mkdir(parents=True, exist_ok=True)
        write_json_atomic(
            review_root / "rounds.json",
            {"schema_version": 1, "presentation_id": presentation_id, "rounds": {}},
        )
        write_yaml_atomic(
            review_root / "findings.yaml",
            {"schema_version": 1, "presentation_id": presentation_id, "findings": []},
        )
        (task / "deliverables" / presentation_id).mkdir(parents=True, exist_ok=True)

    state["presentations"] = state_presentations
    state["phase"] = "working"
    state["production_initialized_utc"] = utc_now()
    state["critical_path_presentation"] = state_presentations[0]["id"]
    save_state(root, slug, state)
    initialize_batch_plan(
        root,
        slug,
        state_presentations,
        production_mode=str(state.get("production_mode") or "greenfield_full"),
    )
    initialize_work_plan(root, slug, state_presentations)
    materialize_active_author_coordinators(root, slug, state=state)
    record_milestone(
        root,
        slug,
        "production_initialized",
        data={"presentations": [item["id"] for item in state_presentations]},
    )
    append_log(
        root,
        slug,
        actor="critical-path-scheduler",
        kind="decision",
        message=(
            "Initialized profile-driven production. Only the first presentation is active; lesson "
            "workspaces remain uninitialized until a planner-approved batch plan is expanded on the critical path."
        ),
        data={
            "presentations": [item["id"] for item in state_presentations],
            "review_channels": list(REVIEW_CHANNELS),
            "production_mode": state.get("production_mode"),
        },
    )
    return state


def _unit_workspace_paths(task: Path, presentation_id: str, unit_id: str) -> tuple[Path, Path, Path]:
    unit_root = task / "workers" / "lesson-authors" / presentation_id / unit_id
    return unit_root, unit_root / "source", unit_root / "TASK-LESSON-AUTHOR.md"


@transactional_task_mutation
def prepare_unit_workspace(
    root: Path,
    slug: str,
    presentation_id: str,
    unit_id: str,
) -> dict[str, Any]:
    """Lazily and idempotently expand one lesson workspace."""

    state = require_gate(root, slug)
    presentation = get_presentation(state, presentation_id)
    unit = get_content_unit(presentation, unit_id)
    task = task_path(root, slug)
    unit_root, source, assignment = _unit_workspace_paths(task, presentation_id, unit_id)
    required = [
        assignment,
        *contract_paths(assignment),
        stage_state_path(root, slug, presentation_id, unit_id),
        source / "section.md",
        source / "UNIT-MANIFEST.yaml",
        source / "INTERACTION-RECORD.yaml",
        source / "UNIT-CONTEXT-PACKET.yaml",
    ]
    already_complete = all(path.is_file() for path in required)

    info = batch_unit_instructions(root, slug, presentation_id, unit_id)
    batch_unit = info["unit"]
    author_source = task / "workers" / "author-coordinator" / "drafts" / presentation_id / "source"
    for directory in [source / "assets", unit_root / "checkpoints"]:
        directory.mkdir(parents=True, exist_ok=True)
    templates = _templates(root)
    assignment_text = _replace(
        templates["lesson"],
        {
            "[[PRESENTATION_ID]]": presentation_id,
            "[[UNIT_ID]]": unit_id,
            "[[UNIT_TITLE]]": str(unit.get("title")),
            "[[PLANNER_ASSIGNMENT_BRIEF]]": (
                f"This assignment was expanded deterministically from `{info['plan_path']}` approved by "
                f"planner `{info['plan'].get('planner_actor')}`. The exact scope is limited to this lesson."
            ),
            "[[UNIT_SCOPE]]": str(batch_unit.get("unit_scope") or ""),
            "[[AUDIENCE_CONTEXT]]": str(batch_unit.get("audience_context") or ""),
            "[[PRIOR_KNOWLEDGE_TO_REACTIVATE]]": str(batch_unit.get("prior_knowledge_to_reactivate") or ""),
            "[[LOCAL_DECISION_RIGHTS]]": _list_text(batch_unit.get("local_decision_rights")),
            "[[STAGE_STATE_PATH]]": relative_display(stage_state_path(root, slug, presentation_id, unit_id), root),
            "[[TERMINOLOGY_PATH]]": relative_display(author_source / "TERMINOLOGY.md", root),
            "[[SEMANTIC_OBJECTS_PATH]]": relative_display(author_source / "SEMANTIC-OBJECTS.yaml", root),
            "[[DECK_MANIFEST_PATH]]": relative_display(author_source / "DECK-MANIFEST.yaml", root),
            "[[EXAMPLE_MAP_PATH]]": relative_display(author_source / "EXAMPLE-MAP.md", root),
            "[[INTERACTION_MANIFEST_PATH]]": relative_display(source / "INTERACTION-RECORD.yaml", root),
            "[[MCQ_AUDIT_PATH]]": relative_display(source / "INTERACTION-RECORD.yaml", root),
            "[[ASSET_DECISIONS_PATH]]": relative_display(author_source / "ASSET-DECISIONS.yaml", root),
            "[[GEOGEBRA_UNIT_RESOURCES_PATH]]": relative_display(source / "GEOGEBRA-RESOURCES.yaml", root),
            "[[LESSON_TIME_PLAN_PATH]]": relative_display(source / "LESSON-TIME-PLAN.yaml", root),
            "[[REFERENCES]]": _list_text(batch_unit.get("approved_text_sources")),
            "[[UNIT_SOURCE_PATH]]": relative_display(source, root),
            "[[UNIT_CHECKPOINT_PATH]]": relative_display(unit_root / "checkpoints" / "latest.json", root),
        },
    )
    assignment_text += (
        "\n\n## Planner-approved unit delta and risks\n\n"
        + _list_text(batch_unit.get("required_delta"))
        + "\n\n## Known risks\n\n"
        + _list_text(batch_unit.get("known_risks"))
        + "\n"
    )
    report = ScaffoldReport()
    assignment_result = ensure_assignment_taskbook(assignment, assignment_text)
    report.created.extend(assignment_result["created"])
    report.preserved.extend(assignment_result["preserved"])
    contract_result = apply_batch_contract(
        root,
        slug,
        assignment,
        assignment_id=f"{presentation_id}:{unit_id}:lesson-author",
        role="lesson-author",
        presentation_id=presentation_id,
        unit_id=unit_id,
    )
    report.created.extend(contract_result.get("created", []))
    report.preserved.extend(contract_result.get("preserved", []))
    initialize_unit_stages(
        root,
        slug,
        presentation_id,
        unit_id,
        unit_title=str(unit.get("title")),
        task_kind=str(state.get("kind")),
        production_mode=str(state.get("production_mode") or "greenfield_full"),
    )

    first_slide_id = f"{presentation_id}-{unit_id}-s01"
    title = (
        f"{unit['meeting_label']}：{unit['title']}"
        if state.get("kind") == "course"
        else f"报告部分 {unit['deck_local_ordinal']}：{unit['title']}"
    )
    section = _replace(
        templates["section"],
        {
            "[[SLIDE_ID]]": first_slide_id,
            "[[SLIDE_TITLE]]": title,
            "[[UNIT_LABEL]]": str(unit["meeting_label"]),
        },
    )
    report.merge(ensure_text(source / "section.md", section))
    report.merge(
        ensure_yaml(
            source / "UNIT-MANIFEST.yaml",
            {
                "schema_version": 2,
                "presentation_id": presentation_id,
                "unit_id": unit_id,
                "title": unit.get("title"),
                "meeting_number": unit.get("global_meeting_number"),
                "global_meeting_number": unit.get("global_meeting_number"),
                "deck_local_ordinal": unit.get("deck_local_ordinal"),
                "meeting_label": unit.get("meeting_label"),
                "organization_basis": unit.get("organization_basis"),
                "slide_ids": [first_slide_id],
                "canonical_records": {
                    "interaction": "INTERACTION-RECORD.yaml",
                    "delta": "UNIT-DELTA.yaml",
                    "time_plan": "LESSON-TIME-PLAN.yaml",
                },
                "semantic_objects": [],
                "examples": [],
                "assets": [],
            },
        )
    )
    report.merge(
        ensure_yaml(
            source / "INTERACTION-RECORD.yaml",
            {
                "schema_version": 1,
                "presentation_id": presentation_id,
                "unit_id": unit_id,
                "task_kind": state.get("kind"),
                "canonical": True,
                "interactions": [],
                "mcq_items": [],
            },
        )
    )
    geogebra_template = (
        root / "templates" / "structured" / "GEOGEBRA-UNIT-RESOURCES.template.yaml"
    ).read_text(encoding="utf-8")
    report.merge(
        ensure_text(
            source / "GEOGEBRA-RESOURCES.yaml",
            _replace(
                geogebra_template,
                {"[[PRESENTATION_ID]]": presentation_id, "[[UNIT_ID]]": unit_id},
            ),
        )
    )
    nominal = int(state.get("minutes") or 0) if state.get("kind") == "course" else 0
    prepared = int(round(nominal * 1.5)) if nominal else 0
    report.merge(
        ensure_yaml(
            source / "LESSON-TIME-PLAN.yaml",
            {
                "schema_version": 2,
                "task_kind": state.get("kind"),
                "presentation_id": presentation_id,
                "unit_id": unit_id,
                "meeting_number": unit.get("global_meeting_number"),
                "global_meeting_number": unit.get("global_meeting_number"),
                "deck_local_ordinal": unit.get("deck_local_ordinal"),
                "meeting_label": unit.get("meeting_label"),
                "organization_basis": unit.get("organization_basis"),
                "nominal_class_minutes": nominal if nominal else None,
                "prepared_material_target_minutes": prepared if prepared else None,
                "core_path_target_minutes": nominal if nominal else None,
                "extension_example_target_minutes": max(0, prepared - nominal) if nominal else None,
                "policy": "advisory_not_hard_gate",
                "stop_at_class_end": True,
                "core_path": {
                    "purpose": "Complete the required lesson concept chain and diagnostics.",
                    "planned_end_slide_id": "[[CORE_END_SLIDE_ID]]",
                },
                "extension_example_bank": {
                    "purpose": "Optional worked examples after the natural stopping point.",
                    "items": [],
                },
                "variation_rationale": "[[TIME_VARIATION_RATIONALE]]",
            },
        )
    )
    report.merge(
        ensure_yaml(
            source / "UNIT-DELTA.yaml",
            {
                "schema_version": 1,
                "presentation_id": presentation_id,
                "unit_id": unit_id,
                "production_mode": state.get("production_mode"),
                "baseline": {
                    "source": batch_unit.get("baseline_source"),
                    "maturity": batch_unit.get("baseline_maturity"),
                    "legacy_source_ranges": batch_unit.get("legacy_source_ranges") or [],
                },
                "slide_ranges": [],
                "required_changes": batch_unit.get("required_delta") or [],
                "continuity_risks": batch_unit.get("known_risks") or [],
                "unchanged_content_sampling": {"method": "pending", "result": "pending"},
            },
        )
    )
    report.merge(
        ensure_yaml(
            source / "UNIT-CONTEXT-PACKET.yaml",
            {
                "schema_version": 1,
                "presentation_id": presentation_id,
                "unit_id": unit_id,
                "production_mode": state.get("production_mode"),
                "assignment_source": info["plan_path"],
                "approved_text_sources": batch_unit.get("approved_text_sources") or [],
                "legacy_source_ranges": batch_unit.get("legacy_source_ranges") or [],
                "course_registry_paths": [
                    relative_display(author_source / "TERMINOLOGY.yaml", root),
                    relative_display(author_source / "SEMANTIC-OBJECTS.yaml", root),
                ],
                "unit_delta_path": relative_display(source / "UNIT-DELTA.yaml", root),
                "required_invariants": info["presentation"].get("common_constraints") or [],
                "known_risks": batch_unit.get("known_risks") or [],
                "forbidden_context": [
                    "original_pdfs",
                    "screenshots",
                    "other_units_unless_explicitly_listed",
                ],
            },
        )
    )
    self_check = (
        root / "templates" / "structured" / "SELF-CHECK.template.md"
    ).read_text(encoding="utf-8")
    report.merge(
        ensure_text(
            source / "SELF-CHECK.md",
            self_check.replace("[[SCOPE_ID]]", f"{presentation_id}/{unit_id}"),
        )
    )
    checkpoint = {
        "schema_version": 1,
        "utc": utc_now(),
        "role": "lesson-author",
        "presentation_id": presentation_id,
        "unit_id": unit_id,
        "status": "assignment_ready",
        "next_action": "queue_and_start_same_fixed_lesson_author",
    }
    report.merge(ensure_json(unit_root / "checkpoints" / "latest.json", checkpoint))
    if not unit.get("workspace_materialized_utc"):
        unit.update(
            {
                "status": "assignment_ready",
                "stage": None,
                "stage_status": "awaiting_start",
                "workspace_materialized_utc": utc_now(),
            }
        )
        save_state(root, slug, state)
    return {
        "presentation_id": presentation_id,
        "unit_id": unit_id,
        "status": unit.get("status"),
        "workspace": relative_display(unit_root, root),
        "assignment": relative_display(assignment, root),
        "already_materialized": already_complete,
        "repaired_or_created": report.created,
        "preserved": report.preserved,
    }



def prepare_revision_author_workspace(
    root: Path,
    slug: str,
    presentation_id: str,
    *,
    frozen_source: Path,
    finding_registry: Path,
    review_plan: Path,
) -> tuple[Path, Path]:
    state = require_gate(root, slug)
    presentation = get_presentation(state, presentation_id)
    task = task_path(root, slug)
    role_root = _ensure_role_root(task, "deck-revision-author", "deck-revision-author")
    assignment = role_root / "assignments" / presentation_id / "TASK-DECK-REVISION-AUTHOR.md"
    source = role_root / "drafts" / presentation_id / "source"
    build = role_root / "drafts" / presentation_id / "build"
    for directory in [assignment.parent, source, build, role_root / "checkpoints" / presentation_id]:
        directory.mkdir(parents=True, exist_ok=True)
    # Copy only files missing from an interrupted scaffold. Existing revision
    # edits are never deleted or replaced.
    ensure_tree(frozen_source, source)
    make_tree_writable(source)
    from mpres.context_packets import enrich_revision_context_packet

    context = source / "AUTHOR-CONTEXT-PACKET.yaml"
    enrich_revision_context_packet(
        root,
        slug,
        presentation_id,
        source_root=source,
        frozen_source=frozen_source,
        finding_registry=finding_registry,
        review_plan=review_plan,
    )
    assignment_text = _replace(
        _templates(root)["revision"],
        {
            "[[PRESENTATION_ID]]": presentation_id,
            "[[PRESENTATION_TITLE]]": str(presentation.get("title")),
            "[[PLANNER_ASSIGNMENT_BRIEF]]": "[[PLANNER_ASSIGNMENT_BRIEF]]",
            "[[REVISION_SOURCE_PATH]]": relative_display(source, root),
            "[[AUTHOR_CONTEXT_PACKET_PATH]]": relative_display(context, root),
            "[[FINDINGS_REGISTRY_PATH]]": relative_display(finding_registry, root),
            "[[REVIEW_PLAN_PATH]]": relative_display(review_plan, root),
        },
    )
    ensure_assignment_taskbook(assignment, assignment_text)
    scaffold_assignment_contract(
        root,
        assignment,
        assignment_id=f"{presentation_id}:deck-revision-author",
        role="deck-revision-author",
        presentation_id=presentation_id,
        requested_by="review-aggregation-job",
        need="Revise the complete deck from five-channel findings using the durable author context packet.",
    )
    return assignment, source



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
    if role == "deck-revision-author":
        return task / "workers" / role / "assignments" / presentation_id / "TASK-DECK-REVISION-AUTHOR.md"
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
    minimum = 600
    contract = assignment_contract_status(path)
    return {
        "ready": not placeholders and len(text.strip()) >= minimum and contract.get("approved") is True,
        "path": relative_display(path, root),
        "placeholders": placeholders,
        "characters": len(text),
        "contract": contract,
    }


@transactional_task_mutation
def activate_presentations(root: Path, slug: str, presentation_ids: list[str]) -> dict[str, Any]:
    """Activate only the ordered current/next authoring window.

    This command never creates speculative workers. It merely opens the permitted presentation
    lanes; unit workspaces remain lazy until ``queue_unit`` expands an approved batch assignment.
    """

    state = require_gate(root, slug)
    if state.get("phase") != "working":
        raise MPresError(f"Cannot activate presentations in phase {state.get('phase')!r}.")
    remaining = [item for item in state.get("presentations", []) if item.get("status") != "finalized"]
    if not remaining:
        raise MPresError("No unfinished presentation remains.")

    current = remaining[0]
    allowed: list[str] = [str(current.get("id"))]
    from mpres.scheduling import _activation_limits, sync_work_plan

    _current_limit, next_limit = _activation_limits(root, slug, state=state)
    if current_allows_next_authoring(current.get("status")):
        for item in remaining[1:]:
            if next_limit <= 0:
                break
            if item.get("status") == "authoring":
                allowed.append(str(item.get("id")))
                next_limit -= 1

    requested = [str(value) for value in presentation_ids]
    outside = sorted(set(requested) - set(allowed))
    if outside:
        raise MPresError(
            "Critical-path activation is limited to the current presentation and the earliest "
            "permitted next authoring presentation while the current deck is in authoring, "
            "review, revision, or release: " + ", ".join(outside)
        )

    # The current lane is invariant. Explicit activation may add the permitted next lane but may
    # never leave a future or stale presentation active.
    desired = {str(current.get("id")), *requested}
    previous = {
        str(item.get("id"))
        for item in state.get("presentations", [])
        if item.get("active") and item.get("status") != "finalized"
    }
    for presentation in state.get("presentations", []):
        presentation["active"] = (
            presentation.get("status") != "finalized"
            and str(presentation.get("id")) in desired
        )
    state["critical_path_presentation"] = str(current.get("id"))
    save_state(root, slug, state)
    materialize_active_author_coordinators(root, slug, state=state)
    sync_work_plan(root, slug, state=state)
    activated = sorted(desired - previous)
    deactivated = sorted(previous - desired)
    append_log(
        root,
        slug,
        actor="critical-path-scheduler",
        kind="decision",
        message="Activated presentation lanes within the ordered current-plus-next WIP limit.",
        data={"active_presentations": sorted(desired), "activated": activated, "deactivated": deactivated},
    )
    return {
        "active_presentations": sorted(desired),
        "activated": activated,
        "deactivated": deactivated,
        "phase": state.get("phase"),
    }


def _clean_fragment(text: str, path: Path) -> str:
    stripped = text.strip()
    if stripped.startswith("---"):
        raise MPresError(f"Lesson fragment must not contain YAML frontmatter: {path}")
    return stripped.strip("\n")


@transactional_task_mutation
def assemble_units(root: Path, slug: str, presentation_id: str) -> dict[str, Any]:
    state = require_gate(root, slug)
    presentation = get_presentation(state, presentation_id)
    if presentation.get("status") != "authoring":
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
    interaction_unit_records: list[dict[str, Any]] = []
    mcq_unit_records: list[dict[str, Any]] = []
    lesson_time_plans: list[dict[str, Any]] = []
    policy = read_yaml(task / "EXECUTION-POLICY.yaml") or {}
    geogebra_policy = ((policy.get("online_resources") or {}).get("geogebra") or {}) if isinstance(policy, dict) else {}
    maximum_queries = int(geogebra_policy.get("max_search_queries_per_unit", 3) or 3)
    maximum_selected = int(geogebra_policy.get("max_selected_links_per_unit", 3) or 3)
    for unit in presentation.get("content_units", []):
        unit_id = str(unit["id"])
        assignment = check_assignment(root, slug, "lesson-author", presentation_id, unit_id=unit_id)
        if not assignment["ready"]:
            raise MPresError(f"Lesson-author assignment for {presentation_id}/{unit_id} is incomplete.")
        if not all_stages_accepted(root, slug, presentation_id, unit_id):
            raise MPresError(f"Lesson/content unit {presentation_id}/{unit_id} has incomplete stages.")
        source = task / "workers" / "lesson-authors" / presentation_id / unit_id / "source"
        materialize_unit_interaction_views(source)
        for required in (
            "section.md",
            "UNIT-MANIFEST.yaml",
            "INTERACTION-RECORD.yaml",
            "INTERACTION-MANIFEST.yaml",
            "MCQ-AUDIT.yaml",
            "GEOGEBRA-RESOURCES.yaml",
            "LESSON-TIME-PLAN.yaml",
            "UNIT-DELTA.yaml",
            "UNIT-CONTEXT-PACKET.yaml",
            "SELF-CHECK.md",
        ):
            path = source / required
            if not path.is_file():
                raise MPresError(f"Missing lesson-author handoff file: {path}")
            placeholders = text_placeholders(path)
            if placeholders:
                raise MPresError(f"{path} still contains placeholders: {placeholders[:8]}")
        time_report = validate_lesson_time_plan(
            source / "LESSON-TIME-PLAN.yaml",
            task_kind=str(state.get("kind")),
            expected_meeting_number=unit.get("global_meeting_number"),
            expected_deck_local_ordinal=int(unit.get("deck_local_ordinal") or 0),
            nominal_minutes=int(state.get("minutes") or 0) if state.get("kind") == "course" else None,
        )
        if not time_report.get("success"):
            raise MPresError(
                f"Lesson time plan for {presentation_id}/{unit_id} is invalid: "
                + "; ".join(time_report.get("errors", [])[:8])
            )
        time_value = read_yaml(source / "LESSON-TIME-PLAN.yaml")
        assert isinstance(time_value, dict)
        lesson_time_plans.append(time_value)
        interaction_report = validate_unit_interactions(
            source / "INTERACTION-MANIFEST.yaml",
            source / "MCQ-AUDIT.yaml",
            task_kind=str(state.get("kind")),
        )
        if not interaction_report.get("success"):
            raise MPresError(
                f"Interaction record for {presentation_id}/{unit_id} is invalid: "
                + "; ".join(interaction_report.get("errors", [])[:8])
            )
        geogebra_report = validate_unit_geogebra_registry(
            source / "GEOGEBRA-RESOURCES.yaml",
            source / "section.md",
            maximum_queries=maximum_queries,
            maximum_selected=maximum_selected,
        )
        if not geogebra_report.get("success"):
            raise MPresError(
                f"GeoGebra record for {presentation_id}/{unit_id} is invalid: "
                + "; ".join(geogebra_report.get("errors", [])[:6])
            )
        geogebra_value = read_yaml(source / "GEOGEBRA-RESOURCES.yaml")
        interaction_value = read_yaml(source / "INTERACTION-MANIFEST.yaml")
        mcq_value = read_yaml(source / "MCQ-AUDIT.yaml")
        if not all(isinstance(value, dict) for value in (geogebra_value, interaction_value, mcq_value)):
            raise MPresError(f"Unit structured records must be mappings: {source}")
        geogebra_unit_records.append(geogebra_value)
        interaction_unit_records.append(interaction_value)
        mcq_unit_records.append(mcq_value)
        destination = integrated / unit_id
        copy_source_tree(source, destination)
        fragments.append(_clean_fragment((destination / "section.md").read_text(encoding="utf-8"), destination / "section.md"))
        unit["status"] = "integrated"
        unit["integrated_utc"] = utc_now()
        results.append({"unit_id": unit_id, "source": relative_display(source, root), "integrated": relative_display(destination, root)})
    write_yaml_atomic(
        author_source / "GEOGEBRA-RESOURCES.yaml",
        aggregate_unit_geogebra_records(geogebra_unit_records, presentation_id=presentation_id),
    )
    aggregate_interactions, aggregate_mcq = aggregate_unit_interactions(
        interaction_unit_records,
        mcq_unit_records,
        presentation_id=presentation_id,
        task_kind=str(state.get("kind")),
    )
    write_yaml_atomic(
        author_source / "INTERACTION-RECORD.yaml",
        {
            "schema_version": 1,
            "presentation_id": presentation_id,
            "task_kind": state.get("kind"),
            "canonical": True,
            "units": [
                {
                    "unit_id": row.get("unit_id"),
                    "interactions": row.get("interactions") or [],
                    "mcq_items": mcq.get("items") or [],
                }
                for row, mcq in zip(interaction_unit_records, mcq_unit_records, strict=True)
            ],
        },
    )
    write_yaml_atomic(author_source / "INTERACTION-MANIFEST.yaml", {**aggregate_interactions, "generated_from": "INTERACTION-RECORD.yaml"})
    write_yaml_atomic(author_source / "MCQ-AUDIT.yaml", {**aggregate_mcq, "generated_from": "INTERACTION-RECORD.yaml"})
    write_yaml_atomic(
        author_source / "LESSON-TIME-PLANS.yaml",
        aggregate_lesson_time_plans(lesson_time_plans, presentation_id=presentation_id, task_kind=str(state.get("kind"))),
    )
    from mpres.context_packets import compile_author_context_packet

    compile_author_context_packet(
        root,
        slug,
        presentation_id,
        source_root=author_source,
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
        message="Integrated all current-path lesson handoffs into canonical presentation.md.",
        data={"units": [item["unit_id"] for item in results]},
    )
    return {"presentation_id": presentation_id, "presentation_md": relative_display(author_source / "presentation.md", root), "units": results}
