from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any, Mapping

from mpres.logs import append_log
from mpres.policy import propose_policy_change
from mpres.state import load_state, save_state
from mpres.tasks import gate_status
from mpres.transactions import transactional_task_mutation
from mpres.util import MPresError, read_yaml, safe_id, task_path, utc_now, write_yaml_atomic

INCIDENT_INDEX_FIELD = "engine_incident_index"
INCIDENT_INDEX_SCHEMA_VERSION = 1
INCIDENT_SCHEMA_VERSION = 2
DEFAULT_RECURRENCE_THRESHOLD = 2
REQUIRED_WORKAROUND_FORBIDDEN_EFFECTS = {
    "modify_workflow_engine_source",
    "change_model_or_reasoning_effort",
    "bypass_review_or_release_gates",
    "falsify_state_or_token_data",
}
ALLOWED_WORKAROUND_EFFECTS = {
    "change_invocation_order",
    "use_temporary_staging_path",
    "restore_permissions_on_copied_workspace",
    "skip_verified_redundant_step",
    "retry_idempotent_control_operation_once",
}


def _engine_policy(root: Path, slug: str) -> dict[str, Any]:
    execution = read_yaml(task_path(root, slug) / "EXECUTION-POLICY.yaml")
    if not isinstance(execution, dict) or not isinstance(execution.get("engine_changes"), dict):
        raise MPresError("EXECUTION-POLICY.yaml engine_changes must be a mapping.")
    return execution["engine_changes"]


def _threshold(root: Path, slug: str) -> int:
    value = _engine_policy(root, slug).get(
        "deterministic_recurrence_threshold", DEFAULT_RECURRENCE_THRESHOLD
    )
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise MPresError("deterministic_recurrence_threshold must be a positive integer.")
    return value


def _empty_index(root: Path, slug: str) -> dict[str, Any]:
    return {
        "schema_version": INCIDENT_INDEX_SCHEMA_VERSION,
        "recurrence_key": "incident_id",
        "deterministic_recurrence_threshold": _threshold(root, slug),
        "incidents": {},
    }


def _summary_path(root: Path, slug: str, incident_id: str) -> Path:
    return task_path(root, slug) / "engine-incidents" / f"{incident_id}.yaml"


def _incident_dir(root: Path, slug: str, incident_id: str) -> Path:
    return task_path(root, slug) / "engine-incidents" / incident_id


def _index_path(root: Path, slug: str) -> Path:
    return task_path(root, slug) / "engine-incidents" / "INCIDENT-INDEX.yaml"


def workaround_draft_path(root: Path, slug: str, incident_id: str) -> Path:
    incident_id = safe_id(incident_id, label="engine incident ID")
    return _incident_dir(root, slug, incident_id) / "OPERATIONAL-WORKAROUND.yaml"


def _migrate_v064_summary(value: Mapping[str, Any], threshold: int) -> dict[str, Any]:
    incident_id = str(value.get("incident_id") or "")
    recorded = str(value.get("recorded_utc") or utc_now())
    blocked = str(value.get("blocked_operation") or "unspecified operation")
    occurrence = {
        "sequence": 1,
        "recorded_utc": recorded,
        "symptom": str(value.get("symptom") or "Migrated v0.6.4 incident"),
        "reproduction": [str(x) for x in value.get("reproduction") or []],
        "blocked_operation": blocked,
        "presentation_id": None,
        "deterministic": True,
        "evidence": [],
        "task_confirmation_sequence": 0,
        "migrated_from_v0_6_4": True,
    }
    return {
        "schema_version": INCIDENT_SCHEMA_VERSION,
        "incident_id": incident_id,
        "classification": value.get(
            "classification", "confirmed_or_suspected_workflow_engine_bug"
        ),
        "in_task_engine_edit_allowed": False,
        "first_recorded_utc": recorded,
        "last_recorded_utc": recorded,
        "occurrence_count": 1,
        "deterministic_occurrence_count": 1,
        "suspected_occurrence_count": 0,
        "blocked_operation": blocked,
        "affected_presentations": [],
        "occurrences": [occurrence],
        "policy_amendment_request": value.get("policy_amendment_request"),
        "required_action": value.get("required_action")
        or (
            "Do not hot-patch the workflow engine. Reconfirm the task policy and prepare an "
            "exact, reversible operational workaround before retrying a repeated failure."
        ),
        "circuit_breaker": {
            "threshold": threshold,
            "open": False,
            "opened_utc": None,
            "opened_on_occurrence": None,
            "active_workaround_id": None,
        },
        "approved_workarounds": {},
        "workaround_applications": [],
        "status": str(value.get("status") or "awaiting_policy_amendment"),
    }


def _index_from_state(root: Path, slug: str, state: Mapping[str, Any]) -> dict[str, Any]:
    raw = state.get(INCIDENT_INDEX_FIELD)
    if isinstance(raw, dict) and isinstance(raw.get("incidents"), dict):
        index = deepcopy(raw)
        index["deterministic_recurrence_threshold"] = _threshold(root, slug)
        return index
    index = _empty_index(root, slug)
    incident_root = task_path(root, slug) / "engine-incidents"
    for path in sorted(incident_root.glob("*.yaml")):
        if path.name == "INCIDENT-INDEX.yaml":
            continue
        value = read_yaml(path)
        if not isinstance(value, dict) or not value.get("incident_id"):
            continue
        item = _migrate_v064_summary(value, int(index["deterministic_recurrence_threshold"]))
        index["incidents"][item["incident_id"]] = item
    return index


def _new_workaround_draft(incident_id: str) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "incident_id": incident_id,
        "workaround_id": f"{incident_id}-operational",
        "status": "draft",
        "title": "",
        "preconditions": [],
        "steps": [],
        "verification": [],
        "rollback": [],
        "reversible": True,
        "allowed_effects": [],
        "forbidden_effects": sorted(REQUIRED_WORKAROUND_FORBIDDEN_EFFECTS),
        "agent_may_invent_or_modify": False,
        "arbitrary_command_execution_by_control_plane": False,
        "requires_TASK_reconfirmation": True,
        "approval_note": (
            "Edit this exact plan, set status to proposed, mention it in the TASK policy "
            "amendment, present TASK.md, and obtain explicit user reconfirmation."
        ),
    }


def _ensure_workaround_draft(root: Path, slug: str, incident_id: str) -> Path:
    path = workaround_draft_path(root, slug, incident_id)
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        write_yaml_atomic(path, _new_workaround_draft(incident_id))
    return path


def operational_workaround_snapshots(root: Path, slug: str) -> dict[str, Any]:
    """Return exact plans presented with TASK.md; no additional hash is created."""
    output: dict[str, Any] = {}
    base = task_path(root, slug) / "engine-incidents"
    for path in sorted(base.glob("*/OPERATIONAL-WORKAROUND.yaml")) if base.is_dir() else []:
        value = read_yaml(path)
        if not isinstance(value, dict):
            raise MPresError(f"Operational workaround must be a mapping: {path}")
        incident_id = safe_id(
            str(value.get("incident_id") or path.parent.name), label="engine incident ID"
        )
        if incident_id != path.parent.name:
            raise MPresError(f"Workaround incident_id does not match its directory: {path}")
        output[incident_id] = value
    return output


def _sync_views(root: Path, slug: str, state: Mapping[str, Any]) -> None:
    index = _index_from_state(root, slug, state)
    write_yaml_atomic(
        _index_path(root, slug),
        {
            **index,
            "generated_from_task_state_revision": state.get("state_revision"),
            "generated_utc": utc_now(),
        },
    )
    for incident_id, incident in index.get("incidents", {}).items():
        write_yaml_atomic(
            _summary_path(root, slug, incident_id),
            {**incident, "generated_from_task_state_revision": state.get("state_revision")},
        )
        occurrence_dir = _incident_dir(root, slug, incident_id) / "occurrences"
        occurrence_dir.mkdir(parents=True, exist_ok=True)
        for occurrence in incident.get("occurrences", []):
            sequence = int(occurrence.get("sequence", 0))
            path = occurrence_dir / f"{sequence:04d}.yaml"
            if sequence > 0 and not path.exists():
                write_yaml_atomic(
                    path,
                    {"schema_version": 1, "incident_id": incident_id, **occurrence},
                )


@transactional_task_mutation
def initialize_incident_index(root: Path, slug: str) -> dict[str, Any]:
    state = load_state(root, slug)
    index = _index_from_state(root, slug, state)
    if state.get(INCIDENT_INDEX_FIELD) != index:
        state[INCIDENT_INDEX_FIELD] = index
        save_state(root, slug, state)
    _sync_views(root, slug, state)
    return index


def open_circuit_ids(state: Mapping[str, Any]) -> list[str]:
    raw = state.get(INCIDENT_INDEX_FIELD)
    incidents = raw.get("incidents", {}) if isinstance(raw, dict) else {}
    return sorted(
        str(key)
        for key, value in incidents.items()
        if isinstance(value, dict)
        and isinstance(value.get("circuit_breaker"), dict)
        and value["circuit_breaker"].get("open") is True
    )


def _validate_occurrence(symptom: str, reproduction: list[str], blocked_operation: str) -> None:
    if not symptom.strip() or not blocked_operation.strip():
        raise MPresError("Engine incident requires an ID, symptom, and blocked operation.")
    if not reproduction or any(not str(step).strip() for step in reproduction):
        raise MPresError("Engine incident requires at least one non-empty reproduction step.")


@transactional_task_mutation
def record_engine_incident(
    root: Path,
    slug: str,
    *,
    incident_id: str,
    symptom: str,
    reproduction: list[str],
    blocked_operation: str,
    presentation_id: str | None = None,
    evidence: list[str] | None = None,
    deterministic: bool = True,
) -> dict[str, Any]:
    """Append an occurrence under a stable incident ID and open a circuit on recurrence."""
    ok, message, state = gate_status(root, slug)
    if not ok:
        raise MPresError(message)
    incident_id = safe_id(incident_id, label="engine incident ID")
    if presentation_id is not None:
        presentation_id = safe_id(presentation_id, label="presentation ID")
    _validate_occurrence(symptom, reproduction, blocked_operation)
    evidence = [str(x).strip() for x in (evidence or []) if str(x).strip()]

    index = _index_from_state(root, slug, state)
    first = incident_id not in index["incidents"]
    amendment: dict[str, Any] | None = None
    amendment_id = f"engine-{incident_id}"
    if first:
        pending = state.get("pending_policy_change_request")
        if pending and pending != amendment_id:
            raise MPresError(
                f"Cannot propose incident {incident_id!r} while policy amendment {pending!r} is pending."
            )
        if pending == amendment_id:
            amendment = read_yaml(
                task_path(root, slug) / "policy-change-requests" / f"{amendment_id}.yaml"
            )
        else:
            amendment = propose_policy_change(
                root,
                slug,
                request_id=amendment_id,
                fields=["workflow_engine_technical_fix"],
                reason=f"Workflow engine incident {incident_id}: {symptom.strip()}",
            )
        state = load_state(root, slug)
        index = _index_from_state(root, slug, state)
        _ensure_workaround_draft(root, slug, incident_id)

    threshold = _threshold(root, slug)
    incident = deepcopy(index["incidents"].get(incident_id) or {})
    now = utc_now()
    if not incident:
        incident = {
            "schema_version": INCIDENT_SCHEMA_VERSION,
            "incident_id": incident_id,
            "classification": "confirmed_or_suspected_workflow_engine_bug",
            "in_task_engine_edit_allowed": False,
            "first_recorded_utc": now,
            "last_recorded_utc": now,
            "occurrence_count": 0,
            "deterministic_occurrence_count": 0,
            "suspected_occurrence_count": 0,
            "blocked_operation": blocked_operation.strip(),
            "affected_presentations": [],
            "occurrences": [],
            "policy_amendment_request": amendment_id,
            "required_action": (
                "Do not hot-patch the workflow engine. Reconfirm the task policy and prepare an "
                "exact, reversible operational workaround. If this deterministic incident reaches "
                "the recurrence threshold, production is circuit-broken until that pre-approved "
                "workaround is applied and verified."
            ),
            "circuit_breaker": {
                "threshold": threshold,
                "open": False,
                "opened_utc": None,
                "opened_on_occurrence": None,
                "active_workaround_id": None,
            },
            "approved_workarounds": {},
            "workaround_applications": [],
            "status": "awaiting_policy_amendment",
        }
    elif str(incident.get("blocked_operation")) != blocked_operation.strip():
        raise MPresError(
            "A recurring incident ID must retain the same blocked_operation. "
            "Use a new incident ID for a different failure path."
        )

    count = int(incident.get("occurrence_count", 0)) + 1
    deterministic_count = int(incident.get("deterministic_occurrence_count", 0))
    suspected_count = int(incident.get("suspected_occurrence_count", 0))
    if deterministic:
        deterministic_count += 1
    else:
        suspected_count += 1
    occurrence = {
        "sequence": count,
        "recorded_utc": now,
        "symptom": symptom.strip(),
        "reproduction": [str(x).strip() for x in reproduction],
        "blocked_operation": blocked_operation.strip(),
        "presentation_id": presentation_id,
        "deterministic": bool(deterministic),
        "evidence": evidence,
        "task_confirmation_sequence": int(state.get("confirmation_sequence", 0)),
    }
    incident["occurrences"] = [*incident.get("occurrences", []), occurrence]
    incident["occurrence_count"] = count
    incident["deterministic_occurrence_count"] = deterministic_count
    incident["suspected_occurrence_count"] = suspected_count
    incident["last_recorded_utc"] = now
    if presentation_id:
        affected = list(incident.get("affected_presentations", []))
        if presentation_id not in affected:
            affected.append(presentation_id)
        incident["affected_presentations"] = affected

    breaker = dict(incident.get("circuit_breaker") or {})
    breaker["threshold"] = threshold
    if deterministic_count >= threshold:
        if not breaker.get("open"):
            breaker["opened_utc"] = now
            breaker["opened_on_occurrence"] = count
        breaker["open"] = True
        incident["status"] = "circuit_open"
    elif first:
        incident["status"] = "awaiting_policy_amendment"
    else:
        incident["status"] = "recurrence_recorded"
    incident["circuit_breaker"] = breaker

    index["deterministic_recurrence_threshold"] = threshold
    index["incidents"][incident_id] = incident
    state[INCIDENT_INDEX_FIELD] = index
    state["open_engine_incident_circuits"] = open_circuit_ids(state)
    save_state(root, slug, state)
    _sync_views(root, slug, state)
    append_log(
        root,
        slug,
        actor="system",
        kind="error",
        message=(
            f"Recorded workflow-engine incident {incident_id} occurrence {count}; "
            f"circuit_open={breaker.get('open')}."
        ),
        presentation_id=presentation_id,
        data={
            "incident_id": incident_id,
            "occurrence_count": count,
            "deterministic_occurrence_count": deterministic_count,
            "circuit_open": bool(breaker.get("open")),
            "threshold": threshold,
        },
    )
    result = {
        **incident,
        "path": str(_summary_path(root, slug, incident_id)),
        "incident_index_path": str(_index_path(root, slug)),
        "workaround_draft_path": str(workaround_draft_path(root, slug, incident_id)),
    }
    if amendment is not None:
        result["policy_amendment"] = amendment
    return result


def _validated_workaround(value: Any, incident_id: str) -> dict[str, Any]:
    if not isinstance(value, dict) or value.get("schema_version") != 1:
        raise MPresError("Operational workaround must be a schema-version 1 mapping.")
    if value.get("incident_id") != incident_id:
        raise MPresError("Operational workaround incident_id does not match the incident.")
    workaround_id = safe_id(str(value.get("workaround_id") or ""), label="workaround ID")
    if value.get("status") != "proposed":
        raise MPresError("Set operational workaround status to proposed before TASK presentation.")
    if len(str(value.get("title") or "").strip()) < 8:
        raise MPresError("Operational workaround title is too short.")
    for field in ("preconditions", "steps", "verification", "rollback"):
        rows = value.get(field)
        if not isinstance(rows, list) or not rows or any(not str(x).strip() for x in rows):
            raise MPresError(f"Operational workaround {field} must contain non-empty steps.")
    if value.get("reversible") is not True:
        raise MPresError("Operational workaround must be explicitly reversible.")
    if value.get("agent_may_invent_or_modify") is not False:
        raise MPresError("Agents may not invent or modify an operational workaround.")
    if value.get("arbitrary_command_execution_by_control_plane") is not False:
        raise MPresError("The control plane may not execute arbitrary workaround commands.")
    unknown = sorted(set(value.get("allowed_effects") or []) - ALLOWED_WORKAROUND_EFFECTS)
    if unknown:
        raise MPresError("Unapproved operational workaround effect(s): " + ", ".join(unknown))
    missing = sorted(
        REQUIRED_WORKAROUND_FORBIDDEN_EFFECTS - set(value.get("forbidden_effects") or [])
    )
    if missing:
        raise MPresError(
            "Operational workaround omits mandatory forbidden effect(s): " + ", ".join(missing)
        )
    if value.get("requires_TASK_reconfirmation") is not True:
        raise MPresError("Operational workaround must require exact TASK reconfirmation.")
    return {**deepcopy(value), "workaround_id": workaround_id}


@transactional_task_mutation
def approve_operational_workaround(
    root: Path, slug: str, *, incident_id: str
) -> dict[str, Any]:
    ok, message, state = gate_status(root, slug)
    if not ok:
        raise MPresError(message)
    if state.get("pending_policy_change_request"):
        raise MPresError("Confirm the pending task policy amendment before approving its workaround.")
    incident_id = safe_id(incident_id, label="engine incident ID")
    index = _index_from_state(root, slug, state)
    incident = deepcopy(index["incidents"].get(incident_id) or {})
    if not incident:
        raise MPresError(f"Unknown engine incident: {incident_id}")
    amendment_id = str(incident.get("policy_amendment_request") or f"engine-{incident_id}")
    amendment = read_yaml(
        task_path(root, slug) / "policy-change-requests" / f"{amendment_id}.yaml"
    )
    if not isinstance(amendment, dict) or amendment.get("status") != "confirmed":
        raise MPresError("The incident's task policy amendment has not been confirmed.")

    path = workaround_draft_path(root, slug, incident_id)
    plan = _validated_workaround(read_yaml(path), incident_id)
    confirmed = state.get("confirmed_operational_workarounds")
    if not isinstance(confirmed, dict) or confirmed.get(incident_id) != plan:
        raise MPresError(
            "This exact operational workaround was not included in the latest presented and "
            "user-reconfirmed task configuration. Present TASK.md again before approval."
        )

    now = utc_now()
    approved = {
        **plan,
        "status": "approved",
        "approved_utc": now,
        "approved_by": "user-via-TASK-reconfirmation",
        "approved_confirmation_sequence": int(state.get("confirmation_sequence", 0)),
    }
    workaround_id = str(approved["workaround_id"])
    approved_path = (
        _incident_dir(root, slug, incident_id)
        / "approved-workarounds"
        / f"{workaround_id}.yaml"
    )
    approved_path.parent.mkdir(parents=True, exist_ok=True)
    write_yaml_atomic(approved_path, approved)
    write_yaml_atomic(path, approved)
    workarounds = dict(incident.get("approved_workarounds") or {})
    workarounds[workaround_id] = approved
    incident["approved_workarounds"] = workarounds
    breaker = dict(incident.get("circuit_breaker") or {})
    breaker["active_workaround_id"] = workaround_id
    incident["circuit_breaker"] = breaker
    if not breaker.get("open"):
        incident["status"] = "workaround_preapproved"
    index["incidents"][incident_id] = incident
    state[INCIDENT_INDEX_FIELD] = index
    save_state(root, slug, state)
    _sync_views(root, slug, state)
    append_log(
        root,
        slug,
        actor="planner",
        kind="decision",
        message=(
            f"Registered user-preapproved operational workaround {workaround_id} "
            f"for {incident_id}."
        ),
        data={"incident_id": incident_id, "workaround_id": workaround_id},
    )
    return {**approved, "path": str(approved_path)}


@transactional_task_mutation
def apply_operational_workaround(
    root: Path,
    slug: str,
    *,
    incident_id: str,
    verification_note: str,
    evidence: list[str] | None = None,
) -> dict[str, Any]:
    """Record operator application; the control plane executes no arbitrary commands."""
    ok, message, state = gate_status(root, slug)
    if not ok:
        raise MPresError(message)
    incident_id = safe_id(incident_id, label="engine incident ID")
    if len(verification_note.strip()) < 16:
        raise MPresError("Workaround application requires a substantive verification note.")
    index = _index_from_state(root, slug, state)
    incident = deepcopy(index["incidents"].get(incident_id) or {})
    if not incident:
        raise MPresError(f"Unknown engine incident: {incident_id}")
    breaker = dict(incident.get("circuit_breaker") or {})
    if breaker.get("open") is not True:
        raise MPresError("The incident circuit is not open; no mitigation application is required.")
    workaround_id = str(breaker.get("active_workaround_id") or "")
    approved = (incident.get("approved_workarounds") or {}).get(workaround_id)
    if not isinstance(approved, dict) or approved.get("status") != "approved":
        raise MPresError(
            "No user-preapproved operational workaround is active. "
            "Reconfirm and approve an exact plan first."
        )
    now = utc_now()
    application = {
        "sequence": len(incident.get("workaround_applications", [])) + 1,
        "applied_utc": now,
        "workaround_id": workaround_id,
        "operator_attestation": verification_note.strip(),
        "evidence": [str(x).strip() for x in (evidence or []) if str(x).strip()],
        "control_plane_executed_arbitrary_commands": False,
        "verified": True,
    }
    incident["workaround_applications"] = [
        *incident.get("workaround_applications", []),
        application,
    ]
    breaker["open"] = False
    breaker["closed_utc"] = now
    breaker["closed_by_workaround_application"] = application["sequence"]
    incident["circuit_breaker"] = breaker
    incident["status"] = "mitigated_by_preapproved_workaround"
    index["incidents"][incident_id] = incident
    state[INCIDENT_INDEX_FIELD] = index
    state["open_engine_incident_circuits"] = open_circuit_ids(state)
    save_state(root, slug, state)
    _sync_views(root, slug, state)
    append_log(
        root,
        slug,
        actor="system",
        kind="decision",
        message=(
            f"Closed incident circuit {incident_id} after operator-verified "
            f"application of {workaround_id}."
        ),
        data={"incident_id": incident_id, "workaround_id": workaround_id},
    )
    return application


@transactional_task_mutation
def engine_incident_status(
    root: Path, slug: str, *, incident_id: str | None = None
) -> dict[str, Any]:
    ok, gate_message, state = gate_status(root, slug)
    index = _index_from_state(root, slug, state)
    if state.get(INCIDENT_INDEX_FIELD) != index:
        state[INCIDENT_INDEX_FIELD] = index
        state["open_engine_incident_circuits"] = open_circuit_ids(state)
        save_state(root, slug, state)
    _sync_views(root, slug, state)
    base = {
        "task_slug": slug,
        "confirmation_gate_ok": ok,
        "confirmation_gate_message": gate_message,
        "open_circuits": open_circuit_ids(state),
        "incident_index_path": str(_index_path(root, slug)),
    }
    if incident_id is None:
        return {**base, "incident_count": len(index["incidents"]), "index": index}
    incident_id = safe_id(incident_id, label="engine incident ID")
    incident = index["incidents"].get(incident_id)
    if not isinstance(incident, dict):
        raise MPresError(f"Unknown engine incident: {incident_id}")
    return {**base, "incident": incident}


def audit_engine_incidents(
    root: Path, slug: str, state: Mapping[str, Any]
) -> dict[str, list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    index = _index_from_state(root, slug, state)
    for incident_id, incident in index.get("incidents", {}).items():
        occurrences = incident.get("occurrences") if isinstance(incident, dict) else None
        if not isinstance(occurrences, list):
            errors.append(f"Engine incident {incident_id} has no occurrence list.")
            continue
        if int(incident.get("occurrence_count", -1)) != len(occurrences):
            errors.append(f"Engine incident {incident_id} occurrence_count is inconsistent.")
        deterministic = sum(
            1
            for row in occurrences
            if isinstance(row, dict) and row.get("deterministic") is True
        )
        if int(incident.get("deterministic_occurrence_count", -1)) != deterministic:
            errors.append(f"Engine incident {incident_id} deterministic count is inconsistent.")
        breaker = incident.get("circuit_breaker") or {}
        if breaker.get("open") is True:
            warnings.append(
                f"Engine incident circuit {incident_id} is open; production commands are blocked."
            )
    if index.get("incidents") and not _index_path(root, slug).is_file():
        errors.append("INCIDENT-INDEX.yaml is missing for recorded engine incidents.")
    return {"errors": errors, "warnings": warnings}
