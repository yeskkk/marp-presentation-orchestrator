from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt
import pytest
import yaml

from mpres.audit import audit_task
from mpres.marp_source import lint_deck
from mpres.plotting import save_marp_figure
from mpres.rendering import render_presentation
from mpres.review import aggregate_round, record_author_responses, request_review, submit_channel_review
from mpres.state import REVIEW_CHANNELS
from mpres.util import MPresError, read_yaml

from .conftest import complete_author_source, fill_placeholders, finalize_canonical_source, initialize_one_deck, install_fake_marp


def test_source_lint_rejects_remote_image(project_root: Path) -> None:
    slug, task = initialize_one_deck(project_root)
    complete_author_source(task)
    author = finalize_canonical_source(project_root, slug, task)
    with (author / "presentation.md").open("a", encoding="utf-8") as handle:
        handle.write("\n\n![remote](https://example.invalid/x.png)\n")
    report = lint_deck(author, policy=read_yaml(task / "EXECUTION-POLICY.yaml"))
    assert report["success"] is False
    assert any("Remote" in error for error in report["errors"])


def test_audit_rejects_html_and_non_task_hash_file(project_root: Path) -> None:
    slug, task = initialize_one_deck(project_root)
    (task / "bad.html").write_text("<html></html>", encoding="utf-8")
    (task / "bad.sha256").write_text("forbidden", encoding="utf-8")
    report = audit_task(project_root, slug)
    assert report["ok"] is False
    areas = {item["area"] for item in report["issues"]}
    assert "output-policy" in areas
    assert "hash-policy" in areas


def test_python_plot_helper_blocks_tiny_text(tmp_path: Path) -> None:
    fig = plt.figure(figsize=(8, 4.5))
    fig.text(0.5, 0.5, "tiny", fontsize=8)
    result = save_marp_figure(fig, tmp_path / "tiny.svg", tmp_path / "tiny.json", minimum_text_pt=18)
    plt.close(fig)
    assert result["success"] is False
    assert result["minimum_text_pt"] == 8


def _fill_channel_report(base: Path, findings: list[dict[str, object]]) -> None:
    report = base / "report.md"
    fill_placeholders(report)
    report.write_text(report.read_text(encoding="utf-8") + "\n" + "完整审核证据。" * 40, encoding="utf-8")
    (base / "findings.yaml").write_text(
        yaml.safe_dump({"schema_version": 1, "findings": findings}, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )


def test_incremental_new_finding_must_be_regression(project_root: Path) -> None:
    slug, task = initialize_one_deck(project_root)
    complete_author_source(task)
    author = finalize_canonical_source(project_root, slug, task)
    install_fake_marp(project_root)
    render_presentation(project_root, slug, "p01", stage="author")
    request_review(project_root, slug, "p01")
    initial = {
        "id": "LANG-001", "channel": "language", "round_opened": "initial",
        "location": {"slide_id": "p01-u01-s01"}, "issue": "ambiguous",
        "learner_impact": "confusion", "acceptance_criteria": "clear subject",
        "verification_method": "source check", "review_status": "open",
    }
    for channel in REVIEW_CHANNELS:
        base = task / "workers" / "specialist-reviewers" / "p01" / "initial" / channel
        _fill_channel_report(base, [initial] if channel == "language" else [])
        submit_channel_review(project_root, slug, "p01", round_name="initial", channel=channel, report_path=base / "report.md", findings_path=base / "findings.yaml")
    aggregate = task / "reviews" / "p01" / "initial" / "aggregate.md"
    fill_placeholders(aggregate)
    aggregate.write_text(aggregate.read_text(encoding="utf-8") + "\n" + "协调结论。" * 50, encoding="utf-8")
    aggregate_round(project_root, slug, "p01", round_name="initial", aggregate_path=aggregate)
    response = author / "AUTHOR-RESPONSES-initial.yaml"
    data = yaml.safe_load(response.read_text(encoding="utf-8"))
    data["responses"][0].update({"disposition": "accepted", "evidence": "fixed", "location": "p01-u01-s01", "remaining_uncertainty": "none"})
    response.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
    record_author_responses(project_root, slug, "p01", response_file=response)
    render_presentation(project_root, slug, "p01", stage="author")
    request_review(project_root, slug, "p01", changed_areas=["p01-u01-s01"])
    base = task / "workers" / "specialist-reviewers" / "p01" / "incremental" / "language"
    illegal = [
        {**initial, "review_status": "resolved", "review_rationale": "fixed"},
        {
            "id": "LANG-NEW", "channel": "language", "round_opened": "incremental",
            "kind": "ordinary", "location": {"slide_id": "p01-title"},
            "issue": "new issue", "learner_impact": "minor", "acceptance_criteria": "fix",
            "verification_method": "source check", "review_status": "open",
        },
    ]
    _fill_channel_report(base, illegal)
    with pytest.raises(MPresError, match="regression"):
        submit_channel_review(project_root, slug, "p01", round_name="incremental", channel="language", report_path=base / "report.md", findings_path=base / "findings.yaml")
