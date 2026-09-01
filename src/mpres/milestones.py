from __future__ import annotations

from pathlib import Path
from typing import Any

from mpres.util import read_json, task_path, utc_now, write_json_atomic

MILESTONES = {
    "task_confirmed",
    "production_initialized",
    "batch_plan_approved",
    "unit_queued",
    "unit_handoff",
    "deck_frozen",
    "review_aggregated",
    "revision_handoff",
    "release_ready",
    "delivered",
}


def record_milestone(
    root: Path,
    slug: str,
    milestone: str,
    *,
    presentation_id: str | None = None,
    unit_id: str | None = None,
    data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if milestone not in MILESTONES:
        raise ValueError(f"Unknown milestone: {milestone}")
    state_dir = task_path(root, slug) / "state"
    state_dir.mkdir(parents=True, exist_ok=True)
    path = state_dir / "MILESTONE-CHECKPOINT.json"
    previous = read_json(path) if path.is_file() else {"schema_version": 1, "events": []}
    events = list(previous.get("events") or [])
    event = {
        "sequence": len(events) + 1,
        "utc": utc_now(),
        "milestone": milestone,
        "presentation_id": presentation_id,
        "unit_id": unit_id,
        "data": data or {},
    }
    events.append(event)
    value = {"schema_version": 1, "latest": event, "events": events[-200:]}
    write_json_atomic(path, value)
    return event
