from __future__ import annotations

from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from mpres.production_profiles import (
    COURSE_FULL_STAGES,
    MIGRATION_STAGES,
    REPORT_COMPACT_STAGES,
    TARGETED_REVISION_STAGES,
    stage_ids_for_profile,
)
from mpres.transactions import (
    ConcurrentStateUpdateError,
    database_path,
    initialize_document,
    read_document,
    save_document,
    transaction_status,
    update_document,
)
from mpres.util import MPresError, safe_id, task_path, utc_now

SCHEMA_VERSION = 5
STATE_DOCUMENT_ID = "task-state"
STATE_REVISION_FIELD = "state_revision"
REVIEW_ROUNDS = ("full",)
REVIEW_CHANNELS = ("language", "domain_accuracy", "layout", "pedagogy", "audience")
PRESENTATION_STATUSES = {
    "authoring",
    "review_requested",
    "reviewing",
    "author_revision",
    "release_ready",
    "finalized",
}
COURSE_STAGE_IDS = COURSE_FULL_STAGES
REPORT_STAGE_IDS = REPORT_COMPACT_STAGES
MIGRATION_STAGE_IDS = MIGRATION_STAGES
REVISION_STAGE_IDS = TARGETED_REVISION_STAGES
UNIT_STAGE_IDS = COURSE_STAGE_IDS
UNIT_STATUSES = {
    "uninitialized",
    "initialized",
    "assignment_ready",
    "queued",
    "running",
    "handoff_ready",
    "integrated",
}


def stage_ids_for_kind(kind: str, production_mode: str | None = None) -> tuple[str, ...]:
    """Return the task-configured stage sequence.

    ``production_mode`` is optional for compatibility with pre-profile callers. New code must pass it or
    use the task's PRODUCTION-PROFILE.yaml.
    """

    if production_mode:
        return stage_ids_for_profile(production_mode, kind)
    if kind == "course":
        return COURSE_STAGE_IDS
    if kind == "report":
        return REPORT_STAGE_IDS
    raise MPresError(f"Unsupported task kind: {kind!r}.")


def state_file(root: Path, slug: str) -> Path:
    return task_path(root, slug) / "state" / "task.json"


def _validate_state(data: Mapping[str, Any]) -> None:
    if data.get("schema_version") != SCHEMA_VERSION:
        raise MPresError(
            f"Unsupported task state schema {data.get('schema_version')!r}; "
            f"expected {SCHEMA_VERSION}."
        )
    revision = data.get(STATE_REVISION_FIELD)
    if isinstance(revision, bool) or not isinstance(revision, int) or revision < 0:
        raise MPresError(
            f"Task state field {STATE_REVISION_FIELD!r} must be a non-negative integer."
        )


def initialize_state(root: Path, slug: str, data: dict[str, Any]) -> dict[str, Any]:
    """Initialize the SQLite canonical state and JSON projection for a new task."""

    value = dict(data)
    value.setdefault(STATE_REVISION_FIELD, 0)
    _validate_state(value)
    initialized = initialize_document(
        root,
        slug,
        document_id=STATE_DOCUMENT_ID,
        payload=value,
        projection_path=state_file(root, slug),
        projection_format="json",
        revision_field=STATE_REVISION_FIELD,
    )
    data.clear()
    data.update(initialized)
    return data


def load_state(root: Path, slug: str) -> dict[str, Any]:
    """Load canonical task state and repair/import the JSON projection as needed."""

    data = read_document(
        root,
        slug,
        document_id=STATE_DOCUMENT_ID,
        projection_path=state_file(root, slug),
        projection_format="json",
        revision_field=STATE_REVISION_FIELD,
    )
    _validate_state(data)
    return data


def save_state(root: Path, slug: str, data: dict[str, Any]) -> None:
    """Commit one loaded state snapshot with optimistic revision validation.

    Normal control-plane mutators run inside ``transactional_task_mutation`` and
    therefore serialize automatically. Direct callers are still protected: a
    stale snapshot raises ``ConcurrentStateUpdateError`` rather than silently
    replacing a newer update.
    """

    data["updated_utc"] = utc_now()
    _validate_state(data)
    updated = save_document(
        root,
        slug,
        document_id=STATE_DOCUMENT_ID,
        payload=data,
        projection_path=state_file(root, slug),
        projection_format="json",
        revision_field=STATE_REVISION_FIELD,
    )
    data.clear()
    data.update(updated)


def mutate_state(
    root: Path,
    slug: str,
    mutator: Callable[[dict[str, Any]], Mapping[str, Any] | None],
) -> dict[str, Any]:
    """Atomically re-read and mutate canonical task state under the writer transaction."""

    def wrapped(data: dict[str, Any]) -> Mapping[str, Any] | None:
        _validate_state(data)
        result = mutator(data)
        value = data if result is None else dict(result)
        value["updated_utc"] = utc_now()
        _validate_state(value)
        return value

    return update_document(
        root,
        slug,
        document_id=STATE_DOCUMENT_ID,
        projection_path=state_file(root, slug),
        projection_format="json",
        revision_field=STATE_REVISION_FIELD,
        mutator=wrapped,
    )


def mutable_state_status(root: Path, slug: str) -> dict[str, Any]:
    """Return transaction metadata, importing both v0.6.3 projections if needed."""

    load_state(root, slug)
    read_document(
        root,
        slug,
        document_id="thread-registry",
        projection_path=task_path(root, slug) / "THREAD-REGISTRY.yaml",
        projection_format="yaml",
        revision_field="registry_revision",
    )
    value = transaction_status(root, slug)
    value["task_state_database"] = str(database_path(root, slug))
    return value


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


__all__ = [
    "ConcurrentStateUpdateError",
    "SCHEMA_VERSION",
    "STATE_REVISION_FIELD",
    "load_state",
    "save_state",
    "initialize_state",
    "mutate_state",
    "mutable_state_status",
]
