from __future__ import annotations

from pathlib import Path
from typing import Any

from mpres.tasks import require_gate
from mpres.util import (
    MPresError,
    ensure_within,
    task_path,
    read_yaml,
    relative_display,
    text_placeholders,
    utc_now,
    write_yaml_atomic,
)


def contract_paths(assignment_path: Path) -> tuple[Path, Path, Path]:
    parent = assignment_path.parent
    return (
        parent / "ASSIGNMENT-REQUEST.yaml",
        parent / "ASSIGNMENT-BRIEF.yaml",
        parent / "ASSIGNMENT-DECISION.yaml",
    )


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
    """Create a coordinator request and a planner-owned brief/decision scaffold.

    Coordinators may state why a role is needed, but only the main planner may replace the brief
    placeholders, write the exact Markdown assignment, and approve the contract.
    """

    request_path, brief_path, decision_path = contract_paths(assignment_path)
    request = {
        "schema_version": 2,
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
        "schema_version": 2,
        "assignment_id": assignment_id,
        "written_by": "planner",
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
        "schema_version": 2,
        "assignment_id": assignment_id,
        "status": "pending",
        "written_by": None,
        "decided_utc": None,
        "request_path": relative_display(request_path, root),
        "brief_path": relative_display(brief_path, root),
        "assignment_path": relative_display(assignment_path, root),
        "notes": None,
    }
    write_yaml_atomic(request_path, request)
    write_yaml_atomic(brief_path, brief)
    write_yaml_atomic(decision_path, decision)


def assignment_contract_status(assignment_path: Path) -> dict[str, Any]:
    request_path, brief_path, decision_path = contract_paths(assignment_path)
    request = read_yaml(request_path) if request_path.is_file() else None
    brief = read_yaml(brief_path) if brief_path.is_file() else None
    decision = read_yaml(decision_path) if decision_path.is_file() else None
    brief_placeholders = text_placeholders(brief_path) if brief_path.is_file() else ["missing"]
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
            and decision.get("written_by") == "planner"
            and isinstance(brief, dict)
            and brief.get("written_by") == "planner"
            and not brief_placeholders
        ),
    }


def approve_assignment(
    root: Path,
    slug: str,
    assignment_path: Path,
    *,
    notes: str | None = None,
) -> dict[str, Any]:
    """Record that the planner personally wrote the brief and exact assignment."""

    require_gate(root, slug)
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
    if not isinstance(request, dict) or request.get("status") not in {
        "awaiting_planner",
        "revision_requested",
    }:
        raise MPresError("Assignment request is missing or not awaiting the planner.")
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
    present_forbidden = [
        marker for marker in forbidden_reference_markers if marker in visible_contract_text
    ]
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
    request["status"] = "approved"
    request["approved_utc"] = now
    decision.update(
        {
            "status": "approved",
            "written_by": "planner",
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
