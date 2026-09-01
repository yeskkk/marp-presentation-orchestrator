from __future__ import annotations

from pathlib import Path
from typing import Any

from mpres.policy import propose_policy_change
from mpres.tasks import require_gate
from mpres.util import MPresError, safe_id, task_path, utc_now, write_yaml_atomic


def record_engine_incident(
    root: Path,
    slug: str,
    *,
    incident_id: str,
    symptom: str,
    reproduction: list[str],
    blocked_operation: str,
) -> dict[str, Any]:
    require_gate(root, slug)
    incident_id = safe_id(incident_id, label="engine incident ID")
    if not symptom.strip() or not blocked_operation.strip():
        raise MPresError("Engine incident requires an ID, symptom, and blocked operation.")
    if not reproduction:
        raise MPresError("Engine incident requires at least one reproduction step.")
    path = task_path(root, slug) / "engine-incidents" / f"{incident_id}.yaml"
    if path.exists():
        raise MPresError(f"Engine incident already exists: {path}")
    value = {
        "schema_version": 1,
        "incident_id": incident_id,
        "recorded_utc": utc_now(),
        "symptom": symptom.strip(),
        "reproduction": reproduction,
        "blocked_operation": blocked_operation.strip(),
        "classification": "confirmed_or_suspected_workflow_engine_bug",
        "in_task_engine_edit_allowed": False,
        "required_action": (
            "Stop the affected path, create and reconfirm a task policy amendment, and perform "
            "engine refactoring as a separate work item. Do not hot-patch the workflow engine."
        ),
        "status": "awaiting_policy_amendment",
    }
    amendment = propose_policy_change(
        root,
        slug,
        request_id=f"engine-{incident_id}",
        fields=["workflow_engine_technical_fix"],
        reason=f"Workflow engine incident {incident_id}: {symptom.strip()}",
    )
    value["policy_amendment_request"] = amendment.get("path")
    path.parent.mkdir(parents=True, exist_ok=True)
    write_yaml_atomic(path, value)
    return {**value, "path": str(path), "policy_amendment": amendment}
