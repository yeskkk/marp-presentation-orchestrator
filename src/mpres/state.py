from __future__ import annotations

from pathlib import Path
from typing import Any

from mpres.util import MPresError, read_json, safe_id, task_path, utc_now, write_json_atomic

SCHEMA_VERSION = 1
REVIEW_ROUNDS = ("initial", "incremental", "final")
REVIEW_CHANNELS = ("language", "domain_accuracy", "layout", "pedagogy", "audience")
PRESENTATION_STATUSES = {
    "authoring",
    "initial_review_requested",
    "initial_reviewing",
    "initial_changes",
    "incremental_review_requested",
    "incremental_reviewing",
    "incremental_changes",
    "final_review_requested",
    "final_reviewing",
    "terminal_revision",
    "release_closure_requested",
    "release_approved",
    "finalized",
}


def state_file(root: Path, slug: str) -> Path:
    return task_path(root, slug) / "state" / "task.json"


def load_state(root: Path, slug: str) -> dict[str, Any]:
    data = read_json(state_file(root, slug))
    if data.get("schema_version") != SCHEMA_VERSION:
        raise MPresError(
            f"Unsupported task state schema {data.get('schema_version')!r}; expected {SCHEMA_VERSION}."
        )
    return data


def save_state(root: Path, slug: str, data: dict[str, Any]) -> None:
    data["updated_utc"] = utc_now()
    write_json_atomic(state_file(root, slug), data)


def get_presentation(state: dict[str, Any], presentation_id: str) -> dict[str, Any]:
    safe_id(presentation_id, label="presentation ID")
    for item in state.get("presentations", []):
        if item.get("id") == presentation_id:
            return item
    raise MPresError(f"Unknown presentation ID: {presentation_id}")


def get_content_unit(presentation: dict[str, Any], unit_id: str) -> dict[str, Any]:
    safe_id(unit_id, label="content-unit ID")
    for item in presentation.get("content_units", []):
        if item.get("id") == unit_id:
            return item
    raise MPresError(f"Unknown content-unit ID {unit_id!r} in {presentation.get('id')!r}.")
