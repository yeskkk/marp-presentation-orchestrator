from __future__ import annotations

import json
import uuid
from collections import defaultdict
from pathlib import Path
from typing import Any

from mpres.tasks import require_gate
from mpres.util import MPresError, relative_display, task_path, utc_now, write_json_atomic

FIELDS = ("input_tokens", "cached_input_tokens", "output_tokens", "reasoning_tokens", "total_tokens")


def _usage_path(root: Path, slug: str) -> Path:
    return task_path(root, slug) / "token-usage" / "usage.jsonl"


def _optional_int(value: Any, name: str) -> int | None:
    if value in {None, "", "unavailable"}:
        return None
    try:
        result = int(value)
    except (TypeError, ValueError) as exc:
        raise MPresError(f"{name} must be an integer or unavailable.") from exc
    if result < 0:
        raise MPresError(f"{name} may not be negative.")
    return result


def _records(path: Path) -> list[dict[str, Any]]:
    text = path.read_text(encoding="utf-8")
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        return [json.loads(line) for line in text.splitlines() if line.strip()]
    if isinstance(value, dict):
        value = value.get("records", [value])
    if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
        raise MPresError("Token source must be JSON object/array or JSONL objects.")
    return value


def import_session(root: Path, slug: str, source: Path, *, presentation_id: str | None, role: str, unit_id: str | None, round_name: str | None, channel: str | None, thread_id: str | None) -> dict[str, Any]:
    require_gate(root, slug)
    source = source.expanduser().resolve()
    if not source.is_file():
        raise MPresError(f"Token source does not exist: {source}")
    import_id = str(uuid.uuid4())
    destination = _usage_path(root, slug)
    destination.parent.mkdir(parents=True, exist_ok=True)
    rows = _records(source)
    with destination.open("a", encoding="utf-8", newline="\n") as handle:
        for index, raw in enumerate(rows, start=1):
            def first(*names: str) -> Any:
                return next((raw[name] for name in names if name in raw), None)
            values = {
                "input_tokens": _optional_int(first("input_tokens", "input", "prompt_tokens"), "input_tokens"),
                "cached_input_tokens": _optional_int(first("cached_input_tokens", "cached", "cached_tokens"), "cached_input_tokens"),
                "output_tokens": _optional_int(first("output_tokens", "output", "completion_tokens"), "output_tokens"),
                "reasoning_tokens": _optional_int(first("reasoning_tokens", "reasoning"), "reasoning_tokens"),
                "total_tokens": _optional_int(first("total_tokens", "total"), "total_tokens"),
            }
            if values["total_tokens"] is None and values["input_tokens"] is not None and values["output_tokens"] is not None:
                values["total_tokens"] = int(values["input_tokens"]) + int(values["output_tokens"])
            record = {
                "schema_version": 1,
                "recorded_utc": utc_now(),
                "import_id": import_id,
                "sequence": index,
                "task_slug": slug,
                "presentation_id": presentation_id or raw.get("presentation_id"),
                "role": role or raw.get("role"),
                "unit_id": unit_id or raw.get("unit_id"),
                "round": round_name or raw.get("round"),
                "channel": channel or raw.get("channel"),
                "thread_id": thread_id or raw.get("thread_id"),
                "model": raw.get("model"),
                **values,
                "measurement_policy": "exact exported counters only; missing values are null",
            }
            handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
    return {"import_id": import_id, "records_imported": len(rows), "destination": relative_display(destination, root)}


def _read(root: Path, slug: str) -> list[dict[str, Any]]:
    path = _usage_path(root, slug)
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()] if path.exists() else []


def token_report(root: Path, slug: str, *, group_by: str = "presentation_id") -> dict[str, Any]:
    require_gate(root, slug)
    allowed = {"presentation_id", "role", "unit_id", "round", "channel", "model", "thread_id"}
    if group_by not in allowed:
        raise MPresError(f"group-by must be one of {sorted(allowed)}")
    buckets: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in _read(root, slug):
        buckets[str(row.get(group_by) or "unattributed")].append(row)
    groups = []
    for key, rows in sorted(buckets.items()):
        totals: dict[str, int | None] = {}
        unavailable: dict[str, int] = {}
        for field in FIELDS:
            values = [row.get(field) for row in rows]
            available = [int(value) for value in values if isinstance(value, int)]
            totals[field] = sum(available) if available else None
            unavailable[field] = len(values) - len(available)
        groups.append({group_by: key, "records": len(rows), "totals": totals, "unavailable_records": unavailable})
    return {"schema_version": 1, "generated_utc": utc_now(), "task_slug": slug, "group_by": group_by, "record_count": sum(len(rows) for rows in buckets.values()), "groups": groups, "measurement_policy": "exact exported counters only; no estimates"}


def save_token_snapshot(root: Path, slug: str, *, group_by: str = "presentation_id") -> dict[str, Any]:
    report = token_report(root, slug, group_by=group_by)
    path = task_path(root, slug) / "token-usage" / "summary.json"
    write_json_atomic(path, report)
    return {**report, "path": relative_display(path, root)}
