from __future__ import annotations

from pathlib import Path
from typing import Any

from mpres.logs import append_log
from mpres.tasks import require_gate
from mpres.util import MPresError, read_json, relative_display, safe_id, task_path, utc_now, write_json_atomic


def checkpoint_path(
    root: Path,
    slug: str,
    role: str,
    presentation_id: str,
    *,
    unit_id: str | None = None,
) -> Path:
    task = task_path(root, slug)
    safe_id(presentation_id, label="presentation ID")
    if role == "author-coordinator":
        return task / "workers" / role / "checkpoints" / presentation_id / "latest.json"
    if role == "lesson-author":
        if not unit_id:
            raise MPresError("lesson-author checkpoint requires --unit.")
        safe_id(unit_id, label="content-unit ID")
        return task / "workers" / "lesson-authors" / presentation_id / unit_id / "checkpoints" / "latest.json"
    if role in {"review-coordinator", "release-coordinator"}:
        return task / "workers" / role / "checkpoints" / presentation_id / "latest.json"
    raise MPresError(f"Unsupported checkpoint role: {role}")


def save_checkpoint(
    root: Path,
    slug: str,
    role: str,
    presentation_id: str,
    *,
    unit_id: str | None,
    completed: list[str],
    decisions: list[str],
    open_issues: list[str],
    next_action: str,
    durable_paths: list[str],
    last_successful_build: str | None,
) -> dict[str, Any]:
    require_gate(root, slug)
    path = checkpoint_path(root, slug, role, presentation_id, unit_id=unit_id)
    record = {
        "schema_version": 1,
        "utc": utc_now(),
        "role": role,
        "presentation_id": presentation_id,
        "unit_id": unit_id,
        "completed": completed,
        "decisions": decisions,
        "open_issues": open_issues,
        "next_action": next_action,
        "last_successful_build": last_successful_build,
        "durable_paths": durable_paths,
    }
    write_json_atomic(path, record)
    actor = f"lesson-author:{unit_id}" if role == "lesson-author" else role
    append_log(
        root,
        slug,
        actor=actor,
        kind="checkpoint",
        presentation_id=presentation_id,
        unit_id=unit_id,
        message=f"Saved durable checkpoint; next action: {next_action}",
        data={"checkpoint": relative_display(path, root)},
    )
    return record


def checkpoint_status(
    root: Path,
    slug: str,
    role: str,
    presentation_id: str,
    *,
    unit_id: str | None,
) -> dict[str, Any]:
    path = checkpoint_path(root, slug, role, presentation_id, unit_id=unit_id)
    return {**read_json(path), "path": relative_display(path, root)}
