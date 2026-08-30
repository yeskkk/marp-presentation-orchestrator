from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from mpres.assignments import approve_assignment
from mpres.interactions import validate_unit_interactions
from mpres.marp_source import lint_deck
from mpres.stages import activate_stage, stage_assignment_path, stage_status
from mpres.util import MPresError, read_yaml

from .conftest import (
    complete_authoring_stages,
    fill_placeholders,
    initialize_one_deck,
    prepare_author_source,
    write_unit_source,
)


def test_stage_cannot_activate_without_planner_assignment(project_root: Path) -> None:
    slug, task = initialize_one_deck(project_root)
    stage = stage_status(project_root, slug, "p01", "u01")["current_stage"]
    assignment = stage_assignment_path(project_root, slug, "p01", "u01", stage)
    fill_placeholders(assignment)
    with pytest.raises(MPresError, match="personally complete and approve"):
        activate_stage(project_root, slug, "p01", "u01", stage)


def test_all_stages_require_separate_planner_activation(project_root: Path) -> None:
    slug, task = initialize_one_deck(project_root)
    complete_authoring_stages(project_root, slug, task)
    status = stage_status(project_root, slug, "p01", "u01")
    assert status["current_stage"] is None
    assert all(item["status"] == "accepted" for item in status["stages"].values())


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
