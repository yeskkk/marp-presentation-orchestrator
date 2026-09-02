from __future__ import annotations

from pathlib import Path

import yaml

from mpres.audit import audit_task
from mpres.control_jobs import release_workspace, review_aggregation_root
from mpres.rendering import render_presentation
from mpres.review import (
    aggregate_round,
    complete_author_revision,
    finalize_release,
    record_author_responses,
    request_review,
    submit_channel_review,
)
from mpres.state import REVIEW_CHANNELS, load_state
from mpres.util import utc_now

from .conftest import (
    approve_revision_author,
    initialize_one_deck,
    install_fake_marp,
    planner_write_and_approve,
    prepare_author_source,
)


def finding(channel: str, number: int) -> dict[str, object]:
    return {
        "id": f"{channel.upper()}-{number:03d}",
        "channel": channel,
        "round_opened": "full",
        "location": {"slide_id": "p01-u01-q1"},
        "issue": "A concrete learner-facing issue was found in the frozen deck.",
        "learner_impact": "The learner could misunderstand the current object or condition.",
        "acceptance_criteria": "The author revises the named location and records evidence.",
        "verification_method": "Read the author response and revised source.",
    }


def test_single_review_author_owned_revision_and_direct_release(project_root: Path) -> None:
    slug, task = initialize_one_deck(project_root)
    install_fake_marp(project_root, version="4.5.0")
    source = prepare_author_source(project_root, slug, task)
    assert render_presentation(project_root, slug, "p01", stage="author", timeout=60)["success"]
    assert request_review(project_root, slug, "p01")["round"] == "full"

    for i, channel in enumerate(REVIEW_CHANNELS, start=1):
        channel_root = task / "workers" / "specialist-reviewers" / "p01" / "full" / channel
        assignment_path = channel_root / "TASK-SPECIALIST-REVIEWER.md"
        from mpres.assignments import assignment_contract_status
        if not assignment_contract_status(assignment_path).get("approved"):
            planner_write_and_approve(project_root, slug, assignment_path)
        report = channel_root / "report.md"
        report.write_text(
            f"# {channel} review\n\n" + "完整范围、证据、finding 与结论。\n" * 45,
            encoding="utf-8",
        )
        structured = channel_root / "findings.yaml"
        structured.write_text(
            yaml.safe_dump(
                {
                    "schema_version": 3,
                    "presentation_id": "p01",
                    "round": "full",
                    "channel": channel,
                    "findings": [finding(channel, i)],
                },
                allow_unicode=True,
                sort_keys=False,
            ),
            encoding="utf-8",
        )
        submit_channel_review(
            project_root,
            slug,
            "p01",
            round_name="full",
            channel=channel,
            report_path=report,
            findings_path=structured,
        )

    aggregate = task / "reviews" / "p01" / "full" / "aggregate.md"
    aggregate.write_text(
        "# Review aggregate\n\n" + "五个通道均已完成，findings 交给作者自行处理。\n" * 45,
        encoding="utf-8",
    )
    decision = aggregate_round(
        project_root, slug, "p01", round_name="full", aggregate_path=aggregate
    )
    assert decision["aggregation_job_receipt"] == str(
        (review_aggregation_root(project_root, slug, "p01") / "receipt.json").relative_to(
            project_root
        )
    )
    assert decision["post_revision_review"] == "none"
    assert (task / "reviews" / "p01" / "REVISION-ROUTING.yaml").is_file()
    revision_queue = (
        task
        / "workers"
        / "deck-revision-author"
        / "drafts"
        / "p01"
        / "source"
        / "REVISION-FINDINGS.yaml"
    )
    assert revision_queue.is_file()
    queue_value = yaml.safe_load(revision_queue.read_text(encoding="utf-8"))
    assert len(queue_value["finding_ids"]) == 5
    assert queue_value["original_lesson_authors_reopened"] is False
    assert load_state(project_root, slug)["presentations"][0]["status"] == "author_revision"

    source = approve_revision_author(project_root, slug, task)
    responses_path = source / "AUTHOR-RESPONSES.yaml"
    responses = yaml.safe_load(responses_path.read_text(encoding="utf-8"))
    for row in responses["responses"]:
        row.update(
            {
                "disposition": "accepted",
                "evidence": "The author changed the named slide and recorded the exact edit.",
                "location": "presentation.md / p01-u01-q1",
                "remaining_uncertainty": "none",
            }
        )
    responses_path.write_text(
        yaml.safe_dump(responses, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )
    assert len(
        record_author_responses(project_root, slug, "p01", response_file=responses_path)[
            "responses_recorded"
        ]
    ) == 5

    revision = source / "AUTHOR-REVISION.md"
    revision.write_text(
        "# Author revision\n\n" + "已逐项阅读 finding、修改内容并重跑全部机械检查。\n" * 40,
        encoding="utf-8",
    )
    checklist_path = source / "AUTHOR-MODIFICATION-CHECKLIST.yaml"
    checklist = yaml.safe_load(checklist_path.read_text(encoding="utf-8"))
    checklist["completed_utc"] = utc_now()
    checklist["steps"] = {key: True for key in checklist["steps"]}
    checklist["author_declaration"] = (
        "The author completed the full modification workflow and accepts responsibility for it."
    )
    checklist_path.write_text(
        yaml.safe_dump(checklist, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )
    (source / "SELF-CHECK.md").write_text(
        "# Revised self-check\n\n" + "已重新执行 source lint、asset validation 和 PDF inspection。\n" * 40,
        encoding="utf-8",
    )
    assert render_presentation(project_root, slug, "p01", stage="author", timeout=60)["success"]
    ready = complete_author_revision(
        project_root, slug, "p01", checklist_file=checklist_path
    )
    assert ready["finding_resolution_checked"] is False
    assert ready["post_revision_reviewer_verification"] is False
    release_job = release_workspace(project_root, slug, "p01") / "job.yaml"
    assert release_job.is_file()
    assert yaml.safe_load(release_job.read_text(encoding="utf-8"))["model_runtime"] is None
    assert not (task / "workers" / "release-coordinator").exists()

    assert render_presentation(project_root, slug, "p01", stage="release", timeout=60)["success"]
    release = finalize_release(project_root, slug, "p01")
    assert (project_root / release["release_job_receipt"]).is_file()
    assert (project_root / release["pdf"]).is_file()
    assert load_state(project_root, slug)["phase"] == "complete"
    audit = audit_task(project_root, slug)
    assert audit["ok"], audit


def test_finding_resolution_fields_are_rejected(project_root: Path) -> None:
    """Findings are historical statements, not objects with a resolution lifecycle."""

    import pytest

    from mpres.review import submit_channel_review
    from mpres.util import MPresError

    slug, task = initialize_one_deck(project_root)
    install_fake_marp(project_root, version="4.5.0")
    prepare_author_source(project_root, slug, task)
    assert render_presentation(project_root, slug, "p01", stage="author", timeout=60)[
        "success"
    ]
    request_review(project_root, slug, "p01")

    channel = "language"
    channel_root = task / "workers" / "specialist-reviewers" / "p01" / "full" / channel
    planner_write_and_approve(
        project_root, slug, channel_root / "TASK-SPECIALIST-REVIEWER.md"
    )
    report = channel_root / "report.md"
    report.write_text(
        "# Language review\n\n" + "完整范围与证据。\n" * 45,
        encoding="utf-8",
    )
    row = finding(channel, 1)
    row["resolved"] = False
    findings_path = channel_root / "findings.yaml"
    findings_path.write_text(
        yaml.safe_dump(
            {
                "schema_version": 3,
                "presentation_id": "p01",
                "round": "full",
                "channel": channel,
                "findings": [row],
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    with pytest.raises(MPresError, match="obsolete resolution field"):
        submit_channel_review(
            project_root,
            slug,
            "p01",
            round_name="full",
            channel=channel,
            report_path=report,
            findings_path=findings_path,
        )


def test_review_resubmission_is_narrow_and_aggregation_is_atomic(project_root: Path) -> None:
    import pytest

    from mpres.util import MPresError, read_yaml, write_yaml_atomic

    slug, task = initialize_one_deck(project_root, slug="atomic-review-task")
    install_fake_marp(project_root, version="4.5.0")
    prepare_author_source(project_root, slug, task)
    render_presentation(project_root, slug, "p01", stage="author", timeout=60)
    request_review(project_root, slug, "p01")

    def submit(channel: str, row: dict[str, object]) -> dict[str, object]:
        channel_root = task / "workers" / "specialist-reviewers" / "p01" / "full" / channel
        assignment_path = channel_root / "TASK-SPECIALIST-REVIEWER.md"
        from mpres.assignments import assignment_contract_status
        if not assignment_contract_status(assignment_path).get("approved"):
            planner_write_and_approve(project_root, slug, assignment_path)
        report = channel_root / "report.md"
        report.write_text(
            f"# {channel} review\n\n" + "完整范围、证据和 finding 说明。\n" * 45,
            encoding="utf-8",
        )
        structured = channel_root / "findings.yaml"
        write_yaml_atomic(
            structured,
            {
                "schema_version": 3,
                "presentation_id": "p01",
                "round": "full",
                "channel": channel,
                "findings": [row],
            },
        )
        return submit_channel_review(
            project_root,
            slug,
            "p01",
            round_name="full",
            channel=channel,
            report_path=report,
            findings_path=structured,
        )

    language = finding("language", 1)
    first = submit("language", language)
    assert first["attempt"] == 1
    registry = read_yaml(task / "reviews" / "p01" / "findings.yaml")
    assert registry["findings"] == []

    corrected = dict(language)
    corrected["location"] = {"slide_id": "p01-u01-q2"}
    corrected["evidence_path"] = "presentation.md#p01-u01-q2"
    corrected["reviewer_note"] = "The original issue was correct; only the slide location was corrected."
    second = submit("language", corrected)
    assert second["attempt"] == 2
    receipt = task / "workers" / "specialist-reviewers" / "p01" / "full" / "language" / "submissions" / "attempt-0002" / "receipt.json"
    assert receipt.is_file()

    changed_issue = dict(corrected)
    changed_issue["issue"] = "A different substantive issue must not replace the original finding."
    with pytest.raises(MPresError, match="changes substantive finding fields"):
        submit("language", changed_issue)

    for index, channel in enumerate(REVIEW_CHANNELS[1:], start=2):
        row = finding(channel, index)
        if channel == "domain_accuracy":
            row["id"] = language["id"]  # Cross-channel duplicate, detected only at atomic aggregate.
        submit(channel, row)

    aggregate = task / "reviews" / "p01" / "full" / "aggregate.md"
    aggregate.write_text(
        "# Aggregate\n\n" + "所有当前 handoff 均已到达，准备原子提交。\n" * 45,
        encoding="utf-8",
    )
    with pytest.raises(MPresError, match="duplicated across channels"):
        aggregate_round(project_root, slug, "p01", round_name="full", aggregate_path=aggregate)
    registry_after = read_yaml(task / "reviews" / "p01" / "findings.yaml")
    assert registry_after["findings"] == []
