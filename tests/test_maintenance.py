from __future__ import annotations

from pathlib import Path

from mpres.audit import audit_task
from mpres.maintenance import complete_maintenance, open_maintenance, publish_maintenance
from mpres.rendering import render_presentation
from mpres.state import load_state
from mpres.util import read_yaml, utc_now, write_yaml_atomic

from .conftest import planner_write_and_approve, release_zero_finding_deck


def test_targeted_corrective_maintenance_preserves_base_release_and_publishes_revision(
    project_root: Path,
) -> None:
    slug, task, base_release = release_zero_finding_deck(project_root)
    base_pdf = project_root / base_release["pdf"]
    base_pdf_bytes = base_pdf.read_bytes()

    cycle = open_maintenance(
        project_root,
        slug,
        "p01",
        mode="targeted_patch",
        reason="A published learner-facing sentence needs a precise correction without changing the instructional plan.",
        allowed_changes=["Correct the named sentence and update the corresponding self-check evidence."],
    )
    base = task / "maintenance" / "p01" / f"r{cycle['revision']:04d}"
    planner_write_and_approve(project_root, slug, base / "TASK-MAINTENANCE.md")
    source = base / "source"
    presentation = source / "presentation.md"
    text = presentation.read_text(encoding="utf-8")
    presentation.write_text(
        text.replace(
            "这一页建立本节课共同使用的对象，并解释为什么需要新的概念。",
            "这一页明确建立本节课共同使用的对象，并说明引入新概念所解决的问题。",
        ),
        encoding="utf-8",
    )
    retrospective = source / "MAINTENANCE-RETROSPECTIVE.md"
    retrospective.write_text(
        "# Maintenance retrospective\n\n"
        + "发布后的措辞虽然不构成数学错误，但对学习者不够精确。此次只修改授权句子，"
        + "保留其它内容、页序、例题和互动结构。以后 assignment 应更早检查句子的对象与作用。\n"
        + ("该经验应进入后续 author 自检。\n" * 30),
        encoding="utf-8",
    )
    checklist = source / "MAINTENANCE-CHECKLIST.yaml"
    value = read_yaml(checklist)
    value["steps"] = {key: True for key in value["steps"]}
    value["completed_utc"] = utc_now()
    value["author_declaration"] = (
        "The author changed only the planner-authorized sentence and reran every required mechanical check."
    )
    write_yaml_atomic(checklist, value)

    report = render_presentation(project_root, slug, "p01", stage="maintenance", timeout=60)
    assert report["success"] is True
    ready = complete_maintenance(project_root, slug, "p01")
    assert ready["status"] == "release_ready"
    revision = publish_maintenance(project_root, slug, "p01")

    assert base_pdf.read_bytes() == base_pdf_bytes
    revision_pdf = project_root / revision["pdf"]
    assert revision_pdf.is_file()
    assert revision_pdf != base_pdf
    current = task / "deliverables" / "p01" / "CURRENT-REVISION.json"
    assert current.is_file()
    presentation_state = load_state(project_root, slug)["presentations"][0]
    assert presentation_state["status"] == "finalized"
    assert presentation_state["maintenance"] is None
    assert presentation_state["maintenance_history"][-1]["status"] == "published"
    audit = audit_task(project_root, slug)
    assert audit["ok"], audit


def test_full_corrective_maintenance_runs_one_review_then_author_owned_release(
    project_root: Path,
) -> None:
    from mpres.maintenance import (
        aggregate_maintenance_review,
        request_maintenance_review,
        submit_maintenance_channel,
    )
    from mpres.state import REVIEW_CHANNELS

    slug, task, _ = release_zero_finding_deck(project_root, slug="full-maintenance-task")
    cycle = open_maintenance(
        project_root,
        slug,
        "p01",
        mode="full_corrective_review",
        reason="A broader pedagogical correction requires a fresh isolated full-deck review while preserving the historical release.",
        allowed_changes=["Clarify the first conceptual explanation and any directly dependent learner-facing text."],
    )
    base = task / "maintenance" / "p01" / f"r{cycle['revision']:04d}"
    planner_write_and_approve(project_root, slug, base / "TASK-MAINTENANCE.md")
    render_presentation(project_root, slug, "p01", stage="maintenance", timeout=60)
    request_maintenance_review(project_root, slug, "p01")

    for index, channel in enumerate(REVIEW_CHANNELS, start=1):
        channel_root = base / "review" / "full" / channel
        planner_write_and_approve(
            project_root, slug, channel_root / "TASK-SPECIALIST-REVIEWER.md"
        )
        report = channel_root / "report.md"
        report.write_text(
            f"# {channel} maintenance review\n\n" + "完整检查维护候选稿和指定通道。\n" * 45,
            encoding="utf-8",
        )
        findings = []
        if channel == "language":
            findings = [
                {
                    "id": "MAINT-LANG-001",
                    "channel": "language",
                    "round_opened": "full",
                    "location": {"slide_id": "p01-u01-s01"},
                    "issue": "The revised learner-facing sentence remains less explicit than intended.",
                    "learner_impact": "The learner may miss the exact instructional purpose of the page.",
                    "acceptance_criteria": "The author makes the object and instructional purpose explicit.",
                    "verification_method": "Read the revised source and author evidence.",
                }
            ]
        structured = channel_root / "findings.yaml"
        write_yaml_atomic(
            structured,
            {
                "schema_version": 1,
                "presentation_id": "p01",
                "round": "full",
                "channel": channel,
                "findings": findings,
            },
        )
        submit_maintenance_channel(
            project_root,
            slug,
            "p01",
            channel=channel,
            report_path=report,
            findings_path=structured,
        )

    aggregate = base / "review" / "full" / "aggregate.md"
    aggregate.write_text(
        "# Corrective aggregate\n\n" + "五个通道已完成，findings 交由作者自行修改。\n" * 45,
        encoding="utf-8",
    )
    aggregate_maintenance_review(
        project_root, slug, "p01", aggregate_path=aggregate
    )
    responses = base / "source" / "MAINTENANCE-AUTHOR-RESPONSES.yaml"
    response_value = read_yaml(responses)
    for row in response_value["responses"]:
        row.update(
            {
                "disposition": "accepted",
                "evidence": "The author rewrote the named sentence in presentation.md.",
                "location": "p01-u01-s01",
                "remaining_uncertainty": "none",
            }
        )
    write_yaml_atomic(responses, response_value)
    presentation = base / "source" / "presentation.md"
    presentation.write_text(
        presentation.read_text(encoding="utf-8").replace(
            "这一页建立本节课共同使用的对象，并解释为什么需要新的概念。",
            "这一页明确给出本节课共同使用的对象，并说明新概念将解决的具体问题。",
        ),
        encoding="utf-8",
    )
    retrospective = base / "source" / "MAINTENANCE-RETROSPECTIVE.md"
    retrospective.write_text(
        "# Maintenance retrospective\n\n" + "完整审核发现了一个需要作者负责修订的语言问题。\n" * 40,
        encoding="utf-8",
    )
    checklist = base / "source" / "MAINTENANCE-CHECKLIST.yaml"
    checklist_value = read_yaml(checklist)
    checklist_value["steps"] = {key: True for key in checklist_value["steps"]}
    checklist_value["completed_utc"] = utc_now()
    checklist_value["author_declaration"] = (
        "The author responded to every maintenance finding and reran all deterministic checks."
    )
    write_yaml_atomic(checklist, checklist_value)

    render_presentation(project_root, slug, "p01", stage="maintenance", timeout=60)
    complete_maintenance(project_root, slug, "p01")
    release = publish_maintenance(project_root, slug, "p01")
    assert (project_root / release["pdf"]).is_file()
    assert load_state(project_root, slug)["presentations"][0]["maintenance"] is None
