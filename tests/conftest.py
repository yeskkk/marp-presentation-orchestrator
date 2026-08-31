from __future__ import annotations

import os
import re
import shutil
from pathlib import Path
from typing import Any

import fitz
import pytest
import yaml

from mpres.assignments import approve_assignment, contract_paths
from mpres.production import initialize_production
from mpres.stages import (
    accept_stage,
    activate_stage,
    stage_artifact_path,
    stage_assignment_path,
    stage_status,
    submit_stage,
)
from mpres.tasks import confirm_task, create_task, present_task
from mpres.util import read_yaml, utc_now, write_yaml_atomic


@pytest.fixture
def project_root(tmp_path: Path) -> Path:
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
    ]:
        if (source / name).exists():
            shutil.copy2(source / name, tmp_path / name)
    (tmp_path / "tasks").mkdir()
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
) -> tuple[str, Path]:
    slug, task = create_task(
        root=root,
        title="测试课程" if kind == "course" else "测试学术报告",
        slug=slug,
        kind=kind,
        stop_mode=stop_mode,
        sessions=2 if kind == "course" else None,
        minutes=minutes if kind == "course" else None,
    )
    fill_placeholders(task / "TASK.md")
    with (task / "TASK.md").open("a", encoding="utf-8") as handle:
        handle.write("\n\n" + "完整规划、听众、策略、资料、角色和验收说明。" * 180)
    present_task(root, slug)
    confirm_task(root, slug)
    return slug, task


def initialize_one_deck(
    root: Path,
    *,
    kind: str = "course",
    stop_mode: str = "all",
    slug: str = "test-task",
    minutes: int = 90,
) -> tuple[str, Path]:
    slug, task = make_confirmed_task(
        root, kind=kind, stop_mode=stop_mode, slug=slug, minutes=minutes
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
    approve_assignment(root, slug, assignment, notes="planner personally wrote this assignment")


def approve_core_assignments(root: Path, slug: str, task: Path) -> None:
    paths = [
        task / "workers" / "author-coordinator" / "assignments" / "p01" / "TASK-AUTHOR-COORDINATOR.md",
        task / "workers" / "review-coordinator" / "assignments" / "p01" / "TASK-REVIEW-COORDINATOR.md",
        task / "workers" / "release-coordinator" / "assignments" / "p01" / "TASK-RELEASE-COORDINATOR.md",
        task / "workers" / "lesson-authors" / "p01" / "u01" / "TASK-LESSON-AUTHOR.md",
    ]
    for path in paths:
        planner_write_and_approve(root, slug, path)


def complete_authoring_stages(root: Path, slug: str, task: Path) -> None:
    approve_core_assignments(root, slug, task)
    while True:
        status = stage_status(root, slug, "p01", "u01")
        stage_id = status.get("current_stage")
        if stage_id is None:
            break
        assignment = stage_assignment_path(root, slug, "p01", "u01", stage_id)
        planner_write_and_approve(root, slug, assignment)
        activate_stage(root, slug, "p01", "u01", stage_id)
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
        accept_stage(root, slug, "p01", "u01", stage_id)


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
        unit / "INTERACTION-MANIFEST.yaml",
        {
            "schema_version": 2,
            "presentation_id": "p01",
            "unit_id": "u01",
            "interactions": interactions,
        },
    )
    write_yaml_atomic(
        unit / "MCQ-AUDIT.yaml",
        {
            "schema_version": 2,
            "presentation_id": "p01",
            "unit_id": "u01",
            "task_kind": kind,
            "items": items,
        },
    )
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
        "math: mathjax\nbackgroundColor: '#ffffff'\n---\n\n"
        "<!-- _class: lead core -->\n<!-- slide-id: p01-title -->\n\n"
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
                    "meeting_label": "第 1 节课" if kind == "course" else "报告部分 1",
                    "organization_basis": "course_meeting" if kind == "course" else "report_section",
                    "source": "sections/u01/section.md",
                }
            ],
            "slides": slide_rows,
        },
    )
    return author


def install_fake_marp(root: Path, *, version: str = "9.9.9", overflow_html: bool = False) -> Path:
    binary = root / "node_modules" / ".bin" / "marp"
    binary.parent.mkdir(parents=True, exist_ok=True)
    overflow_literal = "True" if overflow_html else "False"
    binary.write_text(
        f'''#!/usr/bin/env python3
from __future__ import annotations
import html
import re
import sys
from pathlib import Path
import fitz

OVERFLOW_HTML = {overflow_literal}
if '--version' in sys.argv:
    print('{version}')
    raise SystemExit(0)
args = sys.argv[1:]
source = Path(args[0])
output = Path(args[args.index('--output') + 1])
text = source.read_text(encoding='utf-8')
lines = text.splitlines()
front_end = next(i for i, line in enumerate(lines[1:], start=1) if line.strip() == '---')
body = lines[front_end + 1:]
chunks = []
current = []
in_fence = False
for line in body:
    if line.lstrip().startswith('```'):
        in_fence = not in_fence
    if line.strip() == '---' and not in_fence:
        chunks.append(current)
        current = []
    else:
        current.append(line)
chunks.append(current)
output.parent.mkdir(parents=True, exist_ok=True)
if output.suffix.lower() == '.html':
    sections = []
    for index, chunk in enumerate(chunks, start=1):
        chunk_text = '\\n'.join(chunk)
        match = re.search(r'<!--\\s*slide-id:\\s*([^\\s]+)\\s*-->', chunk_text)
        slide_id = match.group(1) if match else f'slide-{{index}}'
        visible = html.escape(re.sub(r'<!--.*?-->', '', chunk_text, flags=re.S))
        extra = '<div style="height:900px">overflow</div>' if OVERFLOW_HTML and index == 1 else ''
        sections.append(
            f'<section data-marpit-scope="1" id="{{slide_id}}" style="box-sizing:border-box;width:1280px;height:720px;overflow:hidden;padding:40px"><pre style="white-space:pre-wrap">{{visible}}</pre>{{extra}}</section>'
        )
    output.write_text(
        '<!doctype html><html><head><meta charset="utf-8"><style>html,body{{margin:0}}.marpit>section{{position:relative;display:block}}</style></head><body><div class="marpit">'
        + ''.join(sections) + '</div></body></html>',
        encoding='utf-8',
    )
else:
    doc = fitz.open()
    for index in range(len(chunks)):
        page = doc.new_page(width=960, height=540)
        page.insert_text((72, 90), f'Marp test slide {{index + 1}}', fontsize=28)
        page.insert_text((72, 140), 'Readable mathematical presentation content.', fontsize=22)
    doc.save(output)
    doc.close()
print(f'Wrote {{output}}')
''',
        encoding="utf-8",
    )
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
