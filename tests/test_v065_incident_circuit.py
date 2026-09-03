from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from mpres.engine_incidents import (
    apply_operational_workaround,
    approve_operational_workaround,
    engine_incident_status,
    record_engine_incident,
    workaround_draft_path,
)
from mpres.policy import confirm_policy_change
from mpres.state import load_state
from mpres.tasks import confirm_task, present_task, require_gate
from mpres.util import MPresError, read_yaml, write_yaml_atomic
from .conftest import initialize_one_deck


def first(root: Path, slug: str):
    slug, task = initialize_one_deck(root, slug=slug)
    result = record_engine_incident(
        root, slug, incident_id="ENGINE-006",
        symptom="Revision workspace copy retains read-only permissions.",
        reproduction=["Freeze p01.", "Aggregate five review receipts."],
        blocked_operation="review aggregation", presentation_id="p01",
        evidence=["permission denied while preparing revision workspace"],
    )
    return slug, task, result


def approve(root: Path, slug: str, task: Path):
    path = workaround_draft_path(root, slug, "ENGINE-006")
    value = read_yaml(path)
    value.update({
        "status": "proposed",
        "title": "Prepare copied revision workspace before aggregate commit",
        "preconditions": ["Five immutable review receipts are complete."],
        "steps": ["Build in a temporary staging directory.", "Restore owner write permission only on the copied workspace."],
        "verification": ["Open the copied source for write and close it unchanged."],
        "rollback": ["Delete the staged copy and leave frozen source untouched."],
        "allowed_effects": ["use_temporary_staging_path", "restore_permissions_on_copied_workspace"],
    })
    write_yaml_atomic(path, value)
    with (task / "TASK.md").open("a", encoding="utf-8") as handle:
        handle.write("\n\nPolicy amendment: the exact ENGINE-006 reversible workaround accompanies this TASK confirmation.")
    present_task(root, slug)
    confirm_task(root, slug)
    confirm_policy_change(root, slug, request_id="engine-ENGINE-006")
    return approve_operational_workaround(root, slug, incident_id="ENGINE-006")


def recurrence(root: Path, slug: str, pid: str = "p02"):
    return record_engine_incident(
        root, slug, incident_id="ENGINE-006",
        symptom=f"The same copied revision workspace is read-only for {pid}.",
        reproduction=[f"Freeze {pid}.", "Aggregate five review receipts."],
        blocked_operation="review aggregation", presentation_id=pid,
    )


def test_first_occurrence_keeps_amendment_and_creates_draft(project_root: Path):
    slug, task, result = first(project_root, "v065-first")
    assert result["occurrence_count"] == 1
    assert result["status"] == "awaiting_policy_amendment"
    assert result["circuit_breaker"]["open"] is False
    assert result["policy_amendment"]["fields_to_change"] == ["workflow_engine_technical_fix"]
    assert workaround_draft_path(project_root, slug, "ENGINE-006").is_file()
    assert (task / "engine-incidents" / "INCIDENT-INDEX.yaml").is_file()
    assert load_state(project_root, slug)["pending_policy_change_request"] == "engine-ENGINE-006"


def test_exact_reconfirmed_plan_can_be_preapproved(project_root: Path):
    slug, task, _ = first(project_root, "v065-approve")
    result = approve(project_root, slug, task)
    assert result["status"] == "approved"
    status = engine_incident_status(project_root, slug, incident_id="ENGINE-006")
    assert status["incident"]["circuit_breaker"]["active_workaround_id"] == result["workaround_id"]


def test_edit_after_presentation_is_rejected(project_root: Path):
    slug, task, _ = first(project_root, "v065-tamper")
    path = workaround_draft_path(project_root, slug, "ENGINE-006")
    value = read_yaml(path)
    value.update({"status":"proposed","title":"Use one reversible staging step","preconditions":["receipts complete"],"steps":["use staging"],"verification":["verify output"],"rollback":["delete staging"],"allowed_effects":["use_temporary_staging_path"]})
    write_yaml_atomic(path, value)
    with (task / "TASK.md").open("a", encoding="utf-8") as handle:
        handle.write("\n\nPolicy amendment confirms one exact reversible staging workaround.")
    present_task(project_root, slug)
    value["steps"].append("post-presentation change")
    write_yaml_atomic(path, value)
    with pytest.raises(MPresError, match="changed after TASK.md was presented"):
        confirm_task(project_root, slug)


def test_second_deterministic_occurrence_opens_gate_wide_circuit(project_root: Path):
    slug, task, _ = first(project_root, "v065-circuit")
    approve(project_root, slug, task)
    second = recurrence(project_root, slug)
    assert second["occurrence_count"] == 2 and second["circuit_breaker"]["open"] is True
    with pytest.raises(MPresError, match="circuit breaker is open"):
        require_gate(project_root, slug)
    status = engine_incident_status(project_root, slug)
    assert status["open_circuits"] == ["ENGINE-006"]
    assert status["index"]["incidents"]["ENGINE-006"]["affected_presentations"] == ["p01", "p02"]


def test_operator_verified_application_closes_circuit(project_root: Path):
    slug, task, _ = first(project_root, "v065-apply")
    approve(project_root, slug, task)
    recurrence(project_root, slug)
    result = apply_operational_workaround(
        project_root, slug, incident_id="ENGINE-006",
        verification_note="Operator executed the exact confirmed plan and verified a writable copied source.",
        evidence=["writable-open check passed; frozen source remained read-only"],
    )
    assert result["control_plane_executed_arbitrary_commands"] is False
    assert require_gate(project_root, slug)["task_slug"] == slug
    assert engine_incident_status(project_root, slug)["open_circuits"] == []


def test_suspected_occurrence_does_not_count_toward_threshold(project_root: Path):
    slug, _, _ = first(project_root, "v065-suspected")
    result = record_engine_incident(
        project_root, slug, incident_id="ENGINE-006",
        symptom="A similar warning is not yet deterministic.", reproduction=["Inspect p02 logs."],
        blocked_operation="review aggregation", presentation_id="p02", deterministic=False,
    )
    assert result["occurrence_count"] == 2
    assert result["deterministic_occurrence_count"] == 1
    assert result["suspected_occurrence_count"] == 1
    assert result["circuit_breaker"]["open"] is False


def test_concurrent_recurrences_preserve_every_occurrence(project_root: Path):
    slug, _, _ = first(project_root, "v065-concurrent")
    def one(i: int):
        recurrence(project_root, slug, f"p{i+2:02d}")
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(one, range(4)))
    incident = engine_incident_status(project_root, slug, incident_id="ENGINE-006")["incident"]
    assert incident["occurrence_count"] == len(incident["occurrences"]) == 5
    assert incident["deterministic_occurrence_count"] == 5
    assert incident["circuit_breaker"]["open"] is True


def test_policy_amendment_can_be_proposed_while_circuit_is_open(project_root: Path):
    from mpres.policy import propose_policy_change

    slug, task, _ = first(project_root, "v065-late-workaround")
    with (task / "TASK.md").open("a", encoding="utf-8") as handle:
        handle.write("\n\nPolicy amendment: stop the affected path; no hot patch is authorized.")
    present_task(project_root, slug)
    confirm_task(project_root, slug)
    confirm_policy_change(project_root, slug, request_id="engine-ENGINE-006")
    recurrence(project_root, slug)
    with pytest.raises(MPresError, match="circuit breaker is open"):
        require_gate(project_root, slug)
    proposal = propose_policy_change(
        project_root, slug, request_id="engine-ENGINE-006-workaround",
        fields=["workflow_engine_technical_fix"],
        reason="Add an exact reversible operational workaround after the recurrence circuit opened.",
    )
    assert proposal["status"] == "proposed"
