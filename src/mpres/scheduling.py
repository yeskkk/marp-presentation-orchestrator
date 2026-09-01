from __future__ import annotations

from pathlib import Path
from typing import Any

from mpres.state import get_content_unit, get_presentation, load_state, save_state
from mpres.tasks import require_gate
from mpres.util import MPresError, read_yaml, relative_display, task_path, utc_now, write_yaml_atomic


def _work_plan_path(root: Path, slug: str) -> Path:
    return task_path(root, slug) / "PRESENTATION-WORK-PLAN.yaml"


def initialize_work_plan(root: Path, slug: str, presentations: list[dict[str, Any]]) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for sequence, presentation in enumerate(presentations, start=1):
        rows.append(
            {
                "id": presentation["id"],
                "sequence": sequence,
                "priority": sequence,
                "state": "current" if sequence == 1 else "future",
                "authoring_wip": sequence == 1,
                "review_wip": False,
                "release_wip": False,
                "units": [
                    {
                        "id": unit["id"],
                        "state": "uninitialized",
                        "queued_utc": None,
                        "ready_wait_alert": False,
                    }
                    for unit in presentation.get("content_units", [])
                ],
            }
        )
    value = {
        "schema_version": 1,
        "generated_utc": utc_now(),
        "policy": {
            "priority_order": [
                "finish_current_review_revision_or_release",
                "finish_current_presentation",
                "start_next_ready_presentation",
                "prepare_future_metadata_without_model_workers",
            ],
            "max_presentations_reviewing": 1,
            "max_current_authoring_presentations": 1,
            "max_next_authoring_presentations": 1,
            "reviewers_before_freeze": False,
            "release_before_release_ready": False,
            "prospective_hold_threads": False,
        },
        "presentations": rows,
    }
    write_yaml_atomic(_work_plan_path(root, slug), value)
    return value


def _load_work_plan(root: Path, slug: str) -> dict[str, Any]:
    value = read_yaml(_work_plan_path(root, slug))
    if not isinstance(value, dict):
        raise MPresError("PRESENTATION-WORK-PLAN.yaml is missing or malformed.")
    return value



def _activation_limits(root: Path, slug: str, *, state: dict[str, Any]) -> tuple[int, int]:
    policy = read_yaml(task_path(root, slug) / "EXECUTION-POLICY.yaml") or {}
    authoring = policy.get("authoring", {}) if isinstance(policy, dict) else {}
    current_limit = max(1, int(authoring.get("current_presentation_wip_limit", 1) or 1))
    next_limit = max(0, int(authoring.get("next_presentation_authoring_wip_limit", 1) or 0))
    stop_mode = str(state.get("stop_mode") or "all")
    if stop_mode == "each" or (stop_mode == "pilot" and not state.get("pilot_pause_completed")):
        next_limit = 0
    return current_limit, next_limit


def rebalance_active_presentations(
    root: Path,
    slug: str,
    state: dict[str, Any],
    *,
    allow_next: bool = True,
) -> dict[str, Any]:
    """Keep only the current presentation and the permitted next authoring presentation active.

    The current presentation remains the earliest non-finalized presentation, regardless of whether
    it is authoring, reviewing, in deck revision, or release-ready. A second active presentation is
    permitted only when it is the earliest later presentation still in authoring and the task's
    delivery mode allows a next-authoring lane.
    """

    remaining = [
        item for item in state.get("presentations", []) if item.get("status") != "finalized"
    ]
    previous = {
        str(item.get("id"))
        for item in state.get("presentations", [])
        if item.get("active") and item.get("status") != "finalized"
    }
    desired: list[str] = []
    if remaining:
        current = remaining[0]
        desired.append(str(current.get("id")))
        current_limit, next_limit = _activation_limits(root, slug, state=state)
        # The workflow currently has one ordered current lane. Values above one are accepted in
        # policy for forward compatibility but do not create multiple competing "current" decks.
        del current_limit
        if allow_next and current.get("status") == "authoring" and next_limit > 0:
            for item in remaining[1:]:
                if item.get("status") == "authoring":
                    desired.append(str(item.get("id")))
                    next_limit -= 1
                    if next_limit <= 0:
                        break
        state["critical_path_presentation"] = str(current.get("id"))
    else:
        state["critical_path_presentation"] = None
    desired_set = set(desired)
    for item in state.get("presentations", []):
        item["active"] = item.get("status") != "finalized" and str(item.get("id")) in desired_set
    return {
        "active_presentations": desired,
        "activated": sorted(desired_set - previous),
        "deactivated": sorted(previous - desired_set),
    }


def sync_work_plan(
    root: Path,
    slug: str,
    *,
    state: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Project task state into the deterministic human-readable work plan."""

    state = state or load_state(root, slug)
    plan = _load_work_plan(root, slug)
    state_by_id = {str(item.get("id")): item for item in state.get("presentations", [])}
    current_id = next(
        (
            str(item.get("id"))
            for item in state.get("presentations", [])
            if item.get("status") != "finalized"
        ),
        None,
    )
    for row in plan.get("presentations", []):
        pid = str(row.get("id"))
        presentation = state_by_id.get(pid)
        if not presentation:
            continue
        status = str(presentation.get("status") or "authoring")
        if status == "finalized":
            row["state"] = "finalized"
        elif pid == current_id:
            row["state"] = "current"
        elif presentation.get("active"):
            row["state"] = "next_active"
        else:
            row["state"] = "future"
        row["authoring_wip"] = bool(presentation.get("active") and status == "authoring")
        row["review_wip"] = status in {"review_requested", "reviewing"}
        row["revision_wip"] = status == "author_revision"
        row["release_wip"] = status == "release_ready"
        unit_state = {
            str(item.get("id")): item for item in presentation.get("content_units", [])
        }
        for unit in row.get("units", []):
            current = unit_state.get(str(unit.get("id")))
            if current:
                unit["state"] = str(current.get("status") or "uninitialized")
                unit["queued_utc"] = current.get("queued_utc")
    plan["generated_utc"] = utc_now()
    write_yaml_atomic(_work_plan_path(root, slug), plan)
    return plan

def queue_unit(root: Path, slug: str, presentation_id: str, unit_id: str) -> dict[str, Any]:
    """Queue and lazily materialize one unit on the current critical path."""

    require_gate(root, slug)
    state = load_state(root, slug)
    presentation = get_presentation(state, presentation_id)
    if not presentation.get("active"):
        raise MPresError(f"Presentation {presentation_id} is not active on the critical path.")
    if presentation.get("status") != "authoring":
        raise MPresError("Only an authoring presentation may queue a lesson unit.")
    from mpres.production import prepare_unit_workspace

    result = prepare_unit_workspace(root, slug, presentation_id, unit_id)
    state = load_state(root, slug)
    presentation = get_presentation(state, presentation_id)
    state_unit = get_content_unit(presentation, unit_id)
    queued_utc = utc_now()
    state_unit["status"] = "queued"
    state_unit["queued_utc"] = queued_utc
    state_unit["stage_status"] = "awaiting_start"
    save_state(root, slug, state)
    plan = _load_work_plan(root, slug)
    for row in plan.get("presentations", []):
        if row.get("id") != presentation_id:
            continue
        for unit in row.get("units", []):
            if unit.get("id") == unit_id:
                unit["state"] = "queued"
                unit["queued_utc"] = queued_utc
                unit["ready_wait_alert"] = False
    write_yaml_atomic(_work_plan_path(root, slug), plan)
    sync_work_plan(root, slug, state=state)
    return {
        **result,
        "status": "queued",
        "queued_utc": queued_utc,
        "work_plan": relative_display(_work_plan_path(root, slug), root),
    }


def critical_path_plan(root: Path, slug: str) -> dict[str, Any]:
    state = require_gate(root, slug)
    plan = sync_work_plan(root, slug, state=state)
    reviewing = [p for p in state.get("presentations", []) if p.get("status") in {"review_requested", "reviewing"}]
    if len(reviewing) > 1:
        raise MPresError("Critical-path policy permits at most one presentation in review.")
    current: dict[str, Any] | None = None
    next_presentation: dict[str, Any] | None = None
    for presentation in state.get("presentations", []):
        if current is None and presentation.get("status") != "finalized":
            current = presentation
            continue
        if current is not None and next_presentation is None and presentation.get("status") == "authoring":
            next_presentation = presentation
            break
    action = "task_complete"
    if current:
        status = str(current.get("status"))
        if status in {"review_requested", "reviewing"}:
            action = "finish_current_review"
        elif status == "author_revision":
            action = "finish_deck_revision"
        elif status == "release_ready":
            action = "finish_release"
        elif status == "authoring":
            units = current.get("content_units", [])
            queued = [u for u in units if u.get("status") in {"assignment_ready", "queued", "running", "handoff_ready"}]
            uninitialized = [u for u in units if u.get("status") in {None, "uninitialized", "initialized"}]
            action = "finish_current_units" if queued else "queue_next_current_unit" if uninitialized else "assemble_and_freeze"
    return {
        "schema_version": 1,
        "generated_utc": utc_now(),
        "task_slug": slug,
        "action": action,
        "current_presentation": current.get("id") if current else None,
        "next_presentation": next_presentation.get("id") if next_presentation else None,
        "reviewing_count": len(reviewing),
        "rules": plan.get("policy"),
    }
