from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from mpres.assignments import (
    approve_assignment,
    approve_batch_plan,
    assignment_contract_files,
    assignment_contract_status,
    batch_expansion_state_path,
    batch_plan_path,
    contract_paths,
    ensure_assignment_taskbook,
    revoke_assignment,
    revoke_batch_plan,
    scaffold_assignment_contract,
)
from mpres.control_jobs import prepare_release_job, prepare_review_aggregation_job
from mpres.diagnostics import open_diagnostic_case
from mpres.maintenance import open_maintenance
from mpres.production import prepare_author_coordinator_workspace, prepare_unit_workspace
from mpres.rendering import render_presentation
from mpres.review import request_review
from mpres.util import MPresError, read_yaml, write_yaml_atomic

from .conftest import (
    approve_batch_and_queue_unit,
    initialize_one_deck,
    planner_write_and_approve,
    prepare_author_source,
    release_zero_finding_deck,
)


def _bytes(paths: tuple[Path, ...]) -> dict[Path, bytes]:
    return {path: path.read_bytes() for path in paths}


def test_author_workspace_repair_preserves_approved_contract_and_author_edits(
    project_root: Path,
) -> None:
    slug, task = initialize_one_deck(project_root)
    assignment = (
        task
        / "workers"
        / "author-coordinator"
        / "assignments"
        / "p01"
        / "TASK-AUTHOR-COORDINATOR.md"
    )
    planner_write_and_approve(project_root, slug, assignment)
    contract_before = _bytes(assignment_contract_files(assignment))

    source = task / "workers" / "author-coordinator" / "drafts" / "p01" / "source"
    header = source / "HEADER.md"
    header.write_text(header.read_text(encoding="utf-8") + "\nPlanner-preserved author edit.\n", encoding="utf-8")
    header_before = header.read_bytes()
    theme = source / "theme.css"
    theme.unlink()

    result = prepare_author_coordinator_workspace(project_root, slug, "p01")

    assert theme.is_file()
    assert header.read_bytes() == header_before
    assert _bytes(assignment_contract_files(assignment)) == contract_before
    assert result["repaired_or_created"]
    assert assignment_contract_status(assignment)["write_protected"] is True


def test_repeated_approval_is_a_byte_preserving_noop_and_cannot_be_reattributed(
    project_root: Path,
) -> None:
    slug, task = initialize_one_deck(project_root)
    assignment = (
        task
        / "workers"
        / "author-coordinator"
        / "assignments"
        / "p01"
        / "TASK-AUTHOR-COORDINATOR.md"
    )
    planner_write_and_approve(project_root, slug, assignment)
    before = _bytes(assignment_contract_files(assignment))
    decision_before = read_yaml(contract_paths(assignment)[2])

    repeated = approve_assignment(
        project_root,
        slug,
        assignment,
        notes="a main or delegated planner wrote this assignment",
        planner_actor="delegated-planner:test",
    )
    assert repeated["already_approved"] is True
    assert repeated["approved_utc"] == decision_before["decided_utc"]
    assert _bytes(assignment_contract_files(assignment)) == before

    with pytest.raises(MPresError, match="already approved"):
        approve_assignment(
            project_root,
            slug,
            assignment,
            planner_actor="delegated-planner:other",
        )
    with pytest.raises(MPresError, match="different notes"):
        approve_assignment(
            project_root,
            slug,
            assignment,
            notes="different approval metadata",
            planner_actor="delegated-planner:test",
        )
    assert _bytes(assignment_contract_files(assignment)) == before


def test_explicit_revoke_is_required_before_revision_and_reapproval_tracks_sequence(
    project_root: Path,
) -> None:
    slug, task = initialize_one_deck(project_root)
    assignment = (
        task
        / "workers"
        / "author-coordinator"
        / "assignments"
        / "p01"
        / "TASK-AUTHOR-COORDINATOR.md"
    )
    planner_write_and_approve(project_root, slug, assignment)
    first = read_yaml(contract_paths(assignment)[2])

    revoked = revoke_assignment(
        project_root,
        slug,
        assignment,
        reason="The user changed the exact acceptance boundary before this worker starts.",
    )
    assert revoked["already_revoked"] is False
    assert assignment.stat().st_mode & 0o200

    assignment.write_text(
        assignment.read_text(encoding="utf-8")
        + "\n\nPlanner revision after explicit revoke: use the updated acceptance boundary.\n",
        encoding="utf-8",
    )
    brief_path = contract_paths(assignment)[1]
    brief = read_yaml(brief_path)
    brief["acceptance_criteria"].append("Apply the user-confirmed revised acceptance boundary.")
    write_yaml_atomic(brief_path, brief)

    second = approve_assignment(
        project_root,
        slug,
        assignment,
        notes="reapproved after explicit revoke",
        planner_actor="delegated-planner:test",
    )
    decision = read_yaml(contract_paths(assignment)[2])
    assert second["approval_sequence"] == 2
    assert decision["first_approved_utc"] == first["first_approved_utc"]
    assert decision["approval_sequence"] == 2
    assert decision["immutable_after_approval"] is True

    preserved = _bytes(assignment_contract_files(assignment))
    prepare_author_coordinator_workspace(project_root, slug, "p01")
    assert _bytes(assignment_contract_files(assignment)) == preserved


def test_partial_pending_contract_fills_only_missing_files_and_rejects_semantic_conflict(
    project_root: Path,
) -> None:
    slug, task = initialize_one_deck(project_root)
    assignment = task / "workers" / "synthetic" / "TASK-SYNTHETIC.md"
    ensure_assignment_taskbook(assignment, "# Synthetic assignment\n\n" + "Exact planner scope.\n" * 80)
    kwargs = {
        "assignment_id": "p01:synthetic",
        "role": "author-coordinator",
        "presentation_id": "p01",
        "requested_by": "test-scheduler",
        "need": "Create one exact synthetic assignment for an interrupted-scaffold recovery test.",
    }
    scaffold_assignment_contract(project_root, assignment, **kwargs)
    request, brief, decision = contract_paths(assignment)
    request_before = request.read_bytes()
    decision_before = decision.read_bytes()
    brief.unlink()

    repaired = scaffold_assignment_contract(project_root, assignment, **kwargs)
    assert repaired["changed"] is True
    assert brief.is_file()
    assert request.read_bytes() == request_before
    assert decision.read_bytes() == decision_before

    before = _bytes(assignment_contract_files(assignment))
    with pytest.raises(MPresError, match="different scaffold semantics"):
        scaffold_assignment_contract(
            project_root,
            assignment,
            **{**kwargs, "need": "A conflicting need must never overwrite the original request."},
        )
    assert _bytes(assignment_contract_files(assignment)) == before



def test_approved_incomplete_contract_fails_closed_instead_of_regenerating(
    project_root: Path,
) -> None:
    slug, task = initialize_one_deck(project_root)
    assignment = (
        task
        / "workers"
        / "author-coordinator"
        / "assignments"
        / "p01"
        / "TASK-AUTHOR-COORDINATOR.md"
    )
    planner_write_and_approve(project_root, slug, assignment)
    request, brief, decision = contract_paths(assignment)
    brief.chmod(0o644)
    brief.unlink()

    before = {path: path.read_bytes() for path in (assignment, request, decision)}
    with pytest.raises(MPresError, match="Approved assignment contract is incomplete"):
        prepare_author_coordinator_workspace(project_root, slug, "p01")
    assert {path: path.read_bytes() for path in (assignment, request, decision)} == before
    assert not brief.exists()


def test_conflicting_concurrent_scaffold_preserves_one_request_and_rejects_the_other(
    tmp_path: Path,
) -> None:
    root = tmp_path
    assignment = root / "tasks" / "race" / "workers" / "author" / "TASK.md"
    ensure_assignment_taskbook(assignment, "# Concurrent assignment\n\n" + "Exact scope.\n" * 80)

    def create(need: str) -> tuple[str, str]:
        try:
            scaffold_assignment_contract(
                root,
                assignment,
                assignment_id="p01:semantic-race",
                role="author-coordinator",
                presentation_id="p01",
                requested_by="race-test",
                need=need,
            )
            return "ok", need
        except MPresError:
            return "rejected", need

    needs = [
        "First exact semantic request for the concurrency race.",
        "Second conflicting semantic request for the concurrency race.",
    ] * 12
    with ThreadPoolExecutor(max_workers=12) as pool:
        results = list(pool.map(create, needs))

    published = read_yaml(contract_paths(assignment)[0])["need"]
    assert published in set(needs)
    assert any(status == "rejected" for status, _ in results)
    assert all(
        status == "rejected" or need == published
        for status, need in results
    )
    status = assignment_contract_status(assignment)
    assert status["complete"] is True
    assert status["identity_consistent"] is True

def test_batch_expansion_and_lesson_workspace_are_idempotent_without_mutating_approved_plan(
    project_root: Path,
) -> None:
    slug, task = initialize_one_deck(project_root)
    lesson = approve_batch_and_queue_unit(project_root, slug, task)
    plan = batch_plan_path(project_root, slug)
    plan_before = plan.read_bytes()
    contract_before = _bytes(assignment_contract_files(lesson))

    source = lesson.parent / "source"
    section = source / "section.md"
    section.write_text(section.read_text(encoding="utf-8") + "\nAuthor draft survives recovery.\n", encoding="utf-8")
    section_before = section.read_bytes()
    missing = source / "SELF-CHECK.md"
    missing.unlink()

    repaired = prepare_unit_workspace(project_root, slug, "p01", "u01")
    complete = prepare_unit_workspace(project_root, slug, "p01", "u01")

    assert missing.is_file()
    assert section.read_bytes() == section_before
    assert _bytes(assignment_contract_files(lesson)) == contract_before
    assert plan.read_bytes() == plan_before
    expansion = read_yaml(batch_expansion_state_path(project_root, slug))
    assert expansion["expanded_assignments"] == ["p01/u01"]
    assert repaired["repaired_or_created"]
    assert complete["already_materialized"] is True

    batch_before = plan.read_bytes()
    repeated = approve_batch_plan(
        project_root,
        slug,
        planner_actor="delegated-planner:test",
        notes="test planner approved one batch plan for deterministic expansion",
    )
    assert repeated["already_approved"] is True
    assert plan.read_bytes() == batch_before

    first_approval = read_yaml(plan)
    reopened = revoke_batch_plan(
        project_root,
        slug,
        reason="The planner must revise batch metadata through an explicit lifecycle transition.",
    )
    assert reopened["already_revoked"] is False
    repeated_reopen = revoke_batch_plan(
        project_root,
        slug,
        reason="The planner must revise batch metadata through an explicit lifecycle transition.",
    )
    assert repeated_reopen["already_revoked"] is True
    reapproved = approve_batch_plan(
        project_root,
        slug,
        planner_actor="delegated-planner:test",
        notes="reapproved after explicit batch-plan revoke",
    )
    second_approval = read_yaml(plan)
    assert reapproved["approval_sequence"] == 2
    assert second_approval["first_approved_utc"] == first_approval["first_approved_utc"]


def test_review_request_retry_preserves_approved_reviewer_contract_and_repairs_missing_output(
    project_root: Path,
) -> None:
    slug, task = initialize_one_deck(project_root)
    prepare_author_source(project_root, slug, task)
    render_presentation(project_root, slug, "p01", stage="author", timeout=60)
    first = request_review(project_root, slug, "p01", changed_areas=["intro"])
    assert first["already_requested"] is False

    language = (
        task
        / "workers"
        / "specialist-reviewers"
        / "p01"
        / "full"
        / "language"
    )
    planner_write_and_approve(
        project_root, slug, language / "TASK-SPECIALIST-REVIEWER.md"
    )
    contract_before = _bytes(
        assignment_contract_files(language / "TASK-SPECIALIST-REVIEWER.md")
    )
    report = language / "report.md"
    report.write_text("# Preserved reviewer draft\n\n" + "Evidence.\n" * 40, encoding="utf-8")
    report_before = report.read_bytes()

    layout_findings = (
        task
        / "workers"
        / "specialist-reviewers"
        / "p01"
        / "full"
        / "layout"
        / "findings.yaml"
    )
    layout_findings.unlink()
    second = request_review(project_root, slug, "p01", changed_areas=["intro"])

    assert second["already_requested"] is True
    assert layout_findings.is_file()
    assert report.read_bytes() == report_before
    assert _bytes(assignment_contract_files(language / "TASK-SPECIALIST-REVIEWER.md")) == contract_before


def test_diagnostic_reopen_with_explicit_case_id_preserves_approved_contract_and_response(
    project_root: Path,
) -> None:
    slug, task = initialize_one_deck(project_root)
    prepare_author_source(project_root, slug, task)
    report = "The introductory sentence names the object but does not explain the learner problem it resolves."
    first = open_diagnostic_case(
        project_root,
        slug,
        "p01",
        user_report=report,
        slide_ids=["p01-u01-s01"],
        neighbor_radius=1,
        case_id="d0100",
    )
    base = task / "diagnostics" / "p01" / first["case_id"]
    assignment = base / "TASK-DIAGNOSTIC-REVIEWER.md"
    planner_write_and_approve(project_root, slug, assignment)
    contract_before = _bytes(assignment_contract_files(assignment))
    result = base / "response" / "DIAGNOSTIC-RESULT.yaml"
    result.write_text(result.read_text(encoding="utf-8") + "\n# diagnostic draft preserved\n", encoding="utf-8")
    result_before = result.read_bytes()

    second = open_diagnostic_case(
        project_root,
        slug,
        "p01",
        user_report=report,
        slide_ids=["p01-u01-s01"],
        neighbor_radius=1,
        case_id="d0100",
    )
    assert second["already_open"] is True
    assert result.read_bytes() == result_before
    assert _bytes(assignment_contract_files(assignment)) == contract_before


def test_maintenance_reopen_preserves_approved_contract_and_repairs_missing_file(
    project_root: Path,
) -> None:
    slug, task, _ = release_zero_finding_deck(project_root, slug="v067-maintenance")
    reason = "A learner-facing sentence needs a bounded wording correction after publication."
    allowed = ["Correct the named sentence and update its self-check evidence."]
    first = open_maintenance(
        project_root,
        slug,
        "p01",
        mode="targeted_patch",
        reason=reason,
        allowed_changes=allowed,
    )
    base = task / "maintenance" / "p01" / f"r{first['revision']:04d}"
    assignment = base / "TASK-MAINTENANCE.md"
    planner_write_and_approve(project_root, slug, assignment)
    contract_before = _bytes(assignment_contract_files(assignment))
    missing = base / "source" / "MAINTENANCE-RETROSPECTIVE.md"
    missing.unlink()

    second = open_maintenance(
        project_root,
        slug,
        "p01",
        mode="targeted_patch",
        reason=reason,
        allowed_changes=allowed,
    )
    assert second["already_open"] is True
    assert second["revision"] == first["revision"]
    assert missing.is_file()
    assert _bytes(assignment_contract_files(assignment)) == contract_before

    with pytest.raises(MPresError, match="different boundaries"):
        open_maintenance(
            project_root,
            slug,
            "p01",
            mode="targeted_patch",
            reason="A materially different correction request must not reuse the existing workspace.",
            allowed_changes=allowed,
        )


def test_concurrent_same_identity_scaffold_publishes_complete_contract_once(
    tmp_path: Path,
) -> None:
    root = tmp_path
    assignment = root / "tasks" / "race" / "workers" / "author" / "TASK.md"
    ensure_assignment_taskbook(assignment, "# Concurrent assignment\n\n" + "Exact scope.\n" * 80)

    def create(_: int) -> dict:
        return scaffold_assignment_contract(
            root,
            assignment,
            assignment_id="p01:race",
            role="author-coordinator",
            presentation_id="p01",
            requested_by="race-test",
            need="Publish one complete contract exactly once under concurrent recovery calls.",
        )

    with ThreadPoolExecutor(max_workers=12) as pool:
        results = list(pool.map(create, range(48)))

    assert sum(bool(row["changed"]) for row in results) >= 1
    assert all(path.is_file() for path in assignment_contract_files(assignment))
    status = assignment_contract_status(assignment)
    assert status["complete"] is True
    assert status["identity_consistent"] is True


def test_mechanical_job_scaffolds_preserve_existing_job_records(project_root: Path) -> None:
    slug, _ = initialize_one_deck(project_root)
    review_job = prepare_review_aggregation_job(project_root, slug, "p01")
    release_job = prepare_release_job(project_root, slug, "p01")
    review_before = review_job.read_bytes()
    release_before = release_job.read_bytes()

    assert prepare_review_aggregation_job(project_root, slug, "p01") == review_job
    assert prepare_release_job(project_root, slug, "p01") == release_job
    assert review_job.read_bytes() == review_before
    assert release_job.read_bytes() == release_before
