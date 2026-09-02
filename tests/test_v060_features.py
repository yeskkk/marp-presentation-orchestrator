from __future__ import annotations

from pathlib import Path

import pytest

from mpres.assignments import contract_paths
from mpres.course_consistency import validate_course_consistency
from mpres.engine_incidents import record_engine_incident
from mpres.density import validate_slide_density
from mpres.math_inspection import inspect_math_renderer, inspect_math_source
from mpres.orchestration import author_launch_plan
from mpres.production import activate_presentations, initialize_production
from mpres.production_profiles import MIGRATION_STAGES
from mpres.review import request_review
from mpres.state import REVIEW_CHANNELS, load_state
from mpres.threads import capacity_preflight, expected_runtime, register_thread
from mpres.toolchain import require_pinned_marp
from mpres.util import MPresError, read_yaml, write_yaml_atomic

from .conftest import (
    approve_batch_and_queue_unit,
    approve_core_assignments,
    initialize_one_deck,
    install_fake_marp,
    make_confirmed_task,
    prepare_author_source,
)


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


def test_task_runtime_policy_and_reserved_thread_capacity(project_root: Path) -> None:
    slug, _ = make_confirmed_task(project_root, slug="runtime-task")
    planner = expected_runtime(project_root, slug, "planner")
    assert {key: planner[key] for key in ("model", "reasoning_effort")} == {
        "model": "gpt-5.6-sol",
        "reasoning_effort": "high",
    }
    author = expected_runtime(project_root, slug, "lesson-author")
    assert {key: author[key] for key in ("model", "reasoning_effort")} == {
        "model": "gpt-5.6-sol",
        "reasoning_effort": "medium",
    }
    reviewer = expected_runtime(project_root, slug, "specialist-reviewer")
    assert {key: reviewer[key] for key in ("model", "reasoning_effort")} == {
        "model": "gpt-5.6-sol",
        "reasoning_effort": "low",
    }
    with pytest.raises(MPresError, match="Runtime mismatch"):
        register_thread(
            project_root,
            slug,
            handle_id="wrong-runtime",
            runtime_name="lesson",
            role="lesson-author",
            actual_model="gpt-5.6-sol",
            actual_reasoning_effort="high",
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
    assert plan["runtime"]["reasoning_effort"] == "medium"
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
    activate_presentations(project_root, slug, ["p02"])
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


def test_legacy_migration_uses_three_stages_with_lazy_fixed_lesson_author(
    project_root: Path,
) -> None:
    from mpres.assignments import assignment_contract_status
    from mpres.production_profiles import MIGRATION_STAGES, load_production_profile
    from mpres.state import load_state
    from mpres.stages import stage_status

    slug, task = make_confirmed_task(
        project_root,
        slug="migration-profile-task",
        production_mode="legacy_migration",
    )
    profile = load_production_profile(project_root, slug)
    assert profile["mode"] == "legacy_migration"
    assert tuple(profile["stages"]) == MIGRATION_STAGES
    assert profile["unit_granularity"] == "lesson"
    assert profile["lesson_author_policy"]["one_fixed_author_per_lesson"] is True

    initialize_production(
        project_root,
        slug,
        ["p01::迁移课件一", "p02::迁移课件二"],
        ["p01::u01::第一节", "p02::u02::第二节"],
    )
    lesson_root = task / "workers" / "lesson-authors"
    assert not lesson_root.exists(), "lesson workspaces must remain lazy at metadata init"
    assert not (task / "workers" / "review-coordinator").exists()
    assert not (task / "workers" / "release-coordinator").exists()

    assignment = approve_batch_and_queue_unit(project_root, slug, task)
    assert assignment.is_file()
    contract = assignment_contract_status(assignment)
    assert contract["approved"] is True
    assert contract["decision"]["written_by"] == "planner-via-approved-batch"
    assert contract["decision"]["semantic_owner"] == "planner"

    stages = stage_status(project_root, slug, "p01", "u01")
    assert tuple(stages["stage_order"]) == MIGRATION_STAGES
    assert "01_scope_sources" not in stages["stage_order"]
    state = load_state(project_root, slug)
    p01, p02 = state["presentations"]
    assert p01["content_units"][0]["global_meeting_number"] == 1
    assert p01["content_units"][0]["deck_local_ordinal"] == 1
    assert p02["content_units"][0]["global_meeting_number"] == 2
    assert p02["content_units"][0]["deck_local_ordinal"] == 1
    assert not (lesson_root / "p02" / "u02").exists()


def test_main_agent_is_exclusive_only_for_task_md(project_root: Path) -> None:
    import tomllib

    policy = read_yaml(project_root / "MODEL-POLICY.yaml")
    assert policy["selection_scope"] == "task"
    assert policy["agent_may_select_or_modify_runtime"] is False
    delegated = tomllib.loads(
        (project_root / ".codex" / "agents" / "delegated-planner.toml").read_text(
            encoding="utf-8"
        )
    )
    assert "model" not in delegated
    assert "model_reasoning_effort" not in delegated
    assert "main agent alone writes or revises the top-level TASK.md" in delegated[
        "developer_instructions"
    ]
    task_template = (project_root / "templates" / "TASK.template.md").read_text(
        encoding="utf-8"
    )
    assert "其它 planner 工作均可委派" in task_template
    assert "batch plan" in task_template


def test_review_revision_and_release_roles_are_created_just_in_time(
    project_root: Path,
) -> None:
    from mpres.rendering import render_presentation
    from mpres.review import request_review
    from mpres.state import REVIEW_CHANNELS

    from .conftest import prepare_author_source

    slug, task = initialize_one_deck(project_root, slug="jit-roles-task")
    prepare_author_source(project_root, slug, task)
    assert not (task / "workers" / "review-coordinator").exists()
    assert not (task / "workers" / "specialist-reviewers").exists()
    assert not (task / "workers" / "deck-revision-author").exists()
    assert not (task / "workers" / "release-coordinator").exists()

    assert render_presentation(
        project_root, slug, "p01", stage="author", timeout=60
    )["success"]
    request_review(project_root, slug, "p01")

    review_plan = read_yaml(task / "reviews" / "p01" / "REVIEW-PLAN.yaml")
    assert review_plan["scope"] == "full_deck"
    assert review_plan["all_five_reviewers_read_entire_deck"] is True
    assert tuple(review_plan["channels"]) == REVIEW_CHANNELS
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
        assert assignment.is_file()
    assert (task / "workers" / "review-coordinator").is_dir()
    assert not (task / "workers" / "deck-revision-author").exists()
    assert not (task / "workers" / "release-coordinator").exists()


def test_engine_incident_forces_policy_amendment_without_hot_patch(
    project_root: Path,
) -> None:
    from mpres.engine_incidents import record_engine_incident
    from mpres.state import load_state

    slug, task = initialize_one_deck(project_root, slug="engine-incident-task")
    result = record_engine_incident(
        project_root,
        slug,
        incident_id="marp-dom-regression",
        symptom="The inspector cannot recognize the supported slide DOM.",
        reproduction=["Render the smoke fixture.", "Run the HTML layout inspector."],
        blocked_operation="author freeze gate",
    )
    incident = read_yaml(task / "engine-incidents" / "marp-dom-regression.yaml")
    assert incident["in_task_engine_edit_allowed"] is False
    assert incident["status"] == "awaiting_policy_amendment"
    assert "Do not hot-patch" in incident["required_action"]
    amendment = result["policy_amendment"]
    assert amendment["fields_to_change"] == ["workflow_engine_technical_fix"]
    assert amendment["requires_TASK_reconfirmation"] is True
    state = load_state(project_root, slug)
    assert state["pending_policy_change_request"] == "engine-marp-dom-regression"



def test_legacy_migration_uses_exactly_three_stages_and_delegated_batch_expansion(
    project_root: Path,
) -> None:
    slug, task = initialize_one_deck(
        project_root,
        slug="migration-profile-task",
        production_mode="legacy_migration",
    )
    state = load_state(project_root, slug)
    assert state["production_mode"] == "legacy_migration"
    assert state["stage_profile"] == "migration_three"
    assert not (task / "workers" / "lesson-authors" / "p01" / "u01").exists()

    assignment = approve_batch_and_queue_unit(project_root, slug, task)
    from mpres.stages import stage_status

    stage = stage_status(project_root, slug, "p01", "u01")
    assert tuple(stage["stage_order"]) == MIGRATION_STAGES
    assert (
        "one fixed lesson-author thread"
        in assignment.read_text(encoding="utf-8").lower()
    )
    decision = read_yaml(contract_paths(assignment)[2])
    assert decision["written_by"] == "planner-via-approved-batch"
    assert decision["semantic_owner"] == "planner"
    assert decision["planner_actor"] == "delegated-planner:test"

    policy = read_yaml(task / "EXECUTION-POLICY.yaml")
    assert policy["planner_delegation"]["main_agent_exclusive"] == [
        "write_or_revise_TASK_md"
    ]
    assert (
        policy["planner_delegation"]["all_other_planner_operations_may_be_delegated"]
        is True
    )


def test_future_deck_workspaces_are_lazy_and_critical_path_activation_is_ordered(
    project_root: Path,
) -> None:
    slug, task = make_confirmed_task(project_root, slug="lazy-deck-task")
    initialize_production(
        project_root,
        slug,
        ["p01::第一份课件", "p02::第二份课件", "p03::第三份课件"],
        [
            "p01::u01::第一节课",
            "p02::u02::第二节课",
            "p03::u03::第三节课",
        ],
    )
    author_root = task / "workers" / "author-coordinator" / "drafts"
    assert (author_root / "p01").is_dir()
    assert not (author_root / "p02").exists()
    assert not (author_root / "p03").exists()
    assert not (task / "workers" / "specialist-reviewers").exists()
    assert not (task / "workers" / "deck-revision-author").exists()
    assert not (task / "workers" / "release-coordinator").exists()

    activated = activate_presentations(project_root, slug, ["p02"])
    assert activated["active_presentations"] == ["p01", "p02"]
    assert (author_root / "p02").is_dir()
    assert not (author_root / "p03").exists()
    with pytest.raises(MPresError, match="Critical-path activation"):
        activate_presentations(project_root, slug, ["p03"])


def test_freeze_materializes_five_full_deck_reviewers_but_not_revision_or_release(
    project_root: Path,
) -> None:
    slug, task = initialize_one_deck(project_root, slug="full-deck-review-task")
    source = prepare_author_source(project_root, slug, task)
    assert (source / "AUTHOR-CONTEXT-PACKET.yaml").is_file()
    packet = read_yaml(source / "AUTHOR-CONTEXT-PACKET.yaml")
    assert packet["one_fixed_author_per_lesson"] is True
    assert packet["original_lesson_author_threads_may_be_closed"] is True
    assert packet["all_other_planner_work_may_be_delegated"] is True

    from mpres.rendering import render_presentation

    assert render_presentation(project_root, slug, "p01", stage="author", timeout=60)[
        "success"
    ]
    request_review(project_root, slug, "p01")
    plan = read_yaml(task / "reviews" / "p01" / "REVIEW-PLAN.yaml")
    assert plan["scope"] == "full_deck"
    assert plan["all_five_reviewers_read_entire_deck"] is True
    assert tuple(plan["channels"]) == REVIEW_CHANNELS
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
        assert assignment.is_file()
        text = assignment.read_text(encoding="utf-8").lower()
        assert "entire" in text and "frozen deck" in text
    assert not (task / "workers" / "deck-revision-author").exists()
    assert not (task / "workers" / "release-coordinator").exists()


def test_engine_bug_pauses_task_and_requires_reconfirmed_policy_amendment(
    project_root: Path,
) -> None:
    from mpres.policy import confirm_policy_change
    from mpres.tasks import confirm_task, present_task

    slug, task = initialize_one_deck(project_root, slug="engine-incident-task")
    incident = record_engine_incident(
        project_root,
        slug,
        incident_id="marp-dom-regression",
        symptom="The pinned inspector cannot identify the supported slide DOM.",
        reproduction=["Render the three-slide fixture.", "Observe a zero-slide match."],
        blocked_operation="author render gate",
    )
    assert incident["in_task_engine_edit_allowed"] is False
    assert incident["status"] == "awaiting_policy_amendment"
    state = load_state(project_root, slug)
    assert state["pending_policy_change_request"] == "engine-marp-dom-regression"
    with pytest.raises(MPresError, match="policy amendment"):
        author_launch_plan(project_root, slug, "p01")

    with (task / "TASK.md").open("a", encoding="utf-8") as handle:
        handle.write(
            "\n\nPolicy amendment: suspend the affected render path; workflow-engine refactoring "
            "remains separate work and no in-task hot patch is authorized."
        )
    present_task(project_root, slug)
    confirm_task(project_root, slug)
    confirmed = confirm_policy_change(
        project_root,
        slug,
        request_id="engine-marp-dom-regression",
    )
    assert confirmed["status"] == "confirmed"
    assert "pending_policy_change_request" not in load_state(project_root, slug)


def test_render_refuses_a_marp_binary_that_differs_from_the_exact_lock(
    project_root: Path,
) -> None:
    initialize_one_deck(project_root, slug="marp-version-mismatch-task")
    install_fake_marp(project_root, version="9.9.9")
    with pytest.raises(MPresError, match="Pinned Marp version mismatch"):
        require_pinned_marp(project_root)
