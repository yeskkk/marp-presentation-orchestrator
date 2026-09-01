from __future__ import annotations

from pathlib import Path
from typing import Any

from mpres.assignments import assignment_contract_status
from mpres.logs import append_log
from mpres.production_profiles import profile_for
from mpres.milestones import record_milestone
from mpres.state import get_content_unit, get_presentation, load_state, save_state, stage_ids_for_kind
from mpres.tasks import require_gate
from mpres.threads import list_threads
from mpres.util import (
    MPresError,
    read_yaml,
    relative_display,
    task_path,
    text_placeholders,
    utc_now,
    write_yaml_atomic,
)

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
    "m01_baseline_audit": "STAGE-M01-BASELINE-AUDIT.template.md",
    "m02_delta_design_patch": "STAGE-M02-DELTA-DESIGN-PATCH.template.md",
    "m03_integration_semantic_check": "STAGE-M03-INTEGRATION-SEMANTIC-CHECK.template.md",
    "r01_defect_scope": "STAGE-R01-DEFECT-SCOPE.template.md",
    "r02_patch_regression": "STAGE-R02-PATCH-REGRESSION.template.md",
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
    "m01_baseline_audit": 500,
    "m02_delta_design_patch": 500,
    "m03_integration_semantic_check": 500,
    "r01_defect_scope": 400,
    "r02_patch_regression": 500,
}


def unit_root(root: Path, slug: str, presentation_id: str, unit_id: str) -> Path:
    return task_path(root, slug) / "workers" / "lesson-authors" / presentation_id / unit_id


def stage_root(root: Path, slug: str, presentation_id: str, unit_id: str, stage_id: str) -> Path:
    return unit_root(root, slug, presentation_id, unit_id) / "stages" / stage_id


def stage_state_path(root: Path, slug: str, presentation_id: str, unit_id: str) -> Path:
    return unit_root(root, slug, presentation_id, unit_id) / "stages" / "STAGE-STATE.yaml"


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
    production_mode: str | None = None,
) -> None:
    stage_order = list(stage_ids_for_kind(task_kind, production_mode))
    stage_profile = profile_for(production_mode or "greenfield_full", task_kind).stage_profile
    values = {
        "[[PRESENTATION_ID]]": presentation_id,
        "[[UNIT_ID]]": unit_id,
        "[[UNIT_TITLE]]": unit_title,
    }
    stages: dict[str, Any] = {}
    for stage_id in stage_order:
        directory = stage_root(root, slug, presentation_id, unit_id, stage_id)
        directory.mkdir(parents=True, exist_ok=True)
        artifact = (
            root / "templates" / "stages" / STAGE_ARTIFACT_TEMPLATES[stage_id]
        ).read_text(encoding="utf-8")
        for old, replacement in values.items():
            artifact = artifact.replace(old, replacement)
        artifact_path = directory / "STAGE-ARTIFACT.md"
        artifact_path.write_text(artifact, encoding="utf-8", newline="\n")
        stages[stage_id] = {
            "status": "planned",
            "artifact": relative_display(artifact_path, root),
            "task_kind": task_kind,
            "production_mode": production_mode,
        }
    write_yaml_atomic(
        stage_state_path(root, slug, presentation_id, unit_id),
        {
            "schema_version": 5,
            "presentation_id": presentation_id,
            "unit_id": unit_id,
            "unit_title": unit_title,
            "task_kind": task_kind,
            "production_mode": production_mode,
            "stage_profile": stage_profile,
            "sequence_status": "awaiting_start",
            "stage_order": stage_order,
            "current_stage": stage_order[0],
            "fixed_author_for_all_stages": True,
            "thread_handle": None,
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
        production_mode=str(task_state.get("production_mode") or "greenfield_full"),
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


def _lesson_assignment(root: Path, slug: str, presentation_id: str, unit_id: str) -> Path:
    return unit_root(root, slug, presentation_id, unit_id) / "TASK-LESSON-AUTHOR.md"


def _require_lesson_assignment(root: Path, slug: str, presentation_id: str, unit_id: str) -> None:
    assignment = _lesson_assignment(root, slug, presentation_id, unit_id)
    contract = assignment_contract_status(assignment)
    if (
        not assignment.is_file()
        or text_placeholders(assignment)
        or len(assignment.read_text(encoding="utf-8").strip()) < 600
        or not contract.get("approved")
    ):
        raise MPresError(
            "The planner-written lesson assignment must be complete and approved before the "
            "single lesson-author thread starts its stage sequence."
        )


def _validate_thread_handle(
    root: Path,
    slug: str,
    presentation_id: str,
    unit_id: str,
    thread_handle: str,
) -> None:
    registry = list_threads(root, slug)
    rows = [item for item in registry.get("handles", []) if isinstance(item, dict)]
    row = next((item for item in rows if item.get("handle_id") == thread_handle), None)
    if row is None:
        raise MPresError(f"Unknown thread handle: {thread_handle}")
    expected_assignment = f"{presentation_id}:{unit_id}:lesson-author"
    if (
        row.get("state") != "active"
        or row.get("role") != "lesson-author"
        or row.get("presentation_id") != presentation_id
        or row.get("unit_id") != unit_id
        or row.get("current_assignment") != expected_assignment
    ):
        raise MPresError(
            "The supplied thread handle is not the active lesson-author thread for this whole unit."
        )


def stage_status(root: Path, slug: str, presentation_id: str, unit_id: str) -> dict[str, Any]:
    require_gate(root, slug)
    path = stage_state_path(root, slug, presentation_id, unit_id)
    if not path.is_file():
        state = load_state(root, slug)
        presentation = get_presentation(state, presentation_id)
        unit = get_content_unit(presentation, unit_id)
        return {
            "schema_version": 5,
            "presentation_id": presentation_id,
            "unit_id": unit_id,
            "production_mode": state.get("production_mode"),
            "stage_profile": state.get("stage_profile"),
            "fixed_author_for_all_stages": True,
            "sequence_status": "uninitialized",
            "current_stage": None,
            "thread_handle": None,
            "stages": {},
            "unit_status": unit.get("status", "uninitialized"),
            "lesson_assignment_contract": assignment_contract_status(
                _lesson_assignment(root, slug, presentation_id, unit_id)
            ),
            "path": relative_display(path, root),
        }
    value = _load_stage_state(root, slug, presentation_id, unit_id)
    value["lesson_assignment_contract"] = assignment_contract_status(
        _lesson_assignment(root, slug, presentation_id, unit_id)
    )
    return {**value, "path": relative_display(path, root)}


def start_stage_sequence(
    root: Path,
    slug: str,
    presentation_id: str,
    unit_id: str,
    *,
    thread_handle: str | None = None,
) -> dict[str, Any]:
    require_gate(root, slug)
    if not stage_state_path(root, slug, presentation_id, unit_id).is_file():
        from mpres.production import prepare_unit_workspace
        prepare_unit_workspace(root, slug, presentation_id, unit_id)
    _require_lesson_assignment(root, slug, presentation_id, unit_id)
    task_state = load_state(root, slug)
    presentation = get_presentation(task_state, presentation_id)
    unit = get_content_unit(presentation, unit_id)
    if presentation.get("status") != "authoring":
        raise MPresError(f"Cannot start lesson stages in {presentation.get('status')!r} status.")
    value = _load_stage_state(root, slug, presentation_id, unit_id)
    if value.get("sequence_status") not in {"awaiting_start", "reopened"}:
        raise MPresError("The lesson-author stage sequence has already started.")
    if thread_handle:
        _validate_thread_handle(root, slug, presentation_id, unit_id, thread_handle)
        value["thread_handle"] = thread_handle
    first = str(value.get("current_stage") or _stage_order(value)[0])
    value["sequence_status"] = "active"
    value["started_utc"] = value.get("started_utc") or utc_now()
    value["stages"][first]["status"] = "active"
    value["stages"][first]["activated_utc"] = utc_now()
    unit.update({"status": "running", "stage": first, "stage_status": "active"})
    save_state(root, slug, task_state)
    write_yaml_atomic(stage_state_path(root, slug, presentation_id, unit_id), value)
    append_log(
        root,
        slug,
        actor="critical-path-scheduler",
        kind="decision",
        presentation_id=presentation_id,
        unit_id=unit_id,
        message=(
            "Started the complete lesson-author stage sequence. The same lesson-author thread "
            "continues through every stage without new stage assignments or coordinator acceptance."
        ),
        data={"first_stage": first, "thread_handle": thread_handle},
    )
    return stage_status(root, slug, presentation_id, unit_id)


def activate_stage(
    root: Path,
    slug: str,
    presentation_id: str,
    unit_id: str,
    stage_id: str,
    *,
    thread_handle: str | None = None,
) -> dict[str, Any]:
    """Compatibility entry point: only the first/current stage starts the whole sequence."""

    value = _load_stage_state(root, slug, presentation_id, unit_id)
    if value.get("current_stage") != stage_id:
        raise MPresError(
            f"The stage sequence can start only at current stage {value.get('current_stage')!r}."
        )
    return start_stage_sequence(
        root,
        slug,
        presentation_id,
        unit_id,
        thread_handle=thread_handle,
    )


def _validate_stage_artifact(
    root: Path,
    slug: str,
    presentation_id: str,
    unit_id: str,
    stage_id: str,
) -> Path:
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
    return artifact


def submit_stage(
    root: Path,
    slug: str,
    presentation_id: str,
    unit_id: str,
    stage_id: str,
    *,
    thread_handle: str | None = None,
) -> dict[str, Any]:
    require_gate(root, slug)
    _require_lesson_assignment(root, slug, presentation_id, unit_id)
    task_state = load_state(root, slug)
    presentation = get_presentation(task_state, presentation_id)
    unit = get_content_unit(presentation, unit_id)
    if presentation.get("status") != "authoring":
        raise MPresError(f"Lesson stages cannot advance in {presentation.get('status')!r} status.")
    value = _load_stage_state(root, slug, presentation_id, unit_id)
    order = _stage_order(value)
    if value.get("sequence_status") != "active":
        raise MPresError("The lesson-author stage sequence is not active.")
    if value.get("current_stage") != stage_id:
        raise MPresError(f"Current stage is {value.get('current_stage')!r}, not {stage_id!r}.")
    entry = value["stages"].get(stage_id)
    if not isinstance(entry, dict) or entry.get("status") != "active":
        raise MPresError(f"Stage {stage_id} is not active.")
    recorded_handle = value.get("thread_handle")
    if recorded_handle:
        if thread_handle != recorded_handle:
            raise MPresError(
                "The stage must be submitted by the same lesson-author thread that started the sequence."
            )
        _validate_thread_handle(root, slug, presentation_id, unit_id, str(recorded_handle))
    elif thread_handle:
        _validate_thread_handle(root, slug, presentation_id, unit_id, thread_handle)
        value["thread_handle"] = thread_handle
    artifact = _validate_stage_artifact(root, slug, presentation_id, unit_id, stage_id)
    entry["status"] = "completed"
    entry["completed_utc"] = utc_now()
    index = order.index(stage_id)
    if index + 1 < len(order):
        next_stage = order[index + 1]
        value["current_stage"] = next_stage
        value["stages"][next_stage]["status"] = "active"
        value["stages"][next_stage]["activated_utc"] = utc_now()
        unit.update({"status": "running", "stage": next_stage, "stage_status": "active"})
        next_action = f"continue_same_thread:{next_stage}"
    else:
        value["current_stage"] = None
        value["sequence_status"] = "completed"
        value["completed_utc"] = utc_now()
        unit.update({"status": "handoff_ready", "stage": None, "stage_status": "completed"})
        next_action = "handoff_ready"
    save_state(root, slug, task_state)
    write_yaml_atomic(stage_state_path(root, slug, presentation_id, unit_id), value)
    append_log(
        root,
        slug,
        actor=f"lesson-author:{unit_id}",
        kind="handoff" if next_action == "handoff_ready" else "checkpoint",
        presentation_id=presentation_id,
        unit_id=unit_id,
        message=(
            f"Completed authoring stage {stage_id}; {next_action}. No new worker or stage assignment is created."
        ),
        data={"artifact": relative_display(artifact, root), "thread_handle": value.get("thread_handle")},
    )
    if next_action == "handoff_ready":
        record_milestone(root, slug, "unit_handoff", presentation_id=presentation_id, unit_id=unit_id)
    return stage_status(root, slug, presentation_id, unit_id)


def accept_stage(*args: Any, **kwargs: Any) -> dict[str, Any]:
    del args, kwargs
    raise MPresError(
        "Stage acceptance remains removed in v0.6.0. submit-stage automatically advances the same "
        "lesson-author thread after validating the durable stage artifact."
    )


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
        raise MPresError("Reopening an authoring stage requires a reason.")
    task_state = load_state(root, slug)
    presentation = get_presentation(task_state, presentation_id)
    unit = get_content_unit(presentation, unit_id)
    value = _load_stage_state(root, slug, presentation_id, unit_id)
    order = _stage_order(value)
    if stage_id not in order:
        raise MPresError(f"Unknown authoring stage: {stage_id}")
    index = order.index(stage_id)
    for current_index, current_stage in enumerate(order):
        stage_entry = value["stages"][current_stage]
        if current_index < index:
            stage_entry["status"] = "completed"
        elif current_index == index:
            stage_entry["status"] = "active"
            stage_entry["reopened_utc"] = utc_now()
            stage_entry["reopen_reason"] = reason.strip()
        else:
            stage_entry["status"] = "planned"
            for key in ("completed_utc", "activated_utc"):
                stage_entry.pop(key, None)
    value["current_stage"] = stage_id
    value["sequence_status"] = "active"
    value.pop("completed_utc", None)
    unit.update({"status": "running", "stage": stage_id, "stage_status": "active"})
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
            f"Reopened stage {stage_id} inside the existing lesson assignment; the same lesson-author "
            "thread resumes from this stage."
        ),
        data={"reason": reason.strip(), "thread_handle": value.get("thread_handle")},
    )
    return stage_status(root, slug, presentation_id, unit_id)


def all_stages_completed(root: Path, slug: str, presentation_id: str, unit_id: str) -> bool:
    value = _load_stage_state(root, slug, presentation_id, unit_id)
    order = _stage_order(value)
    return value.get("sequence_status") == "completed" and all(
        value["stages"].get(stage_id, {}).get("status") == "completed" for stage_id in order
    )


def all_stages_accepted(root: Path, slug: str, presentation_id: str, unit_id: str) -> bool:
    """Compatibility alias for older callers; v0.6.0 has no coordinator acceptance step."""

    return all_stages_completed(root, slug, presentation_id, unit_id)
