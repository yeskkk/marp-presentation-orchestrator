from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from mpres.interactions import validate_unit_interactions
from mpres.marp_source import lint_deck
from mpres.stages import stage_artifact_path, stage_status, start_stage_sequence, submit_stage
from mpres.util import MPresError, read_yaml

from .conftest import (
    approve_core_assignments,
    complete_authoring_stages,
    fill_placeholders,
    initialize_one_deck,
    prepare_author_source,
    write_unit_source,
)


def test_stage_sequence_requires_planner_approved_lesson_assignment(project_root: Path) -> None:
    slug, _ = initialize_one_deck(project_root)
    with pytest.raises(MPresError, match="planner-approved batch plan"):
        start_stage_sequence(project_root, slug, "p01", "u01")


def test_one_assignment_and_one_sequence_advance_all_authoring_stages(project_root: Path) -> None:
    slug, task = initialize_one_deck(project_root)
    approve_core_assignments(project_root, slug, task)
    initial = start_stage_sequence(project_root, slug, "p01", "u01")
    assert initial["sequence_status"] == "active"
    order = list(initial["stage_order"])
    for stage_id in order:
        status = stage_status(project_root, slug, "p01", "u01")
        assert status["current_stage"] == stage_id
        artifact = stage_artifact_path(project_root, slug, "p01", "u01", stage_id)
        fill_placeholders(artifact, value="同一个 lesson-author 线程完成的阶段分析")
        text = artifact.read_text(encoding="utf-8")
        if stage_id == "01_scope_sources":
            text += "\n\n只读取 tasks/test-task/downloads/text/reference.txt。"
        artifact.write_text(text + "\n" + ("耐久阶段证据。" * 180), encoding="utf-8")
        result = submit_stage(project_root, slug, "p01", "u01", stage_id)
    assert result["sequence_status"] == "completed"
    assert result["current_stage"] is None
    assert all(item["status"] == "completed" for item in result["stages"].values())
    assert not any((task / "workers" / "lesson-authors" / "p01" / "u01" / "stages").rglob("STAGE-ASSIGNMENT.md"))


def test_course_requires_two_or_three_mcqs(project_root: Path) -> None:
    slug, task = initialize_one_deck(project_root)
    complete_authoring_stages(project_root, slug, task)
    write_unit_source(task, kind="course")
    unit = task / "workers" / "lesson-authors" / "p01" / "u01" / "source"
    data = read_yaml(unit / "INTERACTION-MANIFEST.yaml")
    data["interactions"] = data["interactions"][:1]
    yaml.safe_dump(data, (unit / "INTERACTION-MANIFEST.yaml").open("w", encoding="utf-8"), allow_unicode=True, sort_keys=False)
    mcq = read_yaml(unit / "MCQ-AUDIT.yaml")
    mcq["items"] = mcq["items"][:1]
    yaml.safe_dump(mcq, (unit / "MCQ-AUDIT.yaml").open("w", encoding="utf-8"), allow_unicode=True, sort_keys=False)
    report = validate_unit_interactions(unit / "INTERACTION-MANIFEST.yaml", unit / "MCQ-AUDIT.yaml", task_kind="course")
    assert not report["success"]
    assert any("2–3" in error for error in report["errors"])


def test_academic_report_is_exempt_from_mcq_quota(project_root: Path) -> None:
    slug, task = initialize_one_deck(project_root, kind="report", slug="report-task")
    complete_authoring_stages(project_root, slug, task)
    write_unit_source(task, kind="report")
    unit = task / "workers" / "lesson-authors" / "p01" / "u01" / "source"
    report = validate_unit_interactions(unit / "INTERACTION-MANIFEST.yaml", unit / "MCQ-AUDIT.yaml", task_kind="report")
    assert report["success"], report["errors"]
    assert report["mcq_count"] == 0


def test_integrated_deck_passes_marp_lint_and_ignores_front_unit_for_mcq(project_root: Path) -> None:
    slug, task = initialize_one_deck(project_root)
    author = prepare_author_source(project_root, slug, task)
    report = lint_deck(author, policy=read_yaml(task / "EXECUTION-POLICY.yaml"))
    assert report["success"], report["errors"]
    assert report["interactions"]["mcq_count_by_unit"] == {"u01": 2}


def test_bare_tex_control_word_is_blocking(project_root: Path) -> None:
    slug, task = initialize_one_deck(project_root)
    author = prepare_author_source(project_root, slug, task)
    with (author / "presentation.md").open("a", encoding="utf-8") as handle:
        handle.write("\n\n---\n\n<!-- slide-id: bad-tex -->\n<!-- _class: core -->\n\n## Bad math\n\n$$a qquad b$$\n")
    manifest = read_yaml(author / "DECK-MANIFEST.yaml")
    manifest["slides"].append({"id":"bad-tex","unit":"front","kind":"core","concept_chain":"bad","interaction_role":"none","paired_with":None,"interaction_format":"none","selection_rationale":None,"option_audit":None,"semantic_objects":[],"examples":[],"assets":[],"source_refs":[]})
    yaml.safe_dump(manifest, (author / "DECK-MANIFEST.yaml").open("w", encoding="utf-8"), allow_unicode=True, sort_keys=False)
    report = lint_deck(author, policy=read_yaml(task / "EXECUTION-POLICY.yaml"))
    assert not report["success"]
    assert any("Bare TeX" in error for error in report["errors"])
