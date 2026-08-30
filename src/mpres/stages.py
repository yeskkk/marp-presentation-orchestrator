from __future__ import annotations

from pathlib import Path
from typing import Any

from mpres.assignments import assignment_contract_status, revoke_assignment, scaffold_assignment_contract
from mpres.logs import append_log
from mpres.state import get_content_unit, get_presentation, load_state, save_state, stage_ids_for_kind
from mpres.tasks import require_gate
from mpres.util import MPresError, read_yaml, relative_display, task_path, text_placeholders, utc_now, write_yaml_atomic

STAGE_ARTIFACT_TEMPLATES = {
    "01_scope_sources": "STAGE-01-SCOPE-SOURCES.template.md",
    "02_learner_need": "STAGE-02-LEARNER-NEED.template.md",
    "03_domain_development": "STAGE-03-DOMAIN-DEVELOPMENT.template.md",
    "04_entry_diagnostics": "STAGE-04-ENTRY-DIAGNOSTICS.template.md",
    "05_learner_language": "STAGE-05-LEARNER-LANGUAGE.template.md",
    "06_marp_integration": "STAGE-06-MARP-INTEGRATION.template.md",
    "02_audience_domain": "STAGE-REPORT-02-AUDIENCE-DOMAIN.template.md",
    "03_narrative_language": "STAGE-REPORT-03-NARRATIVE-LANGUAGE.template.md",
    "04_marp_integration": "STAGE-REPORT-04-MARP-INTEGRATION.template.md",
}
STAGE_ASSIGNMENT_TEMPLATES = {
    "01_scope_sources": "STAGE-01-scope-sources.template.md",
    "02_learner_need": "STAGE-02-learner-need.template.md",
    "03_domain_development": "STAGE-03-domain-development.template.md",
    "04_entry_diagnostics": "STAGE-04-entry-diagnostics.template.md",
    "05_learner_language": "STAGE-05-learner-language.template.md",
    "06_marp_integration": "STAGE-06-marp-integration.template.md",
    "02_audience_domain": "STAGE-REPORT-02-audience-domain.template.md",
    "03_narrative_language": "STAGE-REPORT-03-narrative-language.template.md",
    "04_marp_integration": "STAGE-REPORT-04-marp-integration.template.md",
}
STAGE_MINIMUM_CHARACTERS = {
    "01_scope_sources": 700,
    "02_learner_need": 700,
    "03_domain_development": 1000,
    "04_entry_diagnostics": 900,
    "05_learner_language": 900,
    "06_marp_integration": 500,
    "02_audience_domain": 1000,
    "03_narrative_language": 900,
    "04_marp_integration": 500,
}


def unit_root(root: Path, slug: str, presentation_id: str, unit_id: str) -> Path:
    return task_path(root, slug) / "workers" / "lesson-authors" / presentation_id / unit_id


def stage_root(root: Path, slug: str, presentation_id: str, unit_id: str, stage_id: str) -> Path:
    return unit_root(root, slug, presentation_id, unit_id) / "stages" / stage_id


def stage_state_path(root: Path, slug: str, presentation_id: str, unit_id: str) -> Path:
    return unit_root(root, slug, presentation_id, unit_id) / "stages" / "STAGE-STATE.yaml"


def stage_assignment_path(root: Path, slug: str, presentation_id: str, unit_id: str, stage_id: str) -> Path:
    return stage_root(root, slug, presentation_id, unit_id, stage_id) / "STAGE-ASSIGNMENT.md"


def stage_artifact_path(root: Path, slug: str, presentation_id: str, unit_id: str, stage_id: str) -> Path:
    return stage_root(root, slug, presentation_id, unit_id, stage_id) / "STAGE-ARTIFACT.md"


def initialize_unit_stages(
    root: Path,
    slug: str,
    presentation_id: str,
    unit_id: str,
    *,
    unit_title: str,
    task_kind: str,
) -> None:
    stage_order = list(stage_ids_for_kind(task_kind))
    values = {
        "[[PRESENTATION_ID]]": presentation_id,
        "[[UNIT_ID]]": unit_id,
        "[[UNIT_TITLE]]": unit_title,
    }
    stages: dict[str, Any] = {}
    for index, stage_id in enumerate(stage_order):
        directory = stage_root(root, slug, presentation_id, unit_id, stage_id)
        directory.mkdir(parents=True, exist_ok=True)
        assignment = (
            root / "templates" / "assignments" / "stages" / STAGE_ASSIGNMENT_TEMPLATES[stage_id]
        ).read_text(encoding="utf-8")
        artifact = (
            root / "templates" / "stages" / STAGE_ARTIFACT_TEMPLATES[stage_id]
        ).read_text(encoding="utf-8")
        for old, new in values.items():
            assignment = assignment.replace(old, new)
            artifact = artifact.replace(old, new)
        assignment_path = directory / "STAGE-ASSIGNMENT.md"
        artifact_path = directory / "STAGE-ARTIFACT.md"
        assignment_path.write_text(assignment, encoding="utf-8", newline="\n")
        artifact_path.write_text(artifact, encoding="utf-8", newline="\n")
        scaffold_assignment_contract(
            root,
            assignment_path,
            assignment_id=f"{presentation_id}:{unit_id}:{stage_id}",
            role="lesson-author-stage",
            presentation_id=presentation_id,
            unit_id=unit_id,
            requested_by="author-coordinator",
            need=(
                f"Planner must personally write the exact {stage_id} brief for "
                f"{presentation_id}/{unit_id}; the coordinator may not write or rewrite it."
            ),
        )
        stages[stage_id] = {
            "status": "awaiting_assignment" if index == 0 else "planned",
            "assignment": relative_display(assignment_path, root),
            "artifact": relative_display(artifact_path, root),
            "task_kind": task_kind,
        }
    write_yaml_atomic(
        stage_state_path(root, slug, presentation_id, unit_id),
        {
            "schema_version": 3,
            "presentation_id": presentation_id,
            "unit_id": unit_id,
            "unit_title": unit_title,
            "task_kind": task_kind,
            "stage_order": stage_order,
            "current_stage": stage_order[0],
            "stages": stages,
        },
    )


def initialize_stage_files(root: Path, slug: str, presentation_id: str, unit_id: str, unit_title: str) -> None:
    task_state = load_state(root, slug)
    initialize_unit_stages(
        root,
        slug,
        presentation_id,
        unit_id,
        unit_title=unit_title,
        task_kind=str(task_state.get("kind") or "course"),
    )


def _load_stage_state(root: Path, slug: str, presentation_id: str, unit_id: str) -> dict[str, Any]:
    path = stage_state_path(root, slug, presentation_id, unit_id)
    value = read_yaml(path)
    if (
        not isinstance(value, dict)
        or not isinstance(value.get("stages"), dict)
        or not isinstance(value.get("stage_order"), list)
        or not value.get("stage_order")
    ):
        raise MPresError(f"Invalid lesson stage state: {path}")
    return value


def _stage_order(value: dict[str, Any]) -> list[str]:
    order = [str(item) for item in value.get("stage_order", [])]
    if not order or any(item not in value.get("stages", {}) for item in order):
        raise MPresError("Stage state contains an invalid stage order.")
    return order


def stage_status(root: Path, slug: str, presentation_id: str, unit_id: str) -> dict[str, Any]:
    require_gate(root, slug)
    value = _load_stage_state(root, slug, presentation_id, unit_id)
    for stage_id, entry in value["stages"].items():
        if isinstance(entry, dict):
            assignment = stage_assignment_path(root, slug, presentation_id, unit_id, stage_id)
            entry["assignment_contract"] = assignment_contract_status(assignment)
    return {
        **value,
        "path": relative_display(stage_state_path(root, slug, presentation_id, unit_id), root),
    }


def activate_stage(root: Path, slug: str, presentation_id: str, unit_id: str, stage_id: str) -> dict[str, Any]:
    require_gate(root, slug)
    task_state = load_state(root, slug)
    presentation = get_presentation(task_state, presentation_id)
    unit = get_content_unit(presentation, unit_id)
    if presentation.get("status") not in {"authoring", "author_revision"}:
        raise MPresError(f"Cannot activate lesson stages in {presentation.get('status')!r} status.")
    value = _load_stage_state(root, slug, presentation_id, unit_id)
    order = _stage_order(value)
    if stage_id not in order:
        raise MPresError(f"Unknown authoring stage for this task profile: {stage_id}")
    if value.get("current_stage") != stage_id:
        raise MPresError(f"Current stage is {value.get('current_stage')!r}, not {stage_id!r}.")
    entry = value["stages"].get(stage_id)
    if not isinstance(entry, dict) or entry.get("status") not in {"awaiting_assignment", "planned"}:
        raise MPresError(f"Stage {stage_id} is not awaiting planner activation.")
    assignment = stage_assignment_path(root, slug, presentation_id, unit_id, stage_id)
    contract = assignment_contract_status(assignment)
    placeholders = text_placeholders(assignment) if assignment.is_file() else ["missing"]
    if not contract.get("approved") or placeholders:
        raise MPresError(
            "The planner must personally complete and approve the exact stage assignment before activation."
        )
    if len(assignment.read_text(encoding="utf-8").strip()) < 700:
        raise MPresError("Stage assignment is too short to be an exact planner-written brief.")
    entry["status"] = "active"
    entry["activated_utc"] = utc_now()
    unit.update({"status": "stage_active", "stage": stage_id, "stage_status": "active"})
    save_state(root, slug, task_state)
    write_yaml_atomic(stage_state_path(root, slug, presentation_id, unit_id), value)
    append_log(
        root,
        slug,
        actor="planner",
        kind="decision",
        presentation_id=presentation_id,
        unit_id=unit_id,
        message=f"Activated planner-written lesson-author stage {stage_id}.",
        data={"assignment": relative_display(assignment, root)},
    )
    return stage_status(root, slug, presentation_id, unit_id)


def submit_stage(root: Path, slug: str, presentation_id: str, unit_id: str, stage_id: str) -> dict[str, Any]:
    require_gate(root, slug)
    lesson_assignment = unit_root(root, slug, presentation_id, unit_id) / "TASK-LESSON-AUTHOR.md"
    lesson_contract = assignment_contract_status(lesson_assignment)
    if (
        not lesson_assignment.is_file()
        or text_placeholders(lesson_assignment)
        or len(lesson_assignment.read_text(encoding="utf-8").strip()) < 600
        or not lesson_contract.get("approved")
    ):
        raise MPresError("The planner-written lesson assignment is incomplete or unapproved.")
    task_state = load_state(root, slug)
    presentation = get_presentation(task_state, presentation_id)
    unit = get_content_unit(presentation, unit_id)
    if presentation.get("status") not in {"authoring", "author_revision"}:
        raise MPresError(f"Lesson stages cannot advance in {presentation.get('status')!r} status.")
    value = _load_stage_state(root, slug, presentation_id, unit_id)
    order = _stage_order(value)
    if stage_id not in order:
        raise MPresError(f"Unknown authoring stage for this task profile: {stage_id}")
    if value.get("current_stage") != stage_id:
        raise MPresError(f"Current stage is {value.get('current_stage')!r}, not {stage_id!r}.")
    entry = value["stages"].get(stage_id)
    if not isinstance(entry, dict) or entry.get("status") != "active":
        raise MPresError(f"Stage {stage_id} is not active.")
    artifact = stage_artifact_path(root, slug, presentation_id, unit_id, stage_id)
    if not artifact.is_file():
        raise MPresError(f"Stage artifact is missing: {artifact}")
    placeholders = text_placeholders(artifact)
    if placeholders:
        raise MPresError(f"Stage artifact still contains placeholders: {', '.join(placeholders[:8])}")
    text = artifact.read_text(encoding="utf-8")
    minimum = STAGE_MINIMUM_CHARACTERS[stage_id]
    if len(text.strip()) < minimum:
        raise MPresError(f"Stage artifact is too short ({len(text.strip())} < {minimum}).")
    if stage_id == "01_scope_sources":
        lowered = text.lower()
        forbidden = (".pdf", "downloads/originals", "restricted-originals")
        if any(item in lowered for item in forbidden):
            raise MPresError("Stage 01 may cite only extracted text; original PDF access is forbidden.")
        if (
            "downloads/text/" not in lowered
            and "no external reference" not in lowered
            and "不使用外部资料" not in text
        ):
            raise MPresError(
                "Stage 01 must cite downloads/text/ or explicitly state that no external reference is used."
            )
    entry["status"] = "submitted"
    entry["submitted_utc"] = utc_now()
    unit.update({"status": "stage_submitted", "stage_status": "submitted"})
    save_state(root, slug, task_state)
    write_yaml_atomic(stage_state_path(root, slug, presentation_id, unit_id), value)
    append_log(
        root,
        slug,
        actor=f"lesson-author:{unit_id}",
        kind="handoff",
        presentation_id=presentation_id,
        unit_id=unit_id,
        message=f"Submitted authoring stage {stage_id} for coordinator acceptance.",
        data={"artifact": relative_display(artifact, root)},
    )
    return stage_status(root, slug, presentation_id, unit_id)


def accept_stage(root: Path, slug: str, presentation_id: str, unit_id: str, stage_id: str) -> dict[str, Any]:
    require_gate(root, slug)
    task_state = load_state(root, slug)
    presentation = get_presentation(task_state, presentation_id)
    unit = get_content_unit(presentation, unit_id)
    value = _load_stage_state(root, slug, presentation_id, unit_id)
    order = _stage_order(value)
    if stage_id not in order:
        raise MPresError(f"Unknown authoring stage for this task profile: {stage_id}")
    if value.get("current_stage") != stage_id:
        raise MPresError(f"Current stage is {value.get('current_stage')!r}, not {stage_id!r}.")
    entry = value["stages"].get(stage_id)
    if not isinstance(entry, dict) or entry.get("status") != "submitted":
        raise MPresError(f"Stage {stage_id} must be submitted before acceptance.")
    entry["status"] = "accepted"
    entry["accepted_utc"] = utc_now()
    index = order.index(stage_id)
    if index + 1 < len(order):
        next_stage = order[index + 1]
        value["current_stage"] = next_stage
        value["stages"][next_stage]["status"] = "awaiting_assignment"
        unit.update(
            {
                "status": "awaiting_stage_assignment",
                "stage": next_stage,
                "stage_status": "awaiting_assignment",
            }
        )
        next_action = f"planner_write_and_activate:{next_stage}"
    else:
        value["current_stage"] = None
        value["completed_utc"] = utc_now()
        unit.update({"status": "handoff_ready", "stage": None, "stage_status": "accepted"})
        next_action = "handoff_ready"
    save_state(root, slug, task_state)
    write_yaml_atomic(stage_state_path(root, slug, presentation_id, unit_id), value)
    append_log(
        root,
        slug,
        actor="author-coordinator",
        kind="decision",
        presentation_id=presentation_id,
        unit_id=unit_id,
        message=(
            f"Accepted stage {stage_id}; next action is {next_action}. The coordinator cannot "
            "write or approve the next planner-owned assignment."
        ),
    )
    return stage_status(root, slug, presentation_id, unit_id)


def reopen_stage(
    root: Path,
    slug: str,
    presentation_id: str,
    unit_id: str,
    stage_id: str,
    *,
    reason: str,
) -> dict[str, Any]:
    require_gate(root, slug)
    if not reason.strip():
        raise MPresError("A non-empty reopen reason is required.")
    task_state = load_state(root, slug)
    presentation = get_presentation(task_state, presentation_id)
    unit = get_content_unit(presentation, unit_id)
    value = _load_stage_state(root, slug, presentation_id, unit_id)
    order = _stage_order(value)
    if stage_id not in order:
        raise MPresError(f"Unknown authoring stage for this task profile: {stage_id}")
    target_index = order.index(stage_id)
    for index, candidate in enumerate(order):
        entry = value["stages"][candidate]
        if index < target_index:
            entry["status"] = "accepted"
            continue
        entry["status"] = "awaiting_assignment" if index == target_index else "planned"
        for key in ("submitted_utc", "accepted_utc", "activated_utc"):
            entry.pop(key, None)
        assignment = stage_assignment_path(root, slug, presentation_id, unit_id, candidate)
        contract = assignment_contract_status(assignment)
        if contract.get("approved"):
            revoke_assignment(root, slug, assignment, reason=reason.strip())
    value["current_stage"] = stage_id
    value.pop("completed_utc", None)
    unit.update(
        {
            "status": "awaiting_stage_assignment",
            "stage": stage_id,
            "stage_status": "awaiting_assignment",
        }
    )
    save_state(root, slug, task_state)
    write_yaml_atomic(stage_state_path(root, slug, presentation_id, unit_id), value)
    append_log(
        root,
        slug,
        actor="author-coordinator",
        kind="restart",
        presentation_id=presentation_id,
        unit_id=unit_id,
        message=(
            f"Reopened {stage_id}: {reason.strip()}. Planner must rewrite and reapprove this "
            "and all later stage assignments before work resumes."
        ),
    )
    return stage_status(root, slug, presentation_id, unit_id)


def all_stages_accepted(root: Path, slug: str, presentation_id: str, unit_id: str) -> bool:
    value = _load_stage_state(root, slug, presentation_id, unit_id)
    order = _stage_order(value)
    return all(
        isinstance(value["stages"].get(stage_id), dict)
        and value["stages"][stage_id].get("status") == "accepted"
        for stage_id in order
    )
