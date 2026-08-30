from __future__ import annotations

from typing import Any

from mpres.tasks import require_gate
from mpres.util import MPresError, read_yaml, task_path, utc_now, write_yaml_atomic

THREAD_STATES = {"active", "idle_reusable", "terminal_not_releasable", "closed"}


def _registry_path(root, slug):
    return task_path(root, slug) / "THREAD-REGISTRY.yaml"


def _load(root, slug) -> dict[str, Any]:
    path = _registry_path(root, slug)
    value = read_yaml(path)
    if not isinstance(value, dict) or not isinstance(value.get("handles"), list):
        raise MPresError(f"Malformed thread registry: {path}")
    return value


def _find(registry: dict[str, Any], handle_id: str) -> dict[str, Any]:
    for item in registry["handles"]:
        if isinstance(item, dict) and item.get("handle_id") == handle_id:
            return item
    raise MPresError(f"Unknown thread handle: {handle_id}")


def register_thread(
    root,
    slug: str,
    *,
    handle_id: str,
    runtime_name: str,
    role: str,
    state: str = "idle_reusable",
) -> dict[str, Any]:
    require_gate(root, slug)
    if state not in THREAD_STATES:
        raise MPresError(f"Invalid thread state: {state}")
    registry = _load(root, slug)
    if any(item.get("handle_id") == handle_id for item in registry["handles"] if isinstance(item, dict)):
        raise MPresError(f"Thread handle already exists: {handle_id}")
    row = {
        "handle_id": handle_id,
        "runtime_name": runtime_name,
        "role": role,
        "state": state,
        "current_assignment": None,
        "presentation_id": None,
        "unit_id": None,
        "round": None,
        "channel": None,
        "authored_presentations": [],
        "reviewed_presentations": [],
        "handoff_validated": False,
        "close_requested": False,
        "close_result": None,
        "reusable_for": [role],
        "updated_utc": utc_now(),
    }
    registry["handles"].append(row)
    write_yaml_atomic(_registry_path(root, slug), registry)
    return row


def assign_thread(
    root,
    slug: str,
    *,
    handle_id: str,
    assignment_id: str,
    role: str,
    presentation_id: str,
    unit_id: str | None = None,
    round_name: str | None = None,
    channel: str | None = None,
) -> dict[str, Any]:
    require_gate(root, slug)
    registry = _load(root, slug)
    row = _find(registry, handle_id)
    if row.get("state") not in {"idle_reusable"}:
        raise MPresError(f"Thread {handle_id} is not idle and reusable.")
    if role == "specialist-reviewer" and presentation_id in row.get("authored_presentations", []):
        raise MPresError("A thread that authored a presentation may not review it.")
    if role == "specialist-reviewer":
        for other in registry["handles"]:
            if not isinstance(other, dict) or other is row:
                continue
            if (
                other.get("state") == "active"
                and other.get("role") == "specialist-reviewer"
                and other.get("presentation_id") == presentation_id
                and other.get("round") == round_name
                and other.get("channel") == channel
            ):
                raise MPresError(f"Review channel {channel} already has an active handle.")
    row.update(
        {
            "role": role,
            "state": "active",
            "current_assignment": assignment_id,
            "presentation_id": presentation_id,
            "unit_id": unit_id,
            "round": round_name,
            "channel": channel,
            "handoff_validated": False,
            "close_requested": False,
            "close_result": None,
            "updated_utc": utc_now(),
        }
    )
    write_yaml_atomic(_registry_path(root, slug), registry)
    return row


def validate_handoff(
    root,
    slug: str,
    *,
    handle_id: str,
    durable_paths: list[str],
    summary: str,
) -> dict[str, Any]:
    require_gate(root, slug)
    registry = _load(root, slug)
    row = _find(registry, handle_id)
    if row.get("state") != "active":
        raise MPresError("Only an active thread can hand off work.")
    row["handoff_validated"] = True
    row["handoff_utc"] = utc_now()
    row["durable_paths"] = durable_paths
    row["handoff_summary"] = summary
    presentation_id = row.get("presentation_id")
    if row.get("role") in {"lesson-author", "author-coordinator"} and presentation_id:
        authored = set(row.get("authored_presentations", []))
        authored.add(presentation_id)
        row["authored_presentations"] = sorted(authored)
    if row.get("role") == "specialist-reviewer" and presentation_id:
        reviewed = set(row.get("reviewed_presentations", []))
        reviewed.add(presentation_id)
        row["reviewed_presentations"] = sorted(reviewed)
    row["updated_utc"] = utc_now()
    write_yaml_atomic(_registry_path(root, slug), registry)
    return row


def release_thread(
    root,
    slug: str,
    *,
    handle_id: str,
    runtime_operation: str,
    capacity_released: bool,
    notes: str | None = None,
) -> dict[str, Any]:
    require_gate(root, slug)
    registry = _load(root, slug)
    row = _find(registry, handle_id)
    if not row.get("handoff_validated"):
        raise MPresError("Validate the durable handoff before releasing or reusing a thread.")
    row["close_requested"] = True
    row["close_result"] = {
        "runtime_operation": runtime_operation,
        "capacity_released": bool(capacity_released),
        "notes": notes,
        "recorded_utc": utc_now(),
    }
    row["state"] = "closed" if capacity_released else "idle_reusable"
    row["current_assignment"] = None
    row["presentation_id"] = None
    row["unit_id"] = None
    row["round"] = None
    row["channel"] = None
    row["updated_utc"] = utc_now()
    write_yaml_atomic(_registry_path(root, slug), registry)
    return row


def list_threads(root, slug: str) -> dict[str, Any]:
    require_gate(root, slug)
    return _load(root, slug)
