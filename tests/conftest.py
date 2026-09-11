from __future__ import annotations

import os
import re
import shutil
from pathlib import Path
from typing import Any

import fitz
import pytest
import yaml

from mpres.assignments import (
    approve_assignment,
    approve_batch_plan,
    batch_plan_path,
    contract_paths,
)
from mpres.production import initialize_production
from mpres.scheduling import queue_unit
from mpres.stages import (
    stage_artifact_path,
    stage_status,
    start_stage_sequence,
    submit_stage,
)
from mpres.tasks import confirm_task, create_task, present_task
from mpres.tokens import initialize_collector
from mpres.util import read_yaml, utc_now, write_yaml_atomic


@pytest.fixture
def project_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("MPRES_LOG_MODE", "direct-test")
    source = Path(__file__).resolve().parents[1]
    for name in ["templates", "themes", ".agents", ".codex"]:
        shutil.copytree(source / name, tmp_path / name)
    for name in [
        "pyproject.toml",
        "package.json",
        ".npmrc",
        "AGENTS.md",
        "AGENT.md",
        "MODEL-POLICY.yaml",
        "TOOLCHAIN-LOCK.yaml",
    ]:
        if (source / name).exists():
            shutil.copy2(source / name, tmp_path / name)
    (tmp_path / "tasks").mkdir()
    smoke = tmp_path / ".mpres" / "toolchain-smoke.yaml"
    smoke.parent.mkdir(parents=True, exist_ok=True)
    smoke.write_text(
        "schema_version: 1\n"
        "completed_utc: 2026-09-01T00:00:00Z\n"
        "expected_marp_version: 4.5.0\n"
        "actual_marp_version: 4.5.0\n"
        "html_slide_count: 3\n"
        "pdf_page_count: 3\n"
        "meeting_number_fields: [global_meeting_number, deck_local_ordinal]\n"
        "errors: []\n"
        "success: true\n",
        encoding="utf-8",
    )
    smoke_dir = tmp_path / ".mpres"
    smoke_dir.mkdir(parents=True, exist_ok=True)
    write_yaml_atomic(
        smoke_dir / "toolchain-smoke.yaml",
        {
            "schema_version": 1,
            "completed_utc": utc_now(),
            "expected_marp_version": "4.5.0",
            "actual_marp_version": "4.5.0",
            "html_slide_count": 3,
            "pdf_page_count": 3,
            "meeting_number_fields": ["global_meeting_number", "deck_local_ordinal"],
            "errors": [],
            "success": True,
            "test_fixture": True,
        },
    )
    # A successful smoke report implies that the exact pinned local CLI is installed. The test
    # fixture materializes the deterministic fake equivalent before any production initialization.
    install_fake_marp(tmp_path, version="4.5.0")
    if Path("/usr/bin/chromium").is_file():
        os.environ["MPRES_CHROMIUM_EXECUTABLE"] = "/usr/bin/chromium"
    return tmp_path


@pytest.fixture(autouse=True)
def deterministic_layout_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep the regression suite deterministic and avoid persistent browser processes.

    The production Playwright implementation has its own interface test; render/review tests use
    the same disposable-HTML generation path with a deterministic DOM-style runner.
    """

    from bs4 import BeautifulSoup
    import mpres.doctor as doctor_module
    import mpres.rendering as rendering_module
    from mpres.html_layout import inspect_marp_html_layout as real_inspect

    def browser_runner(html_path: Path, asset_root: Path) -> dict[str, Any]:
        del asset_root
        soup = BeautifulSoup(html_path.read_text(encoding="utf-8"), "html.parser")
        rows: list[dict[str, Any]] = []
        for index, section in enumerate(soup.select("section[data-marpit-scope], .marpit > section"), start=1):
            overflow = "height:900px" in str(section).replace(" ", "")
            rows.append(
                {
                    "index": index,
                    "id": section.get("id") or f"slide-{index}",
                    "clientWidth": 1280,
                    "clientHeight": 720,
                    "scrollWidth": 1280,
                    "scrollHeight": 900 if overflow else 720,
                    "computedWidth": "1280px",
                    "computedHeight": "720px",
                    "overflowX": 0,
                    "overflowY": 180 if overflow else 0,
                    "overflow": overflow,
                    "textLength": len(section.get_text(" ", strip=True)),
                }
            )
        overflow_rows = [row for row in rows if row["overflow"]]
        errors = (
            ["Detected HTML slide overflow on slide(s): " + ", ".join(row["id"] for row in overflow_rows)]
            if overflow_rows
            else []
        )
        return {
            "schema_version": 1,
            "browser_executable": "deterministic-test-runner",
            "browser_source": "test",
            "browser_version": "test",
            "slide_count": len(rows),
            "slides": rows,
            "overflow_slide_count": len(overflow_rows),
            "overflow_slides": overflow_rows,
            "page_errors": [],
            "failed_requests": [],
            "blocked_external_requests": [],
            "console_messages": [],
            "errors": errors,
            "warnings": [],
            "success": bool(rows) and not errors,
            "inspection_policy": "author mechanical self-check; no screenshots or model vision",
        }

    def deterministic_inspect(root: Path, source: Path, *, policy: dict[str, Any], timeout: int = 1800) -> dict[str, Any]:
        return real_inspect(
            root, source, policy=policy, timeout=timeout, browser_runner=browser_runner
        )

    monkeypatch.setattr(rendering_module, "inspect_marp_html_layout", deterministic_inspect)
    monkeypatch.setattr(
        doctor_module,
        "browser_probe",
        lambda: {
            "available": True,
            "executable": "deterministic-test-runner",
            "source": "test",
            "browser_version": "test",
            "error": None,
        },
    )


def fill_placeholders(path: Path, value: str = "由主规划者写定的具体、可执行且可验收的内容") -> None:
    text = path.read_text(encoding="utf-8")
    text = re.sub(r"\[\[[A-Z0-9_]+\]\]", value, text)
    path.write_text(text, encoding="utf-8", newline="\n")


def make_confirmed_task(
    root: Path,
    *,
    kind: str = "course",
    stop_mode: str = "all",
    slug: str = "test-task",
    minutes: int = 90,
    production_mode: str = "greenfield_full",
) -> tuple[str, Path]:
    slug, task = create_task(
        root=root,
        title="测试课程" if kind == "course" else "测试学术报告",
        slug=slug,
        kind=kind,
        stop_mode=stop_mode,
        sessions=2 if kind == "course" else None,
        minutes=minutes if kind == "course" else None,
        production_mode=production_mode,
    )
    fill_placeholders(task / "TASK.md")
    with (task / "TASK.md").open("a", encoding="utf-8") as handle:
        handle.write("\n\n" + "完整规划、听众、策略、资料、角色和验收说明。" * 180)
    present_task(root, slug)
    confirm_task(root, slug)
    sessions_root = root / ".test-codex-sessions"
    sessions_root.mkdir(exist_ok=True)
    initialize_collector(
        root,
        slug,
        sessions_root=sessions_root,
        root_thread_id=f"root-{slug}",
    )
    return slug, task


def initialize_one_deck(
    root: Path,
    *,
    kind: str = "course",
    stop_mode: str = "all",
    slug: str = "test-task",
    minutes: int = 90,
    production_mode: str = "greenfield_full",
) -> tuple[str, Path]:
    slug, task = make_confirmed_task(
        root,
        kind=kind,
        stop_mode=stop_mode,
        slug=slug,
        minutes=minutes,
        production_mode=production_mode,
    )
    initialize_production(
        root,
        slug,
        ["p01::第一份课件"],
        ["p01::u01::第一节内容"],
    )
    return slug, task


def planner_write_and_approve(root: Path, slug: str, assignment: Path) -> None:
    fill_placeholders(assignment)
    with assignment.open("a", encoding="utf-8") as handle:
        handle.write(
            "\n\n主规划者补充：本任务的范围、听众状态、允许的局部判断、资料路径、"
            "停止条件和验收标准均已明确。只能读取 downloads/text/reference.txt；"
            "不得访问任何受限原件。" * 10
        )
    _, brief, _ = contract_paths(assignment)
    fill_placeholders(brief, value="planner 写定的硬约束、局部判断权和验收标准")
    value = read_yaml(brief)
    assert isinstance(value, dict)
    value["written_by"] = "planner"
    value["approved_text_sources"] = ["tasks/test-task/downloads/text/reference.txt"]
    value["hard_constraints"] = ["只执行本 assignment，禁止访问受限原件。"]
    value["replaceable_hypotheses"] = ["可替换标题和例题数字，但不能改变教学目标。"]
    value["local_decision_rights"] = ["可调整局部页序和学生可见措辞。"]
    value["acceptance_criteria"] = ["完成指定产物并通过结构化检查。"]
    value["deferred_questions"] = ["无"]
    write_yaml_atomic(brief, value)
    approve_assignment(
        root,
        slug,
        assignment,
        notes="a main or delegated planner wrote this assignment",
        planner_actor="delegated-planner:test",
    )


def approve_batch_and_queue_unit(root: Path, slug: str, task: Path) -> Path:
    plan = batch_plan_path(root, slug)
    if not plan.is_file():
        raise AssertionError(f"missing batch plan: {plan}")
    if (read_yaml(plan) or {}).get("status") != "approved":
        fill_placeholders(
            plan,
            value=(
                "由受委派 planner 写定的精确单元范围、听众背景、先备知识、"
                "允许的局部判断、基线差量、资料路径和验收标准"
            ),
        )
        value = read_yaml(plan)
        assert isinstance(value, dict)
        value["written_by"] = "planner"
        value["planner_actor"] = "delegated-planner:test"
        value["common"]["hard_constraints"] = ["只执行获批批次计划，不访问受限原件。"]
        value["common"]["replaceable_hypotheses"] = ["可调整局部措辞，不改变课程目标。"]
        value["common"]["local_decision_rights"] = ["可调整局部页序和例题数字。"]
        value["common"]["approved_text_sources"] = [
            f"tasks/{slug}/downloads/text/reference.txt"
        ]
        value["common"]["acceptance_criteria"] = ["完成阶段产物并通过结构化检查。"]
        for presentation in value.get("presentations", []):
            presentation["common_constraints"] = ["保持整份课件术语和对象连续。"]
            for unit in presentation.get("units", []):
                unit["unit_scope"] = "完成本课次的概念链、诊断题和可选延伸例题。"
                unit["audience_context"] = "面向需要直观入口、但仍须看到严格定义的学习者。"
                unit["prior_knowledge_to_reactivate"] = "只重新激活当前课次直接使用的既有知识，并明确不扩展到与本课次无关的先备内容。"
                unit["local_decision_rights"] = ["可调整本课次页序、措辞和例题数字。"]
                unit["approved_text_sources"] = [f"tasks/{slug}/downloads/text/reference.txt"]
                unit["acceptance_criteria"] = ["交付完整 lesson fragment 和 durable handoff。"]
                unit["baseline_source"] = "none"
                unit["baseline_maturity"] = "not_applicable"
                unit["legacy_source_ranges"] = ["none"]
                unit["required_delta"] = ["完成本课次获批教学目标。"]
                unit["known_risks"] = ["避免课次编号、互动配对和核心/选讲边界漂移。"]
        write_yaml_atomic(plan, value)
        approve_batch_plan(
            root,
            slug,
            planner_actor="delegated-planner:test",
            notes="test planner approved one batch plan for deterministic expansion",
        )
    queue_unit(root, slug, "p01", "u01")
    return task / "workers" / "lesson-authors" / "p01" / "u01" / "TASK-LESSON-AUTHOR.md"


def approve_core_assignments(root: Path, slug: str, task: Path) -> None:
    # The deck coordinator is individually planner-approved. Lesson semantics come from the
    # approved batch plan. Review, revision, and release roles do not exist until their gates.
    author = (
        task
        / "workers"
        / "author-coordinator"
        / "assignments"
        / "p01"
        / "TASK-AUTHOR-COORDINATOR.md"
    )
    if not (read_yaml(contract_paths(author)[2]) or {}).get("status") == "approved":
        planner_write_and_approve(root, slug, author)
    lesson = approve_batch_and_queue_unit(root, slug, task)
    assert (read_yaml(contract_paths(lesson)[2]) or {}).get("written_by") == "planner-via-approved-batch"


def complete_authoring_stages(root: Path, slug: str, task: Path) -> None:
    approve_core_assignments(root, slug, task)
    start_stage_sequence(root, slug, "p01", "u01")
    while True:
        status = stage_status(root, slug, "p01", "u01")
        stage_id = status.get("current_stage")
        if stage_id is None:
            break
        artifact = stage_artifact_path(root, slug, "p01", "u01", stage_id)
        fill_placeholders(artifact, value="本阶段已经完成的具体分析和决定")
        text = artifact.read_text(encoding="utf-8")
        if stage_id == "01_scope_sources":
            text += (
                "\n\n本单元只读取 tasks/test-task/downloads/text/reference.txt。"
                "该文本足以支持当前范围；原始文献路径不会暴露给作者。"
            )
        text += "\n\n" + (f"{stage_id} 的耐久分析、证据和下一阶段约束。" * 100)
        artifact.write_text(text, encoding="utf-8", newline="\n")
        submit_stage(root, slug, "p01", "u01", stage_id)


def _option_audit(correct: str = "A") -> dict[str, dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}
    for label in ("A", "B", "C", "D"):
        if label == correct:
            rows[label] = {
                "stem_compatible": True,
                "truth_status": "correct",
                "wording_check": "该选项与题干语法及数学对象完全匹配。",
                "justification": "依据当前对象的定义和条件，这一判断成立。",
            }
        else:
            rows[label] = {
                "stem_compatible": True,
                "truth_status": "incorrect",
                "wording_check": "该选项与题干语法匹配，但数学结论不成立。",
                "misconception": "它对应学生容易混淆条件、结论或对象的典型误区。",
            }
    return rows


def write_unit_source(task: Path, *, kind: str = "course") -> None:
    unit = task / "workers" / "lesson-authors" / "p01" / "u01" / "source"
    if kind == "course":
        section = """<!-- slide-id: p01-u01-s01 -->
<!-- _class: core -->

## 第 1 节课：从一个具体对象开始

这一页建立本节课共同使用的对象，并解释为什么需要新的概念。

---

<!-- slide-id: p01-u01-q1 -->
<!-- _class: core -->

## 选择题一：区分条件与结论

给定当前对象，哪一个判断正确？

- A. 只有选项 A 满足当前定义
- B. 忽略了题目中的必要条件
- C. 把一个充分条件误当成必要条件
- D. 把另一个对象的性质搬到了当前对象

---

<!-- slide-id: p01-u01-a1 -->
<!-- _class: support -->

## 选择题一的回答

**答案：** A。这里必须同时使用对象和条件，而不能照抄上一页的一句话。

---

<!-- slide-id: p01-u01-q2 -->
<!-- _class: core -->

## 选择题二：把方法迁移到新对象

换成一个结构不同但符号相似的对象，哪一个方法仍然适用？

- A. 直接沿用旧结论而不检查条件
- B. 先检查条件，再选择相应方法
- C. 只凭图形外观判断
- D. 把单位和对象类型全部忽略

---

<!-- slide-id: p01-u01-a2 -->
<!-- _class: support -->

## 选择题二的回答

**答案：** B。迁移的关键是重新核对条件，而不是机械复制步骤。
"""
        interactions = [
            {
                "prompt_slide": "p01-u01-q1",
                "response_slide": "p01-u01-a1",
                "format": "multiple_choice",
                "purpose": "诊断学生是否能区分定义中的条件与结论。",
                "answer_leakage_check": "题干页没有答案标记，答案只在紧邻的 support 页出现。",
            },
            {
                "prompt_slide": "p01-u01-q2",
                "response_slide": "p01-u01-a2",
                "format": "multiple_choice",
                "purpose": "诊断学生能否把方法迁移到结构不同的新对象。",
                "answer_leakage_check": "题干页只给问题和选项，不泄露正确方法。",
            },
        ]
        items = [
            {
                "prompt_slide": "p01-u01-q1",
                "response_slide": "p01-u01-a1",
                "purpose": "区分条件和结论，避免只记住表面口号。",
                "preceding_comparison": "上一页只建立对象，本题要求独立判断四个陈述。",
                "requires_fresh_inference": True,
                "information_state": {
                    "available_before_prompt": ["当前对象、定义和必要条件已经在前页给出。"],
                    "intentionally_withheld": [],
                },
                "new_inference": "学生必须把定义中的条件应用到四个新陈述，而不是复制上一页。",
                "decision_unit": "判断哪一个陈述满足当前定义",
                "prerequisite_available": True,
                "cue_leakage_audit": "题干和选项没有重复答案页措辞，也没有强调正确选项。",
                "composite_option_check": {
                    "single_decision": True,
                    "rationale": "四个选项都回答同一个关于条件与结论的判断问题。",
                },
                "selection_rationale": "concept_discrimination",
                "visible_labels": ["A", "B", "C", "D"],
                "option_audit": _option_audit("A"),
            },
            {
                "prompt_slide": "p01-u01-q2",
                "response_slide": "p01-u01-a2",
                "purpose": "检查学生能否在新对象上重新选择方法。",
                "preceding_comparison": "该题改变对象结构，不能从上一页直接复制答案。",
                "requires_fresh_inference": True,
                "information_state": {
                    "available_before_prompt": ["旧方法的适用条件和新对象的结构均已给出。"],
                    "intentionally_withheld": [],
                },
                "new_inference": "学生必须重新检查适用条件，并据此选择方法。",
                "decision_unit": "选择适用于新对象的方法",
                "prerequisite_available": True,
                "cue_leakage_audit": "题干不出现答案页中的重新核对条件表述。",
                "composite_option_check": {
                    "single_decision": True,
                    "rationale": "每个选项都是对同一个方法选择问题的回答。",
                },
                "selection_rationale": "transfer",
                "visible_labels": ["A", "B", "C", "D"],
                "option_audit": _option_audit("B"),
            },
        ]
        slide_ids = ["p01-u01-s01", "p01-u01-q1", "p01-u01-a1", "p01-u01-q2", "p01-u01-a2"]
    else:
        section = """<!-- slide-id: p01-u01-s01 -->
<!-- _class: core -->

## 报告的核心问题

这一页给出报告对象、范围和主要结论，不设置课程型选择题配额。
"""
        interactions = []
        items = []
        slide_ids = ["p01-u01-s01"]
    (unit / "section.md").write_text(section, encoding="utf-8", newline="\n")
    write_yaml_atomic(
        unit / "UNIT-MANIFEST.yaml",
        {
            "schema_version": 2,
            "presentation_id": "p01",
            "unit_id": "u01",
            "title": "第一节内容",
            "meeting_number": 1 if kind == "course" else None,
            "global_meeting_number": 1 if kind == "course" else None,
            "deck_local_ordinal": 1,
            "meeting_label": "第 1 节课" if kind == "course" else "报告部分 1",
            "organization_basis": "course_meeting" if kind == "course" else "report_section",
            "slide_ids": slide_ids,
            "concept_chains": ["chain-1"],
            "semantic_objects": [],
            "examples": [],
            "assets": [],
        },
    )
    write_yaml_atomic(
        unit / "INTERACTION-RECORD.yaml",
        {
            "schema_version": 1,
            "presentation_id": "p01",
            "unit_id": "u01",
            "task_kind": kind,
            "canonical": True,
            "interactions": interactions,
            "mcq_items": items,
        },
    )
    from mpres.interactions import materialize_unit_interaction_views

    materialize_unit_interaction_views(unit)
    write_yaml_atomic(
        unit / "GEOGEBRA-RESOURCES.yaml",
        {
            "schema_version": 2,
            "presentation_id": "p01",
            "unit_id": "u01",
            "relevant": False,
            "rationale": "当前测试单元不需要动态 GeoGebra 活动。",
            "site_scope": "geogebra.org",
            "search_attempted": False,
            "search_queries": [],
            "search_outcome": "not_applicable",
            "selected_resources": [],
        },
    )
    existing_time_plan = read_yaml(unit / "LESSON-TIME-PLAN.yaml")
    assert isinstance(existing_time_plan, dict)
    existing_time_plan["core_path"] = {
        "purpose": "完成必须讲授的概念链和诊断题。",
        "planned_end_slide_id": "p01-u01-a2" if kind == "course" else "p01-u01-s01",
    }
    existing_time_plan["extension_example_bank"] = {
        "purpose": "以讲解例题提供可选延伸，到点可以不讲完。",
        "items": [],
    }
    existing_time_plan["variation_rationale"] = (
        "测试计划按约 1.5 倍名义时长准备，约束为建议而非硬门。"
    )
    write_yaml_atomic(unit / "LESSON-TIME-PLAN.yaml", existing_time_plan)
    (unit / "SELF-CHECK.md").write_text(
        "# Unit self-check\n\n" + "已检查对象、术语、课程互动和学生进入点。\n" * 30,
        encoding="utf-8",
    )


def prepare_author_source(root: Path, slug: str, task: Path, *, kind: str = "course") -> Path:
    from mpres.production import assemble_units

    complete_authoring_stages(root, slug, task)
    write_unit_source(task, kind=kind)
    author = task / "workers" / "author-coordinator" / "drafts" / "p01" / "source"
    (task / "downloads" / "text" / "reference.txt").write_text(
        "这是只供 worker 使用的抽取文本。" * 100, encoding="utf-8"
    )
    header = author / "HEADER.md"
    fill_placeholders(header)
    header.write_text(
        "---\nmarp: true\ntheme: mathist-academic\npaginate: true\nsize: '16:9'\n"
        "math: mathjax\n---\n\n"
        "<!-- _class: core -->\n<!-- slide-id: p01-title -->\n\n"
        "# 第一份课件\n\n测试课程\n",
        encoding="utf-8",
    )
    for name in [
        "PEDAGOGY-MAP.md",
        "EXAMPLE-MAP.md",
        "TERMINOLOGY.md",
        "SEMANTIC-OBJECTS.yaml",
        "SELF-CHECK.md",
        "RELEASE-RETROSPECTIVE.md",
    ]:
        fill_placeholders(author / name)
    (author / "SELF-CHECK.md").write_text(
        "# Deck self-check\n\n" + "已检查内容、术语、课次边界、时间计划、Marp 源、临时 HTML 溢出、互动配对和 PDF 结构。\n" * 35,
        encoding="utf-8",
    )
    write_yaml_atomic(
        author / "ASSET-DECISIONS.yaml",
        {
            "schema_version": 2,
            "presentation_id": "p01",
            "policy": {"python_generated": "disabled"},
            "assets": [],
        },
    )
    assemble_units(root, slug, "p01")
    slide_rows: list[dict[str, Any]] = [
        {
            "id": "p01-title",
            "unit": "front",
            "kind": "core",
            "concept_chain": "intro",
            "interaction_role": "none",
            "paired_with": None,
            "interaction_format": "none",
            "selection_rationale": None,
            "option_audit": None,
            "semantic_objects": [],
            "examples": [],
            "assets": [],
            "source_refs": [],
        },
        {
            "id": "p01-u01-s01",
            "unit": "u01",
            "kind": "core",
            "concept_chain": "chain-1",
            "interaction_role": "none",
            "paired_with": None,
            "interaction_format": "none",
            "selection_rationale": None,
            "option_audit": None,
            "semantic_objects": [],
            "examples": [],
            "assets": [],
            "source_refs": ["downloads/text/reference.txt"],
        },
    ]
    if kind == "course":
        for prompt, answer, rationale, correct in [
            ("p01-u01-q1", "p01-u01-a1", "concept_discrimination", "A"),
            ("p01-u01-q2", "p01-u01-a2", "transfer", "B"),
        ]:
            slide_rows.extend(
                [
                    {
                        "id": prompt,
                        "unit": "u01",
                        "kind": "core",
                        "concept_chain": "chain-1",
                        "interaction_role": "exercise_prompt",
                        "paired_with": answer,
                        "interaction_format": "multiple_choice",
                        "selection_rationale": rationale,
                        "option_audit": _option_audit(correct),
                        "semantic_objects": [],
                        "examples": [],
                        "assets": [],
                        "source_refs": [],
                    },
                    {
                        "id": answer,
                        "unit": "u01",
                        "kind": "support",
                        "concept_chain": "chain-1",
                        "interaction_role": "exercise_answer",
                        "paired_with": prompt,
                        "interaction_format": "none",
                        "selection_rationale": None,
                        "option_audit": None,
                        "semantic_objects": [],
                        "examples": [],
                        "assets": [],
                        "source_refs": [],
                    },
                ]
            )
    write_yaml_atomic(
        author / "DECK-MANIFEST.yaml",
        {
            "schema_version": 2,
            "presentation_id": "p01",
            "title": "第一份课件",
            "task_kind": kind,
            "content_units": [
                {
                    "id": "u01",
                    "title": "第一节内容",
                    "meeting_number": 1 if kind == "course" else None,
                    "global_meeting_number": 1 if kind == "course" else None,
                    "deck_local_ordinal": 1,
                    "meeting_label": "第 1 节课" if kind == "course" else "报告部分 1",
                    "organization_basis": "course_meeting" if kind == "course" else "report_section",
                    "source": "sections/u01/section.md",
                }
            ],
            "slides": slide_rows,
        },
    )
    write_yaml_atomic(
        author / "SLIDE-DENSITY-AUDIT.yaml",
        {
            "schema_version": 1,
            "presentation_id": "p01",
            "slides": [
                {
                    "id": row["id"],
                    "principal_teaching_move": (
                        "建立本页唯一的主要教学动作并服务于当前概念链"
                    ),
                    "substantial_blocks": ["一个连贯的教学信息组"],
                    "split_rationale": "",
                }
                for row in slide_rows
            ],
        },
    )
    return author


def install_fake_marp(root: Path, *, version: str = "4.5.0", overflow_html: bool = False) -> Path:
    """Install a fast deterministic Marp test double."""

    binary = root / "node_modules" / ".bin" / "marp"
    binary.parent.mkdir(parents=True, exist_ok=True)
    template = (Path(__file__).with_name("fake_marp_cli.py")).read_text(encoding="utf-8")
    template = template.replace("__VERSION__", version).replace(
        "__OVERFLOW__", "True" if overflow_html else "False"
    )
    binary.write_text(template, encoding="utf-8", newline="\n")
    binary.chmod(0o755)
    return binary

# Readable aliases used across the current regression suite.
complete_assignment = planner_write_and_approve
complete_core_assignments = approve_core_assignments
complete_all_stages = complete_authoring_stages


def complete_specialist_assignments(root: Path, slug: str, task: Path) -> None:
    from mpres.state import REVIEW_CHANNELS

    for channel in REVIEW_CHANNELS:
        assignment = (
            task
            / "workers"
            / "specialist-reviewers"
            / "p01"
            / "full"
            / channel
            / "TASK-SPECIALIST-REVIEWER.md"
        )
        planner_write_and_approve(root, slug, assignment)


def approve_revision_author(root: Path, slug: str, task: Path) -> Path:
    planner_write_and_approve(
        root,
        slug,
        task
        / "workers"
        / "deck-revision-author"
        / "assignments"
        / "p01"
        / "TASK-DECK-REVISION-AUTHOR.md",
    )
    return task / "workers" / "deck-revision-author" / "drafts" / "p01" / "source"


def release_zero_finding_deck(
    root: Path, *, slug: str = "maintenance-task"
) -> tuple[str, Path, dict[str, Any]]:
    """Produce one fully released deck with the standard no-recheck workflow."""

    from mpres.rendering import render_presentation
    from mpres.review import (
        aggregate_round,
        complete_author_revision,
        finalize_release,
        request_review,
        submit_channel_review,
    )
    from mpres.state import REVIEW_CHANNELS

    slug, task = initialize_one_deck(root, slug=slug)
    install_fake_marp(root, version="4.5.0")
    source = prepare_author_source(root, slug, task)
    render_presentation(root, slug, "p01", stage="author", timeout=60)
    request_review(root, slug, "p01")
    for channel in REVIEW_CHANNELS:
        channel_root = task / "workers" / "specialist-reviewers" / "p01" / "full" / channel
        planner_write_and_approve(root, slug, channel_root / "TASK-SPECIALIST-REVIEWER.md")
        report = channel_root / "report.md"
        report.write_text(
            f"# {channel} review\n\n" + "完整阅读冻结稿，当前通道没有 finding。\n" * 45,
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
                "findings": [],
            },
        )
        submit_channel_review(
            root,
            slug,
            "p01",
            round_name="full",
            channel=channel,
            report_path=report,
            findings_path=structured,
        )
    aggregate = task / "reviews" / "p01" / "full" / "aggregate.md"
    aggregate.write_text(
        "# Review aggregate\n\n" + "五个通道均完整审核，当前无 finding。\n" * 45,
        encoding="utf-8",
    )
    aggregate_round(root, slug, "p01", round_name="full", aggregate_path=aggregate)
    source = approve_revision_author(root, slug, task)
    responses = source / "AUTHOR-RESPONSES.yaml"
    response_value = read_yaml(responses)
    assert response_value["responses"] == []
    checklist = source / "AUTHOR-MODIFICATION-CHECKLIST.yaml"
    checklist_value = read_yaml(checklist)
    checklist_value["steps"] = {key: True for key in checklist_value["steps"]}
    checklist_value["completed_utc"] = utc_now()
    checklist_value["author_declaration"] = (
        "The author completed the required revision workflow even though no findings were opened."
    )
    write_yaml_atomic(checklist, checklist_value)
    (source / "AUTHOR-REVISION.md").write_text(
        "# Author revision\n\n" + "已重新检查整份课件并完成规定流程。\n" * 45,
        encoding="utf-8",
    )
    (source / "SELF-CHECK.md").write_text(
        "# Revised self-check\n\n" + "已重新运行全部 author 机械检查。\n" * 45,
        encoding="utf-8",
    )
    render_presentation(root, slug, "p01", stage="author", timeout=60)
    complete_author_revision(root, slug, "p01", checklist_file=checklist)
    render_presentation(root, slug, "p01", stage="release", timeout=60)
    release = finalize_release(root, slug, "p01")
    return slug, task, release
