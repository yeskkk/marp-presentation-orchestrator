from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from mpres.production import initialize_production
from mpres.tasks import confirm_task, create_task, gate_status, present_task
from mpres.threads import expected_runtime
from mpres.tokens import import_session, token_report
from mpres.util import MPresError, read_json
from tests.conftest import fill_placeholders, make_confirmed_task


def _finish_task_md(task: Path) -> None:
    fill_placeholders(task / "TASK.md")
    with (task / "TASK.md").open("a", encoding="utf-8") as handle:
        handle.write("\n\n" + "完整任务范围、听众、资料、执行策略和验收标准。" * 200)


def test_default_runtime_profile_is_task_local(project_root: Path) -> None:
    slug, task = make_confirmed_task(project_root, slug="runtime-defaults")
    profile = yaml.safe_load((task / "TASK-RUNTIME-PROFILE.yaml").read_text(encoding="utf-8"))
    assert profile["defaults"] == {
        "planner": {"model": "gpt-5.6-sol", "reasoning_effort": "high"},
        "author": {"model": "gpt-5.6-sol", "reasoning_effort": "medium"},
        "reviewer": {"model": "gpt-5.6-sol", "reasoning_effort": "low"},
    }
    state = read_json(task / "state" / "task.json")
    assert state["confirmed_runtime_profile"]["defaults"] == profile["defaults"]
    assert expected_runtime(project_root, slug, "lesson-author")["reasoning_effort"] == "medium"


def test_user_may_refine_runtime_before_confirmation_but_agent_cannot_change_it_later(
    project_root: Path,
) -> None:
    slug, task = create_task(
        root=project_root,
        title="运行配置测试",
        slug="runtime-refinement",
        kind="course",
        stop_mode="all",
        sessions=1,
        minutes=40,
    )
    _finish_task_md(task)
    path = task / "TASK-RUNTIME-PROFILE.yaml"
    profile = yaml.safe_load(path.read_text(encoding="utf-8"))
    profile["reviewer_channel_overrides"]["domain_accuracy"] = {
        "model": "gpt-5.6-sol",
        "reasoning_effort": "high",
    }
    path.write_text(yaml.safe_dump(profile, allow_unicode=True, sort_keys=False), encoding="utf-8")
    present_task(project_root, slug)
    confirm_task(project_root, slug)

    assert expected_runtime(
        project_root,
        slug,
        "specialist-reviewer",
        channel="domain_accuracy",
    )["reasoning_effort"] == "high"

    profile["defaults"]["author"]["reasoning_effort"] = "high"
    path.write_text(yaml.safe_dump(profile, allow_unicode=True, sort_keys=False), encoding="utf-8")
    ok, message, _ = gate_status(project_root, slug)
    assert not ok
    assert "changed after task confirmation" in message
    with pytest.raises(MPresError, match="changed after task confirmation"):
        expected_runtime(project_root, slug, "lesson-author")


def test_runtime_profile_change_after_presentation_requires_present_again(project_root: Path) -> None:
    slug, task = create_task(
        root=project_root,
        title="确认快照测试",
        slug="runtime-presented",
        kind="course",
        stop_mode="all",
        sessions=1,
        minutes=40,
    )
    _finish_task_md(task)
    present_task(project_root, slug)
    path = task / "TASK-RUNTIME-PROFILE.yaml"
    profile = yaml.safe_load(path.read_text(encoding="utf-8"))
    profile["defaults"]["reviewer"]["reasoning_effort"] = "medium"
    path.write_text(yaml.safe_dump(profile, allow_unicode=True, sort_keys=False), encoding="utf-8")
    with pytest.raises(MPresError, match="changed after the task was presented"):
        confirm_task(project_root, slug)


def test_production_fails_closed_until_token_collector_is_initialized(project_root: Path) -> None:
    slug, task = create_task(
        root=project_root,
        title="Token collector gate",
        slug="collector-gate",
        kind="course",
        stop_mode="all",
        sessions=1,
        minutes=40,
    )
    _finish_task_md(task)
    present_task(project_root, slug)
    confirm_task(project_root, slug)
    with pytest.raises(MPresError, match="Token collector must be initialized before production"):
        initialize_production(
            project_root,
            slug,
            ["p01::第一份课件"],
            ["p01::u01::第一节内容"],
        )


def test_token_summary_keeps_unknown_values_null(project_root: Path, tmp_path: Path) -> None:
    slug, _ = make_confirmed_task(project_root, slug="token-null")
    source = tmp_path / "usage.jsonl"
    source.write_text(
        json.dumps({"input_tokens": 100, "output_tokens": 20, "total_tokens": 120})
        + "\n"
        + json.dumps({"input_tokens": None, "output_tokens": None, "total_tokens": None})
        + "\n",
        encoding="utf-8",
    )
    import_session(
        project_root,
        slug,
        source,
        presentation_id="p01",
        role="lesson-author",
        unit_id="u01",
        round_name=None,
        channel=None,
        thread_id="t01",
    )
    report = token_report(project_root, slug, group_by="role")
    assert report["status"] == "partial_or_unavailable"
    assert report["coverage"] == 0
    assert report["totals"]["input_tokens"] is None
    assert report["known_totals"]["input_tokens"] == 100
    assert report["unknown_records"]["input_tokens"] == 1
    group = report["groups"][0]
    assert group["totals"]["total_tokens"] is None
    assert group["known_totals"]["total_tokens"] == 120
    assert group["unknown_records"]["total_tokens"] == 1
