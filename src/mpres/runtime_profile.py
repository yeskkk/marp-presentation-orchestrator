from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any, Mapping

from mpres.util import MPresError, read_yaml, task_path

PROFILE_FILENAME = "TASK-RUNTIME-PROFILE.yaml"
REASONING_EFFORTS = {"low", "medium", "high", "max"}
ROLE_FAMILIES = {
    "planner": "planner",
    "main-planner": "planner",
    "delegated-planner": "planner",
    "author": "author",
    "author-coordinator": "author",
    "lesson-author": "author",
    "deck-revision-author": "author",
    "maintenance-author": "author",
    "reviewer": "reviewer",
    "specialist-reviewer": "reviewer",
}
ALLOWED_TOP_LEVEL_KEYS = {
    "schema_version",
    "selection_scope",
    "user_editable_until_task_confirmation",
    "immutable_after_task_confirmation",
    "runtime_changes_during_task",
    "defaults",
    "role_overrides",
    "reviewer_channel_overrides",
    "presentation_overrides",
    "notes",
}


def runtime_profile_path(root: Path, slug: str) -> Path:
    return task_path(root, slug) / PROFILE_FILENAME


def _validate_spec(spec: Any, label: str, *, partial: bool = False) -> dict[str, str]:
    if not isinstance(spec, Mapping):
        raise MPresError(f"{label} must be a mapping.")
    allowed = {"model", "reasoning_effort"}
    unknown = sorted(set(spec) - allowed)
    if unknown:
        raise MPresError(f"{label} contains unsupported keys: {', '.join(unknown)}")
    model = spec.get("model")
    effort = spec.get("reasoning_effort")
    if not partial or model is not None:
        if not isinstance(model, str) or not model.strip():
            raise MPresError(f"{label}.model must be a non-empty user-selected model ID.")
    if not partial or effort is not None:
        if effort not in REASONING_EFFORTS:
            raise MPresError(
                f"{label}.reasoning_effort must be one of {sorted(REASONING_EFFORTS)}."
            )
    return {
        **({"model": model.strip()} if isinstance(model, str) and model.strip() else {}),
        **({"reasoning_effort": str(effort)} if effort is not None else {}),
    }


def normalize_runtime_profile(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise MPresError(f"{PROFILE_FILENAME} must contain a mapping.")
    unknown = sorted(set(value) - ALLOWED_TOP_LEVEL_KEYS)
    if unknown:
        raise MPresError(
            f"{PROFILE_FILENAME} contains unsupported top-level keys: {', '.join(unknown)}"
        )
    if value.get("schema_version") != 1:
        raise MPresError(f"{PROFILE_FILENAME} schema_version must be 1.")
    if value.get("selection_scope") != "task":
        raise MPresError(f"{PROFILE_FILENAME} selection_scope must be task.")
    if value.get("user_editable_until_task_confirmation") is not True:
        raise MPresError(
            f"{PROFILE_FILENAME} must remain user-editable until task confirmation."
        )
    if value.get("immutable_after_task_confirmation") is not True:
        raise MPresError(f"{PROFILE_FILENAME} must be immutable after task confirmation.")
    if value.get("runtime_changes_during_task") != "forbidden":
        raise MPresError(f"{PROFILE_FILENAME} must forbid runtime changes during the task.")

    defaults = value.get("defaults")
    if not isinstance(defaults, Mapping):
        raise MPresError(f"{PROFILE_FILENAME}.defaults must be a mapping.")
    normalized_defaults: dict[str, dict[str, str]] = {}
    for family in ("planner", "author", "reviewer"):
        normalized_defaults[family] = _validate_spec(
            defaults.get(family), f"defaults.{family}"
        )
    unknown_families = sorted(set(defaults) - set(normalized_defaults))
    if unknown_families:
        raise MPresError(
            f"{PROFILE_FILENAME}.defaults has unsupported families: "
            + ", ".join(unknown_families)
        )

    def normalized_overrides(section: str) -> dict[str, dict[str, str]]:
        raw = value.get(section, {})
        if not isinstance(raw, Mapping):
            raise MPresError(f"{PROFILE_FILENAME}.{section} must be a mapping.")
        return {
            str(key): _validate_spec(spec, f"{section}.{key}", partial=True)
            for key, spec in raw.items()
        }

    presentations = value.get("presentation_overrides", {})
    if not isinstance(presentations, Mapping):
        raise MPresError(f"{PROFILE_FILENAME}.presentation_overrides must be a mapping.")
    normalized_presentations: dict[str, dict[str, Any]] = {}
    for presentation_id, raw in presentations.items():
        if not isinstance(raw, Mapping):
            raise MPresError(
                f"presentation_overrides.{presentation_id} must be a mapping."
            )
        allowed = {"planner", "author", "reviewer", "roles", "reviewer_channels"}
        extra = sorted(set(raw) - allowed)
        if extra:
            raise MPresError(
                f"presentation_overrides.{presentation_id} has unsupported keys: "
                + ", ".join(extra)
            )
        row: dict[str, Any] = {}
        for family in ("planner", "author", "reviewer"):
            if family in raw:
                row[family] = _validate_spec(
                    raw[family], f"presentation_overrides.{presentation_id}.{family}", partial=True
                )
        for source_key, target_key in (("roles", "roles"), ("reviewer_channels", "reviewer_channels")):
            nested = raw.get(source_key, {})
            if not isinstance(nested, Mapping):
                raise MPresError(
                    f"presentation_overrides.{presentation_id}.{source_key} must be a mapping."
                )
            row[target_key] = {
                str(key): _validate_spec(
                    spec,
                    f"presentation_overrides.{presentation_id}.{source_key}.{key}",
                    partial=True,
                )
                for key, spec in nested.items()
            }
        normalized_presentations[str(presentation_id)] = row

    return {
        "schema_version": 1,
        "selection_scope": "task",
        "user_editable_until_task_confirmation": True,
        "immutable_after_task_confirmation": True,
        "runtime_changes_during_task": "forbidden",
        "defaults": normalized_defaults,
        "role_overrides": normalized_overrides("role_overrides"),
        "reviewer_channel_overrides": normalized_overrides("reviewer_channel_overrides"),
        "presentation_overrides": normalized_presentations,
        "notes": list(value.get("notes") or []),
    }


def load_runtime_profile(root: Path, slug: str) -> dict[str, Any]:
    path = runtime_profile_path(root, slug)
    if not path.is_file():
        raise MPresError(
            f"{PROFILE_FILENAME} is missing. Create it and let the user edit it before confirmation."
        )
    return normalize_runtime_profile(read_yaml(path))


def _merge(base: Mapping[str, str], delta: Any) -> dict[str, str]:
    result = dict(base)
    if isinstance(delta, Mapping):
        if delta.get("model") is not None:
            result["model"] = str(delta["model"])
        if delta.get("reasoning_effort") is not None:
            result["reasoning_effort"] = str(delta["reasoning_effort"])
    return result


def runtime_family(role: str) -> str:
    key = role.strip().lower()
    family = ROLE_FAMILIES.get(key)
    if family is None:
        raise MPresError(
            f"Role {role!r} has no runtime family. The user must add a supported role mapping "
            "before task confirmation; agents may not choose one during production."
        )
    return family


def resolve_runtime(
    profile: Mapping[str, Any],
    role: str,
    *,
    channel: str | None = None,
    presentation_id: str | None = None,
) -> dict[str, str]:
    normalized = normalize_runtime_profile(profile)
    role_key = role.strip().lower()
    family = runtime_family(role_key)
    spec = dict(normalized["defaults"][family])
    spec = _merge(spec, normalized["role_overrides"].get(role_key))
    if family == "reviewer" and channel:
        spec = _merge(spec, normalized["reviewer_channel_overrides"].get(channel))
    if presentation_id:
        presentation = normalized["presentation_overrides"].get(presentation_id, {})
        spec = _merge(spec, presentation.get(family))
        spec = _merge(spec, (presentation.get("roles") or {}).get(role_key))
        if family == "reviewer" and channel:
            spec = _merge(
                spec,
                (presentation.get("reviewer_channels") or {}).get(channel),
            )
    _validate_spec(spec, f"resolved runtime for {role_key}")
    return {
        "model": spec["model"],
        "reasoning_effort": spec["reasoning_effort"],
        "runtime_family": family,
        "runtime_source": PROFILE_FILENAME,
    }


def snapshot_for_confirmation(root: Path, slug: str) -> dict[str, Any]:
    return deepcopy(load_runtime_profile(root, slug))


def assert_runtime_profile_unchanged(
    root: Path,
    slug: str,
    confirmed_snapshot: Any,
) -> dict[str, Any]:
    if not isinstance(confirmed_snapshot, Mapping):
        raise MPresError(
            f"No confirmed {PROFILE_FILENAME} snapshot exists in canonical task state."
        )
    current = load_runtime_profile(root, slug)
    if current != dict(confirmed_snapshot):
        raise MPresError(
            f"{PROFILE_FILENAME} changed after task confirmation. Restore the confirmed choices; "
            "runtime model and reasoning effort may not change during the task."
        )
    return current
