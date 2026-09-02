from __future__ import annotations

from pathlib import Path

import pytest

from mpres.production import activate_presentations, initialize_production
from mpres.review import request_review
from mpres.scheduling import (
    NEXT_AUTHORING_OVERLAP_STATUSES,
    current_allows_next_authoring,
    rebalance_active_presentations,
    refresh_active_presentation_window,
)
from mpres.state import load_state, save_state
from mpres.util import read_yaml, write_yaml_atomic

from .conftest import make_confirmed_task, prepare_author_source


def _initialize_three_decks(
    root: Path,
    *,
    slug: str,
    stop_mode: str = "all",
) -> tuple[str, Path]:
    slug, task = make_confirmed_task(root, slug=slug, stop_mode=stop_mode)
    initialize_production(
        root,
        slug,
        ["p01::第一份", "p02::第二份", "p03::第三份"],
        ["p01::u01::第一课", "p02::u02::第二课", "p03::u03::第三课"],
    )
    return slug, task


@pytest.mark.parametrize("current_status", sorted(NEXT_AUTHORING_OVERLAP_STATUSES))
def test_rebalance_keeps_exactly_one_next_lane_for_every_active_current_status(
    project_root: Path,
    current_status: str,
) -> None:
    slug, _ = _initialize_three_decks(
        project_root, slug=f"rebalance-{current_status.replace('_', '-')}"
    )
    state = load_state(project_root, slug)
    state["presentations"][0]["status"] = current_status
    for row in state["presentations"]:
        row["active"] = row["id"] == "p01"

    result = rebalance_active_presentations(project_root, slug, state)

    assert current_allows_next_authoring(current_status) is True
    assert result["active_presentations"] == ["p01", "p02"]
    assert [row["id"] for row in state["presentations"] if row["active"]] == ["p01", "p02"]
    assert state["presentations"][2]["active"] is False


@pytest.mark.parametrize("current_status", ["review_requested", "reviewing", "author_revision", "release_ready"])
def test_explicit_activation_allows_recovery_after_current_left_authoring(
    project_root: Path,
    current_status: str,
) -> None:
    slug, task = _initialize_three_decks(
        project_root, slug=f"activate-{current_status.replace('_', '-')}"
    )
    state = load_state(project_root, slug)
    state["presentations"][0]["status"] = current_status
    save_state(project_root, slug, state)

    result = activate_presentations(project_root, slug, ["p02"])

    assert result["active_presentations"] == ["p01", "p02"]
    assert (
        task
        / "workers"
        / "author-coordinator"
        / "assignments"
        / "p02"
        / "TASK-AUTHOR-COORDINATOR.md"
    ).is_file()
    assert not (task / "workers" / "author-coordinator" / "drafts" / "p03").exists()


def test_freeze_automatically_opens_and_materializes_next_lane_in_all_mode(
    project_root: Path,
) -> None:
    slug, task = _initialize_three_decks(project_root, slug="freeze-opens-next")
    prepare_author_source(project_root, slug, task)
    from mpres.rendering import render_presentation

    assert render_presentation(project_root, slug, "p01", stage="author", timeout=60)["success"]
    request_review(project_root, slug, "p01")

    state = load_state(project_root, slug)
    assert state["presentations"][0]["status"] == "review_requested"
    assert [row["id"] for row in state["presentations"] if row["active"]] == ["p01", "p02"]
    assert (task / "workers" / "author-coordinator" / "drafts" / "p02").is_dir()
    assert not (task / "workers" / "author-coordinator" / "drafts" / "p03").exists()

    plan = read_yaml(task / "PRESENTATION-WORK-PLAN.yaml")
    rows = {row["id"]: row for row in plan["presentations"]}
    assert rows["p01"]["state"] == "current"
    assert rows["p01"]["review_wip"] is True
    assert rows["p02"]["state"] == "next_active"
    assert rows["p02"]["authoring_wip"] is True
    assert rows["p03"]["state"] == "future"


@pytest.mark.parametrize("stop_mode", ["each", "pilot"])
def test_initial_pause_modes_keep_next_lane_closed(
    project_root: Path,
    stop_mode: str,
) -> None:
    slug, task = _initialize_three_decks(
        project_root, slug=f"pause-{stop_mode}", stop_mode=stop_mode
    )
    state = load_state(project_root, slug)
    state["presentations"][0]["status"] = "reviewing"

    result = refresh_active_presentation_window(project_root, slug, state)

    assert result["active_presentations"] == ["p01"]
    assert not (task / "workers" / "author-coordinator" / "drafts" / "p02").exists()


def test_zero_next_wip_limit_keeps_lane_closed(project_root: Path) -> None:
    slug, task = _initialize_three_decks(project_root, slug="zero-next-limit")
    policy_path = task / "EXECUTION-POLICY.yaml"
    policy = read_yaml(policy_path)
    policy["authoring"]["next_presentation_authoring_wip_limit"] = 0
    write_yaml_atomic(policy_path, policy)
    state = load_state(project_root, slug)
    state["presentations"][0]["status"] = "author_revision"

    result = refresh_active_presentation_window(project_root, slug, state)

    assert result["active_presentations"] == ["p01"]
    assert not (task / "workers" / "author-coordinator" / "drafts" / "p02").exists()


def test_unknown_and_terminal_states_fail_closed() -> None:
    assert current_allows_next_authoring(None) is False
    assert current_allows_next_authoring("finalized") is False
    assert current_allows_next_authoring("unexpected") is False
