from __future__ import annotations

from pathlib import Path
from typing import Any

from mpres.milestones import record_milestone
from mpres.tasks import require_gate
from mpres.util import (
    MPresError,
    ensure_within,
    read_yaml,
    relative_display,
    task_path,
    text_placeholders,
    utc_now,
    write_yaml_atomic,
)

PLANNER_AUTHORSHIP_VALUES = {"planner", "planner-via-approved-batch"}


def contract_paths(assignment_path: Path) -> tuple[Path, Path, Path]:
    parent = assignment_path.parent
    return (
        parent / "ASSIGNMENT-REQUEST.yaml",
        parent / "ASSIGNMENT-BRIEF.yaml",
        parent / "ASSIGNMENT-DECISION.yaml",
    )


def batch_plan_path(root: Path, slug: str) -> Path:
    return task_path(root, slug) / "planning" / "BATCH-ASSIGNMENT-PLAN.yaml"


def scaffold_assignment_contract(
    root: Path,
    assignment_path: Path,
    *,
    assignment_id: str,
    role: str,
    presentation_id: str,
    unit_id: str | None = None,
    round_name: str | None = None,
    channel: str | None = None,
    requested_by: str,
    need: str,
) -> None:
    """Create a request and a planner-owned brief/decision scaffold.

    Any planner may write and approve the assignment. Only writing or revising top-level TASK.md is
    reserved to the main agent. A program-expanded assignment may instead inherit semantic content
    from one planner-approved batch plan.
    """

    request_path, brief_path, decision_path = contract_paths(assignment_path)
    request = {
        "schema_version": 3,
        "assignment_id": assignment_id,
        "role": role,
        "presentation_id": presentation_id,
        "unit_id": unit_id,
        "round": round_name,
        "channel": channel,
        "requested_utc": utc_now(),
        "requested_by": requested_by,
        "need": need,
        "structured_evidence": [],
        "status": "awaiting_planner",
    }
    brief = {
        "schema_version": 3,
        "assignment_id": assignment_id,
        "written_by": "planner",
        "planner_actor": "[[MAIN_OR_DELEGATED_PLANNER]]",
        "written_utc": "[[UTC]]",
        "role": role,
        "presentation_id": presentation_id,
        "unit_id": unit_id,
        "round": round_name,
        "channel": channel,
        "hard_constraints": ["[[HARD_CONSTRAINT]]"],
        "replaceable_hypotheses": ["[[HYPOTHESIS_OR_NONE]]"],
        "local_decision_rights": ["[[DECISION_RIGHT]]"],
        "approved_text_sources": ["[[EXTRACTED_TEXT_OR_WEB_SOURCE]]"],
        "acceptance_criteria": ["[[CRITERION]]"],
        "deferred_questions": ["[[DEFERRED_OR_NONE]]"],
    }
    decision = {
        "schema_version": 3,
        "assignment_id": assignment_id,
        "status": "pending",
        "written_by": None,
        "semantic_owner": "planner",
        "planner_actor": None,
        "approval_basis": "individual_assignment",
        "decided_utc": None,
        "request_path": relative_display(request_path, root),
        "brief_path": relative_display(brief_path, root),
        "assignment_path": relative_display(assignment_path, root),
        "notes": None,
    }
    write_yaml_atomic(request_path, request)
    write_yaml_atomic(brief_path, brief)
    write_yaml_atomic(decision_path, decision)


def initialize_batch_plan(
    root: Path,
    slug: str,
    presentations: list[dict[str, Any]],
    *,
    production_mode: str,
) -> dict[str, Any]:
    path = batch_plan_path(root, slug)
    if path.exists():
        raise MPresError(f"Batch assignment plan already exists: {path}")
    rows: list[dict[str, Any]] = []
    for presentation in presentations:
        units: list[dict[str, Any]] = []
        for unit in presentation.get("content_units", []):
            units.append(
                {
                    "id": unit["id"],
                    "unit_scope": "[[UNIT_SCOPE]]",
                    "audience_context": "[[AUDIENCE_CONTEXT]]",
                    "prior_knowledge_to_reactivate": "[[PRIOR_KNOWLEDGE_TO_REACTIVATE]]",
                    "local_decision_rights": ["[[UNIT_LOCAL_DECISION_RIGHT]]"],
                    "approved_text_sources": ["[[UNIT_APPROVED_TEXT_SOURCE_OR_NONE]]"],
                    "acceptance_criteria": ["[[UNIT_ACCEPTANCE_CRITERION]]"],
                    "baseline_source": "[[BASELINE_SOURCE_OR_NONE]]",
                    "baseline_maturity": "[[BASELINE_MATURITY_OR_NA]]",
                    "legacy_source_ranges": ["[[LEGACY_SOURCE_RANGE_OR_NONE]]"],
                    "required_delta": ["[[REQUIRED_DELTA_OR_GREENFIELD_OBJECTIVE]]"],
                    "known_risks": ["[[KNOWN_RISK_OR_NONE]]"],
                }
            )
        rows.append(
            {
                "id": presentation["id"],
                "title": presentation.get("title"),
                "common_constraints": ["[[PRESENTATION_COMMON_CONSTRAINT]]"],
                "units": units,
            }
        )
    value = {
        "schema_version": 1,
        "plan_id": "authoring-batch-001",
        "status": "draft",
        "written_by": "planner",
        "planner_actor": "[[MAIN_OR_DELEGATED_PLANNER]]",
        "production_mode": production_mode,
        "common": {
            "hard_constraints": ["[[COMMON_HARD_CONSTRAINT]]"],
            "replaceable_hypotheses": ["[[COMMON_REPLACEABLE_HYPOTHESIS]]"],
            "local_decision_rights": ["[[COMMON_LOCAL_DECISION_RIGHT]]"],
            "approved_text_sources": ["[[APPROVED_TEXT_SOURCE_OR_NONE]]"],
            "acceptance_criteria": ["[[COMMON_ACCEPTANCE_CRITERION]]"],
        },
        "presentations": rows,
        "approved_utc": None,
        "expanded_assignments": [],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    write_yaml_atomic(path, value)
    return {**value, "path": relative_display(path, root)}


def batch_plan_status(root: Path, slug: str) -> dict[str, Any]:
    path = batch_plan_path(root, slug)
    value = read_yaml(path) if path.is_file() else None
    placeholders = text_placeholders(path) if path.is_file() else ["missing"]
    approved = bool(
        isinstance(value, dict)
        and value.get("status") == "approved"
        and value.get("written_by") == "planner"
        and not placeholders
    )
    return {
        "path": relative_display(path, root),
        "value": value,
        "placeholders": placeholders,
        "approved": approved,
    }


def approve_batch_plan(
    root: Path,
    slug: str,
    *,
    planner_actor: str,
    notes: str | None = None,
) -> dict[str, Any]:
    require_gate(root, slug)
    if not planner_actor.strip():
        raise MPresError("Batch approval requires a main or delegated planner actor ID.")
    path = batch_plan_path(root, slug)
    value = read_yaml(path)
    if not isinstance(value, dict) or value.get("status") not in {"draft", "revision_requested"}:
        raise MPresError("Batch assignment plan is missing or not awaiting planner approval.")
    placeholders = text_placeholders(path)
    if placeholders:
        raise MPresError(
            "Planner cannot approve a batch plan that still contains placeholders: "
            + ", ".join(placeholders[:8])
        )
    if len(path.read_text(encoding="utf-8").strip()) < 800:
        raise MPresError("Batch plan is too short to define exact unit assignments.")
    if not isinstance(value.get("presentations"), list) or not value["presentations"]:
        raise MPresError("Batch plan must contain at least one presentation.")
    for presentation in value["presentations"]:
        if not isinstance(presentation, dict) or not isinstance(presentation.get("units"), list):
            raise MPresError("Every batch-plan presentation needs a unit list.")
        for unit in presentation["units"]:
            if not isinstance(unit, dict):
                raise MPresError("Every batch-plan unit must be a mapping.")
            for key in ("unit_scope", "audience_context", "prior_knowledge_to_reactivate"):
                if len(str(unit.get(key) or "").strip()) < 20:
                    raise MPresError(f"Batch-plan unit {unit.get('id')} has an incomplete {key}.")
            for key in ("local_decision_rights", "acceptance_criteria", "required_delta"):
                values = unit.get(key)
                if not isinstance(values, list) or not any(str(x).strip() for x in values):
                    raise MPresError(f"Batch-plan unit {unit.get('id')} needs {key}.")
    now = utc_now()
    value.update(
        {
            "status": "approved",
            "written_by": "planner",
            "planner_actor": planner_actor.strip(),
            "approved_utc": now,
            "notes": notes,
        }
    )
    write_yaml_atomic(path, value)
    record_milestone(root, slug, "batch_plan_approved", data={"planner_actor": planner_actor})
    return {"approved": True, "path": relative_display(path, root), "planner_actor": planner_actor}


def _unit_entry(plan: dict[str, Any], presentation_id: str, unit_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
    for presentation in plan.get("presentations", []):
        if isinstance(presentation, dict) and presentation.get("id") == presentation_id:
            for unit in presentation.get("units", []):
                if isinstance(unit, dict) and unit.get("id") == unit_id:
                    return presentation, unit
    raise MPresError(f"Approved batch plan has no unit {presentation_id}/{unit_id}.")


def batch_unit_instructions(root: Path, slug: str, presentation_id: str, unit_id: str) -> dict[str, Any]:
    status = batch_plan_status(root, slug)
    if not status["approved"]:
        raise MPresError("The planner-approved batch plan is required before unit expansion.")
    plan = status["value"]
    assert isinstance(plan, dict)
    presentation, unit = _unit_entry(plan, presentation_id, unit_id)
    return {
        "plan": plan,
        "presentation": presentation,
        "unit": unit,
        "plan_path": status["path"],
    }


def apply_batch_contract(
    root: Path,
    slug: str,
    assignment_path: Path,
    *,
    assignment_id: str,
    role: str,
    presentation_id: str,
    unit_id: str,
) -> dict[str, Any]:
    info = batch_unit_instructions(root, slug, presentation_id, unit_id)
    plan = info["plan"]
    presentation = info["presentation"]
    unit = info["unit"]
    common = plan.get("common") or {}
    request_path, brief_path, decision_path = contract_paths(assignment_path)
    hard_constraints = [*(common.get("hard_constraints") or []), *(presentation.get("common_constraints") or [])]
    local_rights = [*(common.get("local_decision_rights") or []), *(unit.get("local_decision_rights") or [])]
    sources = [*(common.get("approved_text_sources") or []), *(unit.get("approved_text_sources") or [])]
    criteria = [*(common.get("acceptance_criteria") or []), *(unit.get("acceptance_criteria") or [])]
    now = utc_now()
    request = {
        "schema_version": 3,
        "assignment_id": assignment_id,
        "role": role,
        "presentation_id": presentation_id,
        "unit_id": unit_id,
        "round": None,
        "channel": None,
        "requested_utc": now,
        "requested_by": "critical-path-scheduler",
        "need": "Expand one exact lesson-author assignment from the planner-approved batch plan.",
        "structured_evidence": [info["plan_path"]],
        "status": "approved",
        "approved_utc": now,
    }
    brief = {
        "schema_version": 3,
        "assignment_id": assignment_id,
        "written_by": "planner-via-approved-batch",
        "planner_actor": plan.get("planner_actor"),
        "written_utc": now,
        "role": role,
        "presentation_id": presentation_id,
        "unit_id": unit_id,
        "round": None,
        "channel": None,
        "hard_constraints": hard_constraints,
        "replaceable_hypotheses": common.get("replaceable_hypotheses") or ["none"],
        "local_decision_rights": local_rights,
        "approved_text_sources": sources,
        "acceptance_criteria": criteria,
        "deferred_questions": ["none"],
        "batch_plan_path": info["plan_path"],
    }
    decision = {
        "schema_version": 3,
        "assignment_id": assignment_id,
        "status": "approved",
        "written_by": "planner-via-approved-batch",
        "semantic_owner": "planner",
        "planner_actor": plan.get("planner_actor"),
        "approval_basis": "approved_batch_plan",
        "batch_plan_path": info["plan_path"],
        "expanded_by": "mpres",
        "decided_utc": now,
        "request_path": relative_display(request_path, root),
        "brief_path": relative_display(brief_path, root),
        "assignment_path": relative_display(assignment_path, root),
        "notes": "Deterministic expansion; semantic content is inherited from the planner-approved batch plan.",
    }
    write_yaml_atomic(request_path, request)
    write_yaml_atomic(brief_path, brief)
    write_yaml_atomic(decision_path, decision)
    expanded = list(plan.get("expanded_assignments") or [])
    coordinate = f"{presentation_id}/{unit_id}"
    if coordinate not in expanded:
        expanded.append(coordinate)
        plan["expanded_assignments"] = expanded
        write_yaml_atomic(batch_plan_path(root, slug), plan)
    return {"brief": brief, "decision": decision, "unit": unit, "presentation": presentation}


def assignment_contract_status(assignment_path: Path) -> dict[str, Any]:
    request_path, brief_path, decision_path = contract_paths(assignment_path)
    request = read_yaml(request_path) if request_path.is_file() else None
    brief = read_yaml(brief_path) if brief_path.is_file() else None
    decision = read_yaml(decision_path) if decision_path.is_file() else None
    brief_placeholders = text_placeholders(brief_path) if brief_path.is_file() else ["missing"]
    authorship = str((decision or {}).get("written_by") or "") if isinstance(decision, dict) else ""
    brief_authorship = str((brief or {}).get("written_by") or "") if isinstance(brief, dict) else ""
    return {
        "request_path": str(request_path),
        "brief_path": str(brief_path),
        "decision_path": str(decision_path),
        "request": request,
        "brief": brief,
        "decision": decision,
        "brief_placeholders": brief_placeholders,
        "approved": bool(
            isinstance(decision, dict)
            and decision.get("status") == "approved"
            and decision.get("semantic_owner", "planner") == "planner"
            and authorship in PLANNER_AUTHORSHIP_VALUES
            and isinstance(brief, dict)
            and brief_authorship in PLANNER_AUTHORSHIP_VALUES
            and not brief_placeholders
        ),
    }


def approve_assignment(
    root: Path,
    slug: str,
    assignment_path: Path,
    *,
    notes: str | None = None,
    planner_actor: str = "delegated-planner",
) -> dict[str, Any]:
    """Record that a main or delegated planner wrote the brief and exact assignment."""

    require_gate(root, slug)
    if not planner_actor.strip():
        raise MPresError("Assignment approval requires a planner actor ID.")
    assignment_path = assignment_path.expanduser().resolve()
    ensure_within(assignment_path, task_path(root, slug), label="assignment")
    if not assignment_path.is_file():
        raise MPresError(f"Assignment file does not exist: {assignment_path}")
    assignment_placeholders = text_placeholders(assignment_path)
    if assignment_placeholders:
        raise MPresError(
            "Planner cannot approve an assignment that still contains placeholders: "
            + ", ".join(assignment_placeholders[:8])
        )
    if len(assignment_path.read_text(encoding="utf-8").strip()) < 600:
        raise MPresError("Assignment is too short to contain an exact planner-written brief.")
    request_path, brief_path, decision_path = contract_paths(assignment_path)
    request = read_yaml(request_path)
    brief = read_yaml(brief_path)
    decision = read_yaml(decision_path)
    if not isinstance(request, dict) or request.get("status") not in {"awaiting_planner", "revision_requested"}:
        raise MPresError("Assignment request is missing or not awaiting a planner.")
    if not isinstance(brief, dict) or brief.get("written_by") != "planner":
        raise MPresError("Planner-owned ASSIGNMENT-BRIEF.yaml is missing or malformed.")
    visible_contract_text = (
        assignment_path.read_text(encoding="utf-8", errors="replace")
        + "\n"
        + brief_path.read_text(encoding="utf-8", errors="replace")
    ).lower()
    forbidden_reference_markers = (
        "downloads/restricted-originals",
        "downloads/originals",
        "downloads/restricted-metadata",
        ".pdf",
    )
    present_forbidden = [marker for marker in forbidden_reference_markers if marker in visible_contract_text]
    if present_forbidden:
        raise MPresError(
            "Planner assignment exposes an original PDF or restricted reference path: "
            + ", ".join(present_forbidden)
        )
    brief_placeholders = text_placeholders(brief_path)
    if brief_placeholders:
        raise MPresError(
            "Planner cannot approve an assignment whose structured brief still has placeholders: "
            + ", ".join(brief_placeholders[:8])
        )
    criteria = brief.get("acceptance_criteria")
    constraints = brief.get("hard_constraints")
    if not isinstance(criteria, list) or not any(str(item).strip() for item in criteria):
        raise MPresError("Assignment brief needs at least one acceptance criterion.")
    if not isinstance(constraints, list) or not any(str(item).strip() for item in constraints):
        raise MPresError("Assignment brief needs at least one hard constraint.")
    if not isinstance(decision, dict):
        raise MPresError("Assignment decision record is missing or malformed.")
    now = utc_now()
    brief["written_utc"] = now
    brief["planner_actor"] = planner_actor.strip()
    request["status"] = "approved"
    request["approved_utc"] = now
    decision.update(
        {
            "status": "approved",
            "written_by": "planner",
            "semantic_owner": "planner",
            "planner_actor": planner_actor.strip(),
            "approval_basis": "individual_assignment",
            "decided_utc": now,
            "notes": notes,
        }
    )
    write_yaml_atomic(brief_path, brief)
    write_yaml_atomic(request_path, request)
    write_yaml_atomic(decision_path, decision)
    return {
        "assignment_path": relative_display(assignment_path, root),
        "request_path": relative_display(request_path, root),
        "brief_path": relative_display(brief_path, root),
        "decision_path": relative_display(decision_path, root),
        "approved": True,
        "planner_actor": planner_actor.strip(),
    }


def revoke_assignment(
    root: Path,
    slug: str,
    assignment_path: Path,
    *,
    reason: str,
) -> dict[str, Any]:
    require_gate(root, slug)
    if not reason.strip():
        raise MPresError("Assignment revocation requires a reason.")
    request_path, brief_path, decision_path = contract_paths(assignment_path.resolve())
    request = read_yaml(request_path)
    decision = read_yaml(decision_path)
    if not isinstance(request, dict) or not isinstance(decision, dict):
        raise MPresError("Assignment contract is missing.")
    request["status"] = "revision_requested"
    request["revision_reason"] = reason.strip()
    decision.update(
        {
            "status": "revoked",
            "written_by": "planner",
            "semantic_owner": "planner",
            "decided_utc": utc_now(),
            "notes": reason.strip(),
        }
    )
    write_yaml_atomic(request_path, request)
    write_yaml_atomic(decision_path, decision)
    return {
        "assignment_path": str(assignment_path),
        "brief_path": str(brief_path),
        "approved": False,
        "reason": reason.strip(),
    }
