from __future__ import annotations

from pathlib import Path
from typing import Any

from mpres.production import check_assignment
from mpres.state import REVIEW_CHANNELS, get_presentation, load_state
from mpres.stages import stage_status
from mpres.tasks import require_gate
from mpres.threads import capacity_preflight, expected_runtime, list_threads
from mpres.util import MPresError, relative_display, task_path, utc_now, write_json_atomic


def _idle_handles(root: Path, slug: str, role: str) -> list[dict[str, Any]]:
    expected = expected_runtime(root, role)
    registry = list_threads(root, slug)
    return [
        item
        for item in registry.get("handles", [])
        if isinstance(item, dict)
        and item.get("state") == "idle_reusable"
        and role in (item.get("reusable_for") or [item.get("role")])
        and item.get("actual_model") == expected["model"]
        and item.get("actual_reasoning_effort") == expected["reasoning_effort"]
    ]


def author_launch_plan(root: Path, slug: str, presentation_id: str, *, save: bool = False) -> dict[str, Any]:
    """Build a deterministic current launch plan without starting agents or creating a journal."""

    state = require_gate(root, slug)
    presentation = get_presentation(state, presentation_id)
    if not presentation.get("active"):
        raise MPresError(f"Presentation {presentation_id} is not active.")
    units: list[dict[str, Any]] = []
    for unit in presentation.get("content_units", []):
        unit_id = str(unit["id"])
        assignment = check_assignment(root, slug, "lesson-author", presentation_id, unit_id=unit_id)
        stage = stage_status(root, slug, presentation_id, unit_id)
        if stage.get("sequence_status") == "completed":
            action = "none_completed"
        elif not assignment.get("ready"):
            action = "planner_must_finish_assignment"
        elif stage.get("sequence_status") in {"awaiting_start", "reopened"}:
            action = "start_or_reuse_lesson_author"
        else:
            action = "resume_same_lesson_author_thread"
        units.append(
            {
                "unit_id": unit_id,
                "title": unit.get("title"),
                "assignment": assignment,
                "sequence_status": stage.get("sequence_status"),
                "current_stage": stage.get("current_stage"),
                "thread_handle": stage.get("thread_handle"),
                "action": action,
            }
        )
    needing_handle = [
        row for row in units if row["action"] == "start_or_reuse_lesson_author" and not row.get("thread_handle")
    ]
    reusable = _idle_handles(root, slug, "lesson-author")
    new_handles = max(0, len(needing_handle) - len(reusable))
    capacity = capacity_preflight(root, slug, requested=new_handles)
    result = {
        "schema_version": 1,
        "generated_utc": utc_now(),
        "kind": "author-launch-plan",
        "task_slug": slug,
        "presentation_id": presentation_id,
        "status": presentation.get("status"),
        "runtime": expected_runtime(root, "lesson-author"),
        "reusable_handle_ids": [str(item.get("handle_id")) for item in reusable],
        "new_handles_needed": new_handles,
        "capacity": capacity,
        "units": units,
        "journal_policy": "none; current plan only",
    }
    if save:
        path = task_path(root, slug) / "state" / f"author-launch-plan-{presentation_id}.json"
        write_json_atomic(path, result)
        result["path"] = relative_display(path, root)
    return result


def review_launch_plan(root: Path, slug: str, presentation_id: str, *, save: bool = False) -> dict[str, Any]:
    """Build a deterministic five-channel launch plan from current review state."""

    state = require_gate(root, slug)
    presentation = get_presentation(state, presentation_id)
    if presentation.get("status") not in {"review_requested", "reviewing"}:
        raise MPresError("Review launch planning requires review_requested or reviewing status.")
    submitted = presentation.get("rounds", {}).get("full", {}).get("channels", {})
    channels: list[dict[str, Any]] = []
    for channel in REVIEW_CHANNELS:
        assignment = check_assignment(
            root,
            slug,
            "specialist-reviewer",
            presentation_id,
            round_name="full",
            channel=channel,
        )
        channels.append(
            {
                "channel": channel,
                "assignment": assignment,
                "submitted": channel in submitted,
                "action": (
                    "none_submitted"
                    if channel in submitted
                    else "planner_must_finish_assignment"
                    if not assignment.get("ready")
                    else "start_or_reuse_independent_reviewer"
                ),
            }
        )
    pending = [row for row in channels if row["action"] == "start_or_reuse_independent_reviewer"]
    reusable = _idle_handles(root, slug, "specialist-reviewer")
    new_handles = max(0, len(pending) - len(reusable))
    capacity = capacity_preflight(root, slug, requested=new_handles)
    result = {
        "schema_version": 1,
        "generated_utc": utc_now(),
        "kind": "review-launch-plan",
        "task_slug": slug,
        "presentation_id": presentation_id,
        "status": presentation.get("status"),
        "runtime": expected_runtime(root, "specialist-reviewer"),
        "reusable_handle_ids": [str(item.get("handle_id")) for item in reusable],
        "new_handles_needed": new_handles,
        "capacity": capacity,
        "channels": channels,
        "journal_policy": "none; current plan only",
    }
    if save:
        path = task_path(root, slug) / "state" / f"review-launch-plan-{presentation_id}.json"
        write_json_atomic(path, result)
        result["path"] = relative_display(path, root)
    return result
