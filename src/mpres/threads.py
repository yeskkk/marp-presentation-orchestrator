from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any

from mpres.tasks import require_gate
from mpres.util import MPresError, read_yaml, task_path, utc_now, write_yaml_atomic

THREAD_STATES = {"active", "idle_reusable", "terminal_not_releasable", "closed"}


def _registry_path(root: Path, slug: str) -> Path:
    return task_path(root, slug) / "THREAD-REGISTRY.yaml"


def _load(root: Path, slug: str) -> dict[str, Any]:
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


def _model_policy(root: Path) -> dict[str, Any]:
    value = read_yaml(root / "MODEL-POLICY.yaml")
    if not isinstance(value, dict):
        raise MPresError("MODEL-POLICY.yaml must contain a mapping.")
    return value


def expected_runtime(root: Path, role: str) -> dict[str, str]:
    policy = _model_policy(root)
    key = "planner" if role == "planner" else "workers"
    row = policy.get(key)
    if not isinstance(row, dict):
        raise MPresError(f"MODEL-POLICY.yaml lacks the {key} runtime policy.")
    model = str(row.get("model") or "").strip()
    reasoning = str(row.get("reasoning_effort") or "").strip()
    if not model or not reasoning:
        raise MPresError(f"MODEL-POLICY.yaml contains an incomplete {key} runtime policy.")
    return {"model": model, "reasoning_effort": reasoning}


def _thread_limit(root: Path) -> int:
    path = root / ".codex" / "config.toml"
    try:
        value = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise MPresError(f"Cannot read Codex thread limit from {path}: {exc}") from exc
    agents = value.get("agents") if isinstance(value, dict) else None
    limit = agents.get("max_concurrent_threads_per_session") if isinstance(agents, dict) else None
    if not isinstance(limit, int) or limit < 1:
        raise MPresError(".codex/config.toml needs a positive max_concurrent_threads_per_session.")
    return limit


def capacity_preflight(root: Path, slug: str, *, requested: int = 1) -> dict[str, Any]:
    require_gate(root, slug)
    if requested < 0:
        raise MPresError("requested thread count may not be negative.")
    registry = _load(root, slug)
    task_policy = read_yaml(task_path(root, slug) / "EXECUTION-POLICY.yaml") or {}
    lifecycle = task_policy.get("thread_lifecycle") if isinstance(task_policy, dict) else None
    reserve = int((lifecycle or {}).get("reserve_unallocated_capacity", 2) or 0)
    limit = _thread_limit(root)
    allocated = sum(
        1
        for item in registry.get("handles", [])
        if isinstance(item, dict) and item.get("state") != "closed"
    )
    remaining_before = limit - allocated
    remaining_after = remaining_before - requested
    ok = remaining_after >= reserve
    return {
        "schema_version": 1,
        "thread_limit": limit,
        "allocated_handles": allocated,
        "requested_handles": requested,
        "reserve_unallocated_capacity": reserve,
        "remaining_before": remaining_before,
        "remaining_after": remaining_after,
        "ok": ok,
        "reason": (
            "capacity available"
            if ok
            else "requested handles would consume the reserved recovery/reviewer capacity"
        ),
    }


def _require_runtime_match(root: Path, role: str, model: str, reasoning_effort: str) -> None:
    expected = expected_runtime(root, role)
    if model != expected["model"] or reasoning_effort != expected["reasoning_effort"]:
        raise MPresError(
            f"Runtime mismatch for {role}: expected {expected['model']}/{expected['reasoning_effort']}, "
            f"got {model}/{reasoning_effort}."
        )


def register_thread(
    root: Path,
    slug: str,
    *,
    handle_id: str,
    runtime_name: str,
    role: str,
    actual_model: str,
    actual_reasoning_effort: str,
    state: str = "idle_reusable",
) -> dict[str, Any]:
    require_gate(root, slug)
    if state not in THREAD_STATES:
        raise MPresError(f"Invalid thread state: {state}")
    _require_runtime_match(root, role, actual_model, actual_reasoning_effort)
    capacity = capacity_preflight(root, slug, requested=1)
    if not capacity["ok"]:
        raise MPresError(str(capacity["reason"]))
    registry = _load(root, slug)
    if any(item.get("handle_id") == handle_id for item in registry["handles"] if isinstance(item, dict)):
        raise MPresError(f"Thread handle already exists: {handle_id}")
    row = {
        "handle_id": handle_id,
        "runtime_name": runtime_name,
        "role": role,
        "actual_model": actual_model,
        "actual_reasoning_effort": actual_reasoning_effort,
        "runtime_policy_verified": True,
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
    root: Path,
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
    _require_runtime_match(
        root,
        role,
        str(row.get("actual_model") or ""),
        str(row.get("actual_reasoning_effort") or ""),
    )
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
            "runtime_policy_verified": True,
            "updated_utc": utc_now(),
        }
    )
    write_yaml_atomic(_registry_path(root, slug), registry)
    return row


def validate_handoff(
    root: Path,
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
    root: Path,
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


def list_threads(root: Path, slug: str) -> dict[str, Any]:
    require_gate(root, slug)
    return _load(root, slug)
