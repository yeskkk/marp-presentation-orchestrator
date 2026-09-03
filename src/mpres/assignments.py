from __future__ import annotations

from pathlib import Path
from typing import Any

from mpres.milestones import record_milestone
from mpres.scaffolds import (
    ScaffoldReport,
    ensure_mapping_identity,
    ensure_text,
    ensure_yaml,
    make_files_read_only,
    make_files_writable,
)
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

CONTRACT_SCHEMA_VERSION = 4


def _optional_yaml(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    value = read_yaml(path)
    if not isinstance(value, dict):
        raise MPresError(f"Assignment contract file must contain a mapping: {path}")
    return value


def _contract_identity(
    *,
    assignment_id: str,
    role: str,
    presentation_id: str,
    unit_id: str | None,
    round_name: str | None,
    channel: str | None,
) -> dict[str, Any]:
    return {
        "assignment_id": assignment_id,
        "role": role,
        "presentation_id": presentation_id,
        "unit_id": unit_id,
        "round": round_name,
        "channel": channel,
    }


def _validate_contract_identity(
    assignment_path: Path,
    expected: dict[str, Any],
) -> None:
    request_path, brief_path, decision_path = contract_paths(assignment_path)
    request = _optional_yaml(request_path)
    brief = _optional_yaml(brief_path)
    decision = _optional_yaml(decision_path)
    if request is not None:
        ensure_mapping_identity(request, expected, path=request_path)
    if brief is not None:
        ensure_mapping_identity(brief, expected, path=brief_path)
    if decision is not None:
        # v0.6.6 decisions only carried assignment_id. v0.6.7 writes the full
        # identity, while accepting that legacy shape during migration.
        decision_expected = {"assignment_id": expected["assignment_id"]}
        decision_expected.update({key: value for key, value in expected.items() if key in decision})
        ensure_mapping_identity(decision, decision_expected, path=decision_path)
        expected_assignment_path = decision.get("assignment_path")
        if expected_assignment_path is not None:
            normalized = str(expected_assignment_path).replace("\\", "/")
            if not normalized.endswith(assignment_path.name):
                raise MPresError(
                    f"Assignment decision points at a different taskbook: {decision_path}"
                )


def assignment_contract_files(assignment_path: Path) -> tuple[Path, Path, Path, Path]:
    request_path, brief_path, decision_path = contract_paths(assignment_path)
    return assignment_path, request_path, brief_path, decision_path


def protect_approved_assignment(assignment_path: Path) -> None:
    make_files_read_only(assignment_contract_files(assignment_path))


def unprotect_assignment_for_revision(assignment_path: Path) -> None:
    make_files_writable(assignment_contract_files(assignment_path))


def ensure_assignment_taskbook(assignment_path: Path, content: str) -> dict[str, Any]:
    """Create an assignment taskbook once and preserve every existing version.

    Workspace recovery is allowed to fill a missing taskbook, but an approved
    decision with a missing taskbook is considered corruption rather than an
    invitation to reconstruct unknown planner-authored text.
    """

    _request, _brief, decision_path = contract_paths(assignment_path)
    decision = _optional_yaml(decision_path)
    lifecycle = str(decision.get("status") or "") if isinstance(decision, dict) else ""
    if lifecycle in {"approved", "revoked"} and not assignment_path.is_file():
        raise MPresError(
            f"{lifecycle.title()} assignment taskbook is missing and cannot be regenerated: {assignment_path}"
        )
    report = ensure_text(assignment_path, content)
    approved_preserved = bool(
        isinstance(decision, dict)
        and decision.get("status") == "approved"
        and not report.changed
    )
    if approved_preserved:
        protect_approved_assignment(assignment_path)
    return {
        **report.as_dict(),
        "assignment_path": str(assignment_path),
        "approved_contract_preserved": approved_preserved,
    }


def batch_expansion_state_path(root: Path, slug: str) -> Path:
    return task_path(root, slug) / "planning" / "BATCH-ASSIGNMENT-EXPANSIONS.yaml"


def _record_batch_expansion(root: Path, slug: str, coordinate: str) -> dict[str, Any]:
    path = batch_expansion_state_path(root, slug)
    if path.is_file():
        value = read_yaml(path)
        if not isinstance(value, dict):
            raise MPresError(f"Batch expansion state is malformed: {path}")
    else:
        value = {
            "schema_version": 1,
            "batch_plan": relative_display(batch_plan_path(root, slug), root),
            "expanded_assignments": [],
            "updated_utc": None,
        }
    expanded = [str(item) for item in value.get("expanded_assignments", [])]
    if coordinate not in expanded:
        expanded.append(coordinate)
        value["expanded_assignments"] = expanded
        value["updated_utc"] = utc_now()
        write_yaml_atomic(path, value)
    return value


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
) -> dict[str, Any]:
    """Ensure one planner-owned contract without replacing existing files.

    Re-running a workspace scaffold is safe: existing planner edits, approvals,
    timestamps, and revocations are preserved byte-for-byte. Missing files from
    an interrupted *unapproved* scaffold are filled. An incomplete approved
    contract fails closed because its missing content cannot be reconstructed.
    """

    assignment_path = assignment_path.expanduser().resolve()
    request_path, brief_path, decision_path = contract_paths(assignment_path)
    expected = _contract_identity(
        assignment_id=assignment_id,
        role=role,
        presentation_id=presentation_id,
        unit_id=unit_id,
        round_name=round_name,
        channel=channel,
    )
    _validate_contract_identity(assignment_path, expected)

    existing_request = _optional_yaml(request_path)
    if isinstance(existing_request, dict):
        semantic_mismatches = []
        if existing_request.get("requested_by") != requested_by:
            semantic_mismatches.append("requested_by")
        if existing_request.get("need") != need:
            semantic_mismatches.append("need")
        if semantic_mismatches:
            raise MPresError(
                "Existing assignment request has different scaffold semantics and will not be overwritten: "
                + ", ".join(semantic_mismatches)
            )

    existing_decision = _optional_yaml(decision_path)
    lifecycle_status = (
        str(existing_decision.get("status") or "")
        if isinstance(existing_decision, dict)
        else ""
    )
    if lifecycle_status in {"approved", "revoked"}:
        missing = [
            str(path)
            for path in assignment_contract_files(assignment_path)
            if not path.is_file()
        ]
        if missing:
            raise MPresError(
                f"{lifecycle_status.title()} assignment contract is incomplete and may not be regenerated: "
                + ", ".join(missing)
            )
        if lifecycle_status == "approved":
            protect_approved_assignment(assignment_path)
        return {
            "assignment_path": relative_display(assignment_path, root),
            "created": [],
            "preserved": [
                relative_display(path, root) for path in assignment_contract_files(assignment_path)
            ],
            "changed": False,
            "approved_contract_preserved": lifecycle_status == "approved",
            "lifecycle_status": lifecycle_status,
        }

    now = utc_now()
    request = {
        "schema_version": CONTRACT_SCHEMA_VERSION,
        **expected,
        "requested_utc": now,
        "requested_by": requested_by,
        "need": need,
        "structured_evidence": [],
        "status": "awaiting_planner",
    }
    brief = {
        "schema_version": CONTRACT_SCHEMA_VERSION,
        **expected,
        "written_by": "planner",
        "planner_actor": "[[MAIN_OR_DELEGATED_PLANNER]]",
        "written_utc": "[[UTC]]",
        "hard_constraints": ["[[HARD_CONSTRAINT]]"],
        "replaceable_hypotheses": ["[[HYPOTHESIS_OR_NONE]]"],
        "local_decision_rights": ["[[DECISION_RIGHT]]"],
        "approved_text_sources": ["[[EXTRACTED_TEXT_OR_WEB_SOURCE]]"],
        "acceptance_criteria": ["[[CRITERION]]"],
        "deferred_questions": ["[[DEFERRED_OR_NONE]]"],
    }
    decision = {
        "schema_version": CONTRACT_SCHEMA_VERSION,
        **expected,
        "status": "pending",
        "written_by": None,
        "semantic_owner": "planner",
        "planner_actor": None,
        "approval_basis": "individual_assignment",
        "decided_utc": None,
        "immutable_after_approval": False,
        "revision_requires_explicit_revoke": True,
        "approval_sequence": 0,
        "request_path": relative_display(request_path, root),
        "brief_path": relative_display(brief_path, root),
        "assignment_path": relative_display(assignment_path, root),
        "notes": None,
    }

    report = ScaffoldReport()
    report.merge(ensure_yaml(request_path, request))
    report.merge(ensure_yaml(brief_path, brief))
    # Decision is the commit marker and is always created last.
    report.merge(ensure_yaml(decision_path, decision))
    _validate_contract_identity(assignment_path, expected)
    published_request = _optional_yaml(request_path) or {}
    semantic_mismatches = [
        field
        for field, desired in (("requested_by", requested_by), ("need", need))
        if published_request.get(field) != desired
    ]
    if semantic_mismatches:
        raise MPresError(
            "Concurrent assignment scaffold published different request semantics and was preserved: "
            + ", ".join(semantic_mismatches)
        )
    return {
        "assignment_path": relative_display(assignment_path, root),
        "created": [relative_display(Path(path), root) for path in report.created],
        "preserved": [relative_display(Path(path), root) for path in report.preserved],
        "changed": report.changed,
        "approved_contract_preserved": False,
        "lifecycle_status": "pending",
    }



def initialize_batch_plan(
    root: Path,
    slug: str,
    presentations: list[dict[str, Any]],
    *,
    production_mode: str,
) -> dict[str, Any]:
    path = batch_plan_path(root, slug)
    if path.exists():
        value = read_yaml(path)
        if not isinstance(value, dict):
            raise MPresError(f"Batch assignment plan is malformed: {path}")
        expected_topology = [
            (str(presentation["id"]), [str(unit["id"]) for unit in presentation.get("content_units", [])])
            for presentation in presentations
        ]
        actual_topology = [
            (
                str(presentation.get("id")),
                [str(unit.get("id")) for unit in presentation.get("units", []) if isinstance(unit, dict)],
            )
            for presentation in value.get("presentations", [])
            if isinstance(presentation, dict)
        ]
        if value.get("production_mode") != production_mode or actual_topology != expected_topology:
            raise MPresError(
                "Existing batch assignment plan belongs to a different production topology; "
                "it will not be overwritten."
            )
        if value.get("status") == "approved":
            make_files_read_only([path])
        return {
            **value,
            "path": relative_display(path, root),
            "already_initialized": True,
        }

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
        "schema_version": 2,
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
        # Retained as a legacy projection. v0.6.7 writes operational expansion
        # state to BATCH-ASSIGNMENT-EXPANSIONS.yaml instead of mutating this plan.
        "expanded_assignments": [],
        "immutable_after_approval": True,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    ensure_yaml(path, value)
    return {**value, "path": relative_display(path, root), "already_initialized": False}



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
    if not isinstance(value, dict):
        raise MPresError("Batch assignment plan is missing or malformed.")
    if value.get("status") == "approved":
        original_actor = str(value.get("planner_actor") or "")
        if original_actor != planner_actor.strip():
            raise MPresError(
                f"Batch plan is already approved by {original_actor!r}; it cannot be re-attributed."
            )
        if notes != value.get("notes"):
            raise MPresError(
                "Batch plan is already approved with different notes; revoke it before revising approval metadata."
            )
        make_files_read_only([path])
        return {
            "approved": True,
            "already_approved": True,
            "path": relative_display(path, root),
            "planner_actor": original_actor,
            "approved_utc": value.get("approved_utc"),
            "approval_sequence": int(value.get("approval_sequence") or 1),
        }
    if value.get("status") not in {"draft", "revision_requested"}:
        raise MPresError("Batch assignment plan is not awaiting planner approval.")
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
    sequence = int(value.get("approval_sequence") or 0) + 1
    make_files_writable([path])
    value.update(
        {
            "schema_version": max(int(value.get("schema_version") or 1), 2),
            "status": "approved",
            "written_by": "planner",
            "planner_actor": planner_actor.strip(),
            "approved_utc": now,
            "first_approved_utc": value.get("first_approved_utc") or now,
            "approval_sequence": sequence,
            "notes": notes,
            "immutable_after_approval": True,
        }
    )
    value.pop("revision_requested_utc", None)
    value.pop("revision_reason", None)
    write_yaml_atomic(path, value)
    make_files_read_only([path])
    record_milestone(root, slug, "batch_plan_approved", data={"planner_actor": planner_actor})
    return {
        "approved": True,
        "already_approved": False,
        "path": relative_display(path, root),
        "planner_actor": planner_actor.strip(),
        "approved_utc": now,
        "approval_sequence": sequence,
    }


def revoke_batch_plan(
    root: Path,
    slug: str,
    *,
    reason: str,
) -> dict[str, Any]:
    """Explicitly reopen an approved batch plan for planner revision.

    Expansion state is kept in a separate operational file, so reopening the
    semantic plan never erases which lesson assignments have already been
    materialized. Repeated revocation with the same reason is a no-op.
    """

    require_gate(root, slug)
    if not reason.strip():
        raise MPresError("Batch-plan revocation requires a reason.")
    path = batch_plan_path(root, slug)
    value = read_yaml(path)
    if not isinstance(value, dict):
        raise MPresError("Batch assignment plan is missing or malformed.")
    status = str(value.get("status") or "")
    if status == "revision_requested":
        existing_reason = str(value.get("revision_reason") or "")
        if existing_reason != reason.strip():
            raise MPresError(
                "Batch plan is already reopened for a different reason; preserve the original revision record."
            )
        make_files_writable([path])
        return {
            "approved": False,
            "already_revoked": True,
            "path": relative_display(path, root),
            "reason": existing_reason,
            "approval_sequence": int(value.get("approval_sequence") or 1),
        }
    if status != "approved":
        raise MPresError("Only an approved batch plan may be explicitly revoked for revision.")
    make_files_writable([path])
    now = utc_now()
    value.update(
        {
            "status": "revision_requested",
            "revision_requested_utc": now,
            "revision_reason": reason.strip(),
            "immutable_after_approval": False,
        }
    )
    write_yaml_atomic(path, value)
    return {
        "approved": False,
        "already_revoked": False,
        "path": relative_display(path, root),
        "reason": reason.strip(),
        "approval_sequence": int(value.get("approval_sequence") or 1),
    }



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
    hard_constraints = [
        *(common.get("hard_constraints") or []),
        *(presentation.get("common_constraints") or []),
    ]
    local_rights = [
        *(common.get("local_decision_rights") or []),
        *(unit.get("local_decision_rights") or []),
    ]
    sources = [
        *(common.get("approved_text_sources") or []),
        *(unit.get("approved_text_sources") or []),
    ]
    criteria = [
        *(common.get("acceptance_criteria") or []),
        *(unit.get("acceptance_criteria") or []),
    ]
    expected = _contract_identity(
        assignment_id=assignment_id,
        role=role,
        presentation_id=presentation_id,
        unit_id=unit_id,
        round_name=None,
        channel=None,
    )
    _validate_contract_identity(assignment_path, expected)
    existing_request = _optional_yaml(request_path)
    existing_brief = _optional_yaml(brief_path)
    existing_decision = _optional_yaml(decision_path)

    # A manually scaffolded contract must not be silently converted into a
    # batch-expanded approval. Only an interrupted batch expansion may resume.
    if existing_request is not None and existing_request.get("requested_by") != "critical-path-scheduler":
        raise MPresError(
            "Existing lesson assignment request was not created by batch expansion and will not be overwritten."
        )
    if existing_brief is not None and existing_brief.get("written_by") != "planner-via-approved-batch":
        raise MPresError(
            "Existing lesson assignment brief is not a batch-derived planner brief and will not be overwritten."
        )
    if existing_decision is not None and existing_decision.get("approval_basis") not in {
        None,
        "approved_batch_plan",
    }:
        raise MPresError(
            "Existing lesson assignment decision has a different approval basis and will not be overwritten."
        )

    now = (
        (existing_request or {}).get("requested_utc")
        or (existing_brief or {}).get("written_utc")
        or (existing_decision or {}).get("decided_utc")
        or utc_now()
    )
    request = {
        "schema_version": CONTRACT_SCHEMA_VERSION,
        **expected,
        "requested_utc": now,
        "requested_by": "critical-path-scheduler",
        "need": "Expand one exact lesson-author assignment from the planner-approved batch plan.",
        "structured_evidence": [info["plan_path"]],
        "status": "approved",
        "approved_utc": now,
    }
    brief = {
        "schema_version": CONTRACT_SCHEMA_VERSION,
        **expected,
        "written_by": "planner-via-approved-batch",
        "planner_actor": plan.get("planner_actor"),
        "written_utc": now,
        "hard_constraints": hard_constraints,
        "replaceable_hypotheses": common.get("replaceable_hypotheses") or ["none"],
        "local_decision_rights": local_rights,
        "approved_text_sources": sources,
        "acceptance_criteria": criteria,
        "deferred_questions": ["none"],
        "batch_plan_path": info["plan_path"],
    }
    decision = {
        "schema_version": CONTRACT_SCHEMA_VERSION,
        **expected,
        "status": "approved",
        "written_by": "planner-via-approved-batch",
        "semantic_owner": "planner",
        "planner_actor": plan.get("planner_actor"),
        "approval_basis": "approved_batch_plan",
        "batch_plan_path": info["plan_path"],
        "expanded_by": "mpres",
        "decided_utc": now,
        "immutable_after_approval": True,
        "revision_requires_explicit_revoke": True,
        "approval_sequence": 1,
        "request_path": relative_display(request_path, root),
        "brief_path": relative_display(brief_path, root),
        "assignment_path": relative_display(assignment_path, root),
        "notes": "Deterministic expansion; semantic content is inherited from the planner-approved batch plan.",
    }

    report = ScaffoldReport()
    report.merge(ensure_yaml(request_path, request))
    report.merge(ensure_yaml(brief_path, brief))
    report.merge(ensure_yaml(decision_path, decision))
    _validate_contract_identity(assignment_path, expected)

    current_request = _optional_yaml(request_path) or {}
    current_brief = _optional_yaml(brief_path) or {}
    current_decision = _optional_yaml(decision_path) or {}
    semantic_expectations = (
        (current_request, request, ("requested_by", "need", "structured_evidence", "status"), request_path),
        (
            current_brief,
            brief,
            (
                "written_by",
                "planner_actor",
                "hard_constraints",
                "replaceable_hypotheses",
                "local_decision_rights",
                "approved_text_sources",
                "acceptance_criteria",
                "deferred_questions",
                "batch_plan_path",
            ),
            brief_path,
        ),
        (
            current_decision,
            decision,
            ("status", "written_by", "semantic_owner", "approval_basis", "batch_plan_path"),
            decision_path,
        ),
    )
    for actual, desired, fields, path in semantic_expectations:
        mismatches = [field for field in fields if actual.get(field) != desired.get(field)]
        if mismatches:
            raise MPresError(
                f"Existing batch-expanded contract differs from the approved plan at {path}: "
                + ", ".join(mismatches)
            )

    protect_approved_assignment(assignment_path)
    coordinate = f"{presentation_id}/{unit_id}"
    expansion_state = _record_batch_expansion(root, slug, coordinate)
    return {
        "brief": current_brief,
        "decision": current_decision,
        "unit": unit,
        "presentation": presentation,
        "already_applied": not report.changed,
        "created": report.created,
        "preserved": report.preserved,
        "expansion_state": expansion_state,
    }



def assignment_contract_status(assignment_path: Path) -> dict[str, Any]:
    request_path, brief_path, decision_path = contract_paths(assignment_path)
    request = _optional_yaml(request_path)
    brief = _optional_yaml(brief_path)
    decision = _optional_yaml(decision_path)
    brief_placeholders = text_placeholders(brief_path) if brief_path.is_file() else ["missing"]
    authorship = str((decision or {}).get("written_by") or "") if isinstance(decision, dict) else ""
    brief_authorship = str((brief or {}).get("written_by") or "") if isinstance(brief, dict) else ""
    missing_paths = [
        str(path)
        for path in assignment_contract_files(assignment_path)
        if not path.is_file()
    ]
    identity_fields = (
        "assignment_id",
        "role",
        "presentation_id",
        "unit_id",
        "round",
        "channel",
    )
    identity_consistent = True
    identity_mismatches: list[str] = []
    for field in identity_fields:
        values = {
            value.get(field)
            for value in (request, brief, decision)
            if isinstance(value, dict) and field in value
        }
        if len(values) > 1:
            identity_consistent = False
            identity_mismatches.append(field)
    approved = bool(
        not missing_paths
        and identity_consistent
        and isinstance(decision, dict)
        and decision.get("status") == "approved"
        and decision.get("semantic_owner", "planner") == "planner"
        and authorship in PLANNER_AUTHORSHIP_VALUES
        and isinstance(brief, dict)
        and brief_authorship in PLANNER_AUTHORSHIP_VALUES
        and not brief_placeholders
    )
    lifecycle_status = (
        "approved"
        if approved
        else "revoked"
        if isinstance(decision, dict) and decision.get("status") == "revoked"
        else "incomplete"
        if missing_paths
        else "pending"
    )
    files = assignment_contract_files(assignment_path)
    write_protected = bool(files) and all(
        path.is_file() and not (path.stat().st_mode & 0o222) for path in files
    )
    return {
        "request_path": str(request_path),
        "brief_path": str(brief_path),
        "decision_path": str(decision_path),
        "request": request,
        "brief": brief,
        "decision": decision,
        "brief_placeholders": brief_placeholders,
        "missing_paths": missing_paths,
        "complete": not missing_paths,
        "identity_consistent": identity_consistent,
        "identity_mismatches": identity_mismatches,
        "lifecycle_status": lifecycle_status,
        "immutable_after_approval": bool(
            approved and (decision or {}).get("immutable_after_approval", True)
        ),
        "revision_requires_explicit_revoke": bool(
            approved and (decision or {}).get("revision_requires_explicit_revoke", True)
        ),
        "write_protected": write_protected,
        "approved": approved,
    }



def approve_assignment(
    root: Path,
    slug: str,
    assignment_path: Path,
    *,
    notes: str | None = None,
    planner_actor: str = "delegated-planner",
) -> dict[str, Any]:
    """Approve once; repeated identical approval is a read-only no-op."""

    require_gate(root, slug)
    if not planner_actor.strip():
        raise MPresError("Assignment approval requires a planner actor ID.")
    assignment_path = assignment_path.expanduser().resolve()
    ensure_within(assignment_path, task_path(root, slug), label="assignment")
    if not assignment_path.is_file():
        raise MPresError(f"Assignment file does not exist: {assignment_path}")
    request_path, brief_path, decision_path = contract_paths(assignment_path)
    status = assignment_contract_status(assignment_path)
    decision = status.get("decision")
    if isinstance(decision, dict) and decision.get("status") == "approved":
        if not status.get("approved"):
            raise MPresError(
                "Assignment decision says approved but the contract is incomplete or inconsistent; "
                "automatic regeneration is forbidden."
            )
        original_actor = str(decision.get("planner_actor") or "")
        if original_actor != planner_actor.strip():
            raise MPresError(
                f"Assignment is already approved by {original_actor!r}; revoke it before changing authorship."
            )
        if notes != decision.get("notes"):
            raise MPresError(
                "Assignment is already approved with different notes; revoke it before revising approval metadata."
            )
        protect_approved_assignment(assignment_path)
        return {
            "assignment_path": relative_display(assignment_path, root),
            "request_path": relative_display(request_path, root),
            "brief_path": relative_display(brief_path, root),
            "decision_path": relative_display(decision_path, root),
            "approved": True,
            "already_approved": True,
            "planner_actor": original_actor,
            "approved_utc": decision.get("decided_utc"),
            "approval_sequence": int(decision.get("approval_sequence") or 1),
        }

    assignment_placeholders = text_placeholders(assignment_path)
    if assignment_placeholders:
        raise MPresError(
            "Planner cannot approve an assignment that still contains placeholders: "
            + ", ".join(assignment_placeholders[:8])
        )
    if len(assignment_path.read_text(encoding="utf-8").strip()) < 600:
        raise MPresError("Assignment is too short to contain an exact planner-written brief.")
    request = status.get("request")
    brief = status.get("brief")
    decision = status.get("decision")
    if not isinstance(request, dict) or request.get("status") not in {
        "awaiting_planner",
        "revision_requested",
        "approved",  # interrupted approval may have written request before decision
    }:
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
    if decision.get("status") not in {"pending", "revoked", None}:
        raise MPresError(f"Assignment decision is not approvable from {decision.get('status')!r} status.")

    unprotect_assignment_for_revision(assignment_path)
    now = utc_now()
    sequence = int(decision.get("approval_sequence") or 0) + 1
    brief["schema_version"] = max(int(brief.get("schema_version") or 1), CONTRACT_SCHEMA_VERSION)
    brief["written_utc"] = now
    brief["planner_actor"] = planner_actor.strip()
    request["schema_version"] = max(int(request.get("schema_version") or 1), CONTRACT_SCHEMA_VERSION)
    request["status"] = "approved"
    request["approved_utc"] = now
    request.pop("revision_reason", None)
    decision.update(
        {
            "schema_version": max(int(decision.get("schema_version") or 1), CONTRACT_SCHEMA_VERSION),
            "status": "approved",
            "written_by": "planner",
            "semantic_owner": "planner",
            "planner_actor": planner_actor.strip(),
            "approval_basis": "individual_assignment",
            "decided_utc": now,
            "first_approved_utc": decision.get("first_approved_utc") or now,
            "approval_sequence": sequence,
            "immutable_after_approval": True,
            "revision_requires_explicit_revoke": True,
            "notes": notes,
        }
    )
    decision.pop("revoked_utc", None)
    decision.pop("revocation_reason", None)
    write_yaml_atomic(brief_path, brief)
    write_yaml_atomic(request_path, request)
    # The decision is written last and is the approval commit marker.
    write_yaml_atomic(decision_path, decision)
    protect_approved_assignment(assignment_path)
    return {
        "assignment_path": relative_display(assignment_path, root),
        "request_path": relative_display(request_path, root),
        "brief_path": relative_display(brief_path, root),
        "decision_path": relative_display(decision_path, root),
        "approved": True,
        "already_approved": False,
        "planner_actor": planner_actor.strip(),
        "approved_utc": now,
        "approval_sequence": sequence,
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
    assignment_path = assignment_path.expanduser().resolve()
    ensure_within(assignment_path, task_path(root, slug), label="assignment")
    request_path, brief_path, decision_path = contract_paths(assignment_path)
    request = _optional_yaml(request_path)
    decision = _optional_yaml(decision_path)
    if not isinstance(request, dict) or not isinstance(decision, dict):
        raise MPresError("Assignment contract is missing.")
    if decision.get("status") == "revoked" and request.get("status") == "revision_requested":
        existing_reason = str(decision.get("revocation_reason") or decision.get("notes") or "")
        if existing_reason != reason.strip():
            raise MPresError(
                "Assignment is already revoked for a different reason; preserve the original revision record."
            )
        unprotect_assignment_for_revision(assignment_path)
        return {
            "assignment_path": str(assignment_path),
            "brief_path": str(brief_path),
            "approved": False,
            "already_revoked": True,
            "reason": existing_reason,
            "approval_sequence": int(decision.get("approval_sequence") or 0),
        }
    if decision.get("status") != "approved":
        raise MPresError("Only an approved assignment may be explicitly revoked for revision.")

    unprotect_assignment_for_revision(assignment_path)
    now = utc_now()
    request["status"] = "revision_requested"
    request["revision_reason"] = reason.strip()
    request["revision_requested_utc"] = now
    decision.update(
        {
            "status": "revoked",
            "written_by": "planner",
            "semantic_owner": "planner",
            "decided_utc": now,
            "revoked_utc": now,
            "revocation_reason": reason.strip(),
            "immutable_after_approval": False,
            "revision_requires_explicit_revoke": True,
            "notes": reason.strip(),
        }
    )
    write_yaml_atomic(request_path, request)
    write_yaml_atomic(decision_path, decision)
    return {
        "assignment_path": str(assignment_path),
        "brief_path": str(brief_path),
        "approved": False,
        "already_revoked": False,
        "reason": reason.strip(),
        "approval_sequence": int(decision.get("approval_sequence") or 0),
    }
