from __future__ import annotations

from pathlib import Path

import yaml

from mpres.audit import audit_task
from mpres.rendering import render_presentation
from mpres.review import (
    aggregate_round,
    approve_release_closure,
    finalize_release,
    record_author_responses,
    request_review,
    submit_channel_review,
)
from mpres.state import REVIEW_CHANNELS, load_state

from .conftest import complete_author_source, fill_placeholders, finalize_canonical_source, initialize_one_deck, install_fake_marp


def _submit_round(root: Path, slug: str, task: Path, round_name: str, unresolved: bool) -> None:
    for channel in REVIEW_CHANNELS:
        base = task / "workers" / "specialist-reviewers" / "p01" / round_name / channel
        report = base / "report.md"
        fill_placeholders(report)
        report.write_text(report.read_text(encoding="utf-8") + "\n" + "完整审核证据。" * 50, encoding="utf-8")
        findings = []
        if channel == "language":
            findings = [{
                "id": "LANG-001",
                "channel": "language",
                "round_opened": "initial",
                "kind": "ordinary",
                "location": {"slide_id": "p01-u01-s01"},
                "issue": "标题主语不够明确",
                "learner_impact": "听众可能无法判断当前对象",
                "acceptance_criteria": "标题明确写出对象",
                "verification_method": "检查 Marp 源中的标题",
                "review_status": "open" if unresolved else "resolved",
                "review_rationale": None if unresolved else "修订后标题已经明确",
            }]
        path = base / "findings.yaml"
        path.write_text(yaml.safe_dump({"schema_version": 1, "findings": findings}, allow_unicode=True, sort_keys=False), encoding="utf-8")
        submit_channel_review(root, slug, "p01", round_name=round_name, channel=channel, report_path=report, findings_path=path)
    aggregate = task / "reviews" / "p01" / round_name / "aggregate.md"
    fill_placeholders(aggregate)
    aggregate.write_text(aggregate.read_text(encoding="utf-8") + "\n" + "审核协调结论。" * 50, encoding="utf-8")
    aggregate_round(root, slug, "p01", round_name=round_name, aggregate_path=aggregate)


def test_complete_three_round_release(project_root: Path) -> None:
    slug, task = initialize_one_deck(project_root, stop_mode="pilot")
    complete_author_source(task)
    author = finalize_canonical_source(project_root, slug, task)
    install_fake_marp(project_root)

    render_presentation(project_root, slug, "p01", stage="author")
    request_review(project_root, slug, "p01")
    _submit_round(project_root, slug, task, "initial", unresolved=True)

    response = author / "AUTHOR-RESPONSES-initial.yaml"
    value = yaml.safe_load(response.read_text(encoding="utf-8"))
    value["responses"][0].update({"disposition": "accepted", "evidence": "标题已改", "location": "p01-u01-s01", "remaining_uncertainty": "none"})
    response.write_text(yaml.safe_dump(value, allow_unicode=True, sort_keys=False), encoding="utf-8")
    record_author_responses(project_root, slug, "p01", response_file=response)
    render_presentation(project_root, slug, "p01", stage="author")
    request_review(project_root, slug, "p01", changed_areas=["p01-u01-s01"])
    _submit_round(project_root, slug, task, "incremental", unresolved=False)

    render_presentation(project_root, slug, "p01", stage="author")
    request_review(project_root, slug, "p01")
    _submit_round(project_root, slug, task, "final", unresolved=False)

    render_presentation(project_root, slug, "p01", stage="author")
    request_review(project_root, slug, "p01")
    closure_root = task / "workers" / "release-coordinator" / "closure" / "p01"
    closures = closure_root / "closures.yaml"
    closure_report = closure_root / "CLOSURE.md"
    closure_report.write_text(closure_report.read_text(encoding="utf-8") + "\n" + "终审 finding 均已关闭，允许机械发布。" * 30, encoding="utf-8")
    approve_release_closure(project_root, slug, "p01", closure_file=closures, closure_report=closure_report)
    render_presentation(project_root, slug, "p01", stage="release")
    release = finalize_release(project_root, slug, "p01")
    assert (project_root / release["pdf"]).is_file()
    assert load_state(project_root, slug)["phase"] == "complete"
    assert audit_task(project_root, slug)["ok"] is True
