from __future__ import annotations

from pathlib import Path

import pytest

from mpres.course_consistency import validate_course_consistency
from mpres.density import validate_slide_density
from mpres.math_inspection import inspect_math_renderer, inspect_math_source
from mpres.orchestration import author_launch_plan
from mpres.production import initialize_production
from mpres.threads import capacity_preflight, expected_runtime, register_thread
from mpres.util import MPresError, read_yaml, write_yaml_atomic

from .conftest import approve_core_assignments, make_confirmed_task


def _simple_marp_source(directory: Path) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "presentation.md").write_text(
        """---
marp: true
theme: mathist-academic
paginate: true
size: 16:9
math: mathjax
---

<!-- slide-id: s01 -->
<!-- _class: core -->

## 一个主要动作

由 $x^2$ 说明当前对象。

---

<!-- slide-id: s02 -->
<!-- _class: support -->

## 一个支持动作

回顾定义。
""",
        encoding="utf-8",
    )


def test_global_runtime_policy_and_reserved_thread_capacity(project_root: Path) -> None:
    slug, _ = make_confirmed_task(project_root, slug="runtime-task")
    assert expected_runtime(project_root, "planner") == {
        "model": "gpt-5.6-sol",
        "reasoning_effort": "max",
    }
    assert expected_runtime(project_root, "lesson-author") == {
        "model": "gpt-5.6-sol",
        "reasoning_effort": "high",
    }
    with pytest.raises(MPresError, match="Runtime mismatch"):
        register_thread(
            project_root,
            slug,
            handle_id="wrong-runtime",
            runtime_name="lesson",
            role="lesson-author",
            actual_model="gpt-5.6-sol",
            actual_reasoning_effort="medium",
        )
    assert capacity_preflight(project_root, slug, requested=14)["ok"] is True
    blocked = capacity_preflight(project_root, slug, requested=15)
    assert blocked["ok"] is False
    assert blocked["reserve_unallocated_capacity"] == 2


def test_author_launch_plan_is_current_not_an_attempt_journal(project_root: Path) -> None:
    slug, task = make_confirmed_task(project_root, slug="plan-task")
    initialize_production(
        project_root,
        slug,
        ["p01::第一份课件"],
        ["p01::u01::第一节内容"],
    )
    approve_core_assignments(project_root, slug, task)
    plan = author_launch_plan(project_root, slug, "p01", save=True)
    assert plan["journal_policy"] == "none; current plan only"
    assert plan["units"][0]["action"] == "start_or_reuse_lesson_author"
    assert plan["runtime"]["reasoning_effort"] == "high"
    assert (task / "state" / "author-launch-plan-p01.json").is_file()
    assert not list(task.rglob("attempt-*"))


def test_slide_density_requires_rationale_for_many_substantial_blocks(tmp_path: Path) -> None:
    source = tmp_path / "source"
    _simple_marp_source(source)
    write_yaml_atomic(
        source / "SLIDE-DENSITY-AUDIT.yaml",
        {
            "schema_version": 1,
            "presentation_id": "p01",
            "slides": [
                {
                    "id": "s01",
                    "principal_teaching_move": "建立一个对象并说明为什么需要它",
                    "substantial_blocks": ["对象", "定义", "反例", "计算"],
                    "split_rationale": "",
                },
                {
                    "id": "s02",
                    "principal_teaching_move": "用一页支持内容重新激活定义",
                    "substantial_blocks": ["定义卡"],
                    "split_rationale": "",
                },
            ],
        },
    )
    failed = validate_slide_density(source)
    assert failed["success"] is False
    assert any("without split_rationale" in item for item in failed["errors"])
    value = read_yaml(source / "SLIDE-DENSITY-AUDIT.yaml")
    value["slides"][0]["split_rationale"] = (
        "四个块共同完成同一个比较动作，拆开会破坏同屏辨析。"
    )
    write_yaml_atomic(source / "SLIDE-DENSITY-AUDIT.yaml", value)
    assert validate_slide_density(source)["success"] is True


def test_math_inspection_has_source_and_renderer_layers_but_no_pdf_evidence(tmp_path: Path) -> None:
    source = tmp_path / "source"
    _simple_marp_source(source)
    inventory = inspect_math_source(source)
    assert inventory["success"] is True
    assert inventory["total_fragments"] == 1
    renderer = inspect_math_renderer(
        inventory,
        {
            "math_renderer": [
                {
                    "id": "s01",
                    "rendered_math_nodes": 1,
                    "renderer_errors": [],
                    "leaked_markers": [],
                },
                {
                    "id": "s02",
                    "rendered_math_nodes": 0,
                    "renderer_errors": [],
                    "leaked_markers": [],
                },
            ]
        },
    )
    assert renderer["success"] is True
    assert "pdf" not in " ".join(renderer.keys()).lower()
    assert not (source / "MATH-PDF-EVIDENCE.json").exists()
    failed = inspect_math_renderer(inventory, {"math_renderer": []})
    assert failed["success"] is False


def test_course_level_terms_objects_and_cross_deck_handoff(project_root: Path) -> None:
    slug, task = make_confirmed_task(project_root, slug="continuity-task")
    initialize_production(
        project_root,
        slug,
        ["p01::第一份课件", "p02::第二份课件"],
        ["p01::u01::第一节课", "p02::u02::第二节课"],
    )
    write_yaml_atomic(
        task / "COURSE-TERMINOLOGY.yaml",
        {
            "schema_version": 1,
            "terms": [
                {"id": "term-linear-map", "canonical_term": "线性映射", "aliases": []}
            ],
        },
    )
    write_yaml_atomic(
        task / "COURSE-SEMANTIC-OBJECTS.yaml",
        {
            "schema_version": 1,
            "objects": [
                {"id": "obj-A", "kind": "matrix", "description": "贯穿两节课的矩阵"}
            ],
        },
    )
    write_yaml_atomic(
        task / "CROSS-DECK-HANDOFFS.yaml",
        {
            "schema_version": 1,
            "handoffs": [
                {
                    "from_presentation": "p01",
                    "to_presentation": "p02",
                    "terms_to_reactivate": ["term-linear-map"],
                    "objects_to_reactivate": ["obj-A"],
                    "bridge": "从第一节课的具体矩阵过渡到第二节课的线性映射。",
                }
            ],
        },
    )
    source = task / "workers" / "author-coordinator" / "drafts" / "p02" / "source"
    write_yaml_atomic(
        source / "TERMINOLOGY.yaml",
        {
            "schema_version": 1,
            "presentation_id": "p02",
            "terms": [
                {
                    "id": "local-linear-map",
                    "course_term_id": "term-linear-map",
                    "canonical_term": "线性映射",
                }
            ],
        },
    )
    write_yaml_atomic(
        source / "SEMANTIC-OBJECTS.yaml",
        {
            "schema_version": 1,
            "presentation_id": "p02",
            "objects": [{"id": "obj-A", "scope": "course", "kind": "matrix"}],
        },
    )
    write_yaml_atomic(
        source / "PRESENTATION-CONTINUITY-MAP.yaml",
        {
            "schema_version": 1,
            "presentation_id": "p02",
            "incoming_from": "p01",
            "reactivated_terms": ["term-linear-map"],
            "reactivated_objects": ["obj-A"],
            "anchor_objects": ["obj-A"],
            "bridges": ["由具体矩阵重新进入线性映射。"],
        },
    )
    result = validate_course_consistency(
        project_root, slug, "p02", source=source
    )
    assert result["success"] is True, result
    terms = read_yaml(source / "TERMINOLOGY.yaml")
    terms["terms"][0]["course_term_id"] = "unknown-term"
    write_yaml_atomic(source / "TERMINOLOGY.yaml", terms)
    assert validate_course_consistency(project_root, slug, "p02", source=source)["success"] is False
