from __future__ import annotations

from pathlib import Path

import pytest

from mpres.assignments import approve_assignment, contract_paths
from mpres.audit import audit_task
from mpres.policy import policy_audit
from mpres.production import check_assignment
from mpres.tasks import create_task, gate_status
from mpres.util import MPresError, task_sha256

from .conftest import fill_placeholders, initialize_one_deck, planner_write_and_approve


def test_only_task_md_can_be_hashed(project_root: Path) -> None:
    slug, task = initialize_one_deck(project_root)
    assert task_sha256(task / "TASK.md")
    with pytest.raises(MPresError, match="Only top-level TASK.md"):
        task_sha256(task / "EXECUTION-POLICY.yaml")
    assert gate_status(project_root, slug)[0]


def test_policy_is_one_review_high_pinned_and_text_only(project_root: Path) -> None:
    slug, task = initialize_one_deck(project_root)
    report = policy_audit(project_root, slug)
    assert report["ok"], report["errors"]
    package = (project_root / "package.json").read_text(encoding="utf-8")
    assert '"@marp-team/marp-cli": "4.5.0"' in package
    lock = (project_root / "TOOLCHAIN-LOCK.yaml").read_text(encoding="utf-8")
    assert 'version: "4.5.0"' in lock
    policy_text = (task / "EXECUTION-POLICY.yaml").read_text(encoding="utf-8")
    assert "runtime_profile_source: TASK-RUNTIME-PROFILE.yaml" in policy_text
    assert "runtime_changes_during_task: forbidden" in policy_text
    runtime_text = (task / "TASK-RUNTIME-PROFILE.yaml").read_text(encoding="utf-8")
    assert "reasoning_effort: high" in runtime_text
    assert "reasoning_effort: medium" in runtime_text
    assert "reasoning_effort: low" in runtime_text
    assert (project_root / "MODEL-POLICY.yaml").is_file()
    assert "workers_may_open_original_pdf: false" in (task / "REFERENCE-ACCESS-POLICY.yaml").read_text(encoding="utf-8")


def test_assignment_requires_planner_written_contract(project_root: Path) -> None:
    slug, task = initialize_one_deck(project_root)
    assignment = task / "workers" / "author-coordinator" / "assignments" / "p01" / "TASK-AUTHOR-COORDINATOR.md"
    fill_placeholders(assignment)
    with pytest.raises(MPresError, match="structured brief still has placeholders"):
        approve_assignment(project_root, slug, assignment)
    planner_write_and_approve(project_root, slug, assignment)
    assert check_assignment(project_root, slug, "author-coordinator", "p01")["ready"]


def test_assignment_rejects_original_pdf_and_restricted_paths(project_root: Path) -> None:
    slug, task = initialize_one_deck(project_root)
    assignment = task / "workers" / "author-coordinator" / "assignments" / "p01" / "TASK-AUTHOR-COORDINATOR.md"
    fill_placeholders(assignment)
    with assignment.open("a", encoding="utf-8") as handle:
        handle.write("\nOpen downloads/restricted-originals/book.pdf directly.\n" * 40)
    _, brief, _ = contract_paths(assignment)
    fill_placeholders(brief)
    with pytest.raises(MPresError, match="original PDF or restricted reference path"):
        approve_assignment(project_root, slug, assignment)


def test_audit_rejects_non_task_hash_and_persistent_html(project_root: Path) -> None:
    slug, task = initialize_one_deck(project_root)
    (task / "bad.sha256").write_text("x", encoding="utf-8")
    (task / "bad.html").write_text("<html></html>", encoding="utf-8")
    report = audit_task(project_root, slug)
    assert not report["ok"]
    messages = "\n".join(item["message"] for item in report["issues"])
    assert "hash" in messages.lower()
    assert "html" in messages.lower()


def test_material_policy_change_requires_reconfirmed_task(project_root: Path) -> None:
    from mpres.policy import confirm_policy_change, propose_policy_change
    from mpres.tasks import confirm_task, present_task

    slug, task = create_task(
        root=project_root,
        title="Policy test",
        slug="policy-test",
        kind="course",
        stop_mode="all",
        sessions=1,
        minutes=90,
    )
    fill_placeholders(task / "TASK.md")
    with (task / "TASK.md").open("a", encoding="utf-8") as handle:
        handle.write("\n" + "完整任务计划。" * 500)
    present_task(project_root, slug)
    confirm_task(project_root, slug)
    propose_policy_change(
        project_root,
        slug,
        request_id="review-policy",
        fields=["review_round_count"],
        reason="Material policy change for test",
    )
    with pytest.raises(MPresError, match="reconfirming TASK.md"):
        confirm_policy_change(project_root, slug, request_id="review-policy")
    with (task / "TASK.md").open("a", encoding="utf-8") as handle:
        handle.write("\nPolicy amendment explicitly incorporated into TASK.md.")
    present_task(project_root, slug)
    confirm_task(project_root, slug)
    result = confirm_policy_change(project_root, slug, request_id="review-policy")
    assert result["status"] == "confirmed"
