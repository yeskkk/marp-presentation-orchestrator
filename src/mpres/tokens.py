from __future__ import annotations

import csv
import json
import re
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Iterable

from mpres.tasks import require_gate
from mpres.util import MPresError, parse_utc, relative_display, task_path, utc_now, write_json_atomic, write_yaml_atomic, read_yaml

FIELDS = (
    "input_tokens",
    "cached_input_tokens",
    "cache_write_input_tokens",
    "output_tokens",
    "reasoning_output_tokens",
    "total_tokens",
)


def _usage_root(root: Path, slug: str) -> Path:
    return task_path(root, slug) / "token-usage"


def _usage_path(root: Path, slug: str) -> Path:
    return _usage_root(root, slug) / "usage.jsonl"


def _collector_config_path(root: Path, slug: str) -> Path:
    return _usage_root(root, slug) / "collector.json"


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
        rows: list[dict[str, Any]] = []
        for number, line in enumerate(text.splitlines(), start=1):
            if not line.strip():
                continue
            try:
                item = json.loads(line)
            except json.JSONDecodeError as exc:
                raise MPresError(f"Invalid JSONL token record at line {number}: {exc}") from exc
            if not isinstance(item, dict):
                raise MPresError(f"Token record at line {number} is not an object.")
            rows.append(item)
        return rows
    if isinstance(value, dict):
        value = value.get("records", [value])
    if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
        raise MPresError("Token source must be JSON object/array or JSONL objects.")
    return list(value)


def import_session(
    root: Path,
    slug: str,
    source: Path,
    *,
    presentation_id: str | None,
    role: str,
    unit_id: str | None,
    round_name: str | None,
    channel: str | None,
    thread_id: str | None,
) -> dict[str, Any]:
    """Import exact counters exported by a client; missing values remain null."""

    require_gate(root, slug)
    source = source.expanduser().resolve()
    if not source.is_file():
        raise MPresError(f"Token source does not exist: {source}")
    rows = _records(source)
    destination = _usage_path(root, slug)
    destination.parent.mkdir(parents=True, exist_ok=True)
    imported = 0
    with destination.open("a", encoding="utf-8", newline="\n") as handle:
        for raw in rows:
            def first(*names: str) -> Any:
                return next((raw[name] for name in names if name in raw), None)

            values = {
                "input_tokens": _optional_int(first("input_tokens", "input", "prompt_tokens"), "input_tokens"),
                "cached_input_tokens": _optional_int(first("cached_input_tokens", "cached", "cached_tokens"), "cached_input_tokens"),
                "cache_write_input_tokens": _optional_int(first("cache_write_input_tokens", "cache_write_tokens"), "cache_write_input_tokens"),
                "output_tokens": _optional_int(first("output_tokens", "output", "completion_tokens"), "output_tokens"),
                "reasoning_output_tokens": _optional_int(first("reasoning_output_tokens", "reasoning_tokens", "reasoning"), "reasoning_output_tokens"),
                "total_tokens": _optional_int(first("total_tokens", "total"), "total_tokens"),
            }
            if values["total_tokens"] is None and values["input_tokens"] is not None and values["output_tokens"] is not None:
                values["total_tokens"] = int(values["input_tokens"]) + int(values["output_tokens"])
            record = {
                "schema_version": 2,
                "recorded_utc": utc_now(),
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
            imported += 1
    return {
        "records_imported": imported,
        "destination": relative_display(destination, root),
    }


def _read(root: Path, slug: str) -> list[dict[str, Any]]:
    path = _usage_path(root, slug)
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _field_summary(rows: Iterable[dict[str, Any]]) -> dict[str, Any]:
    materialized = list(rows)
    totals: dict[str, int | None] = {}
    known_totals: dict[str, int] = {}
    unknown_records: dict[str, int] = {}
    field_coverage: dict[str, float] = {}
    for name in FIELDS:
        known = [int(row[name]) for row in materialized if row.get(name) is not None]
        unknown = len(materialized) - len(known)
        known_totals[name] = sum(known)
        unknown_records[name] = unknown
        totals[name] = sum(known) if unknown == 0 else None
        field_coverage[name] = len(known) / len(materialized) if materialized else 1.0
    complete_records = sum(
        1 for row in materialized if all(row.get(name) is not None for name in FIELDS)
    )
    coverage = complete_records / len(materialized) if materialized else 1.0
    return {
        "records": len(materialized),
        "complete_records": complete_records,
        "coverage": coverage,
        "status": "complete" if complete_records == len(materialized) else "partial_or_unavailable",
        "totals": totals,
        "known_totals": known_totals,
        "unknown_records": unknown_records,
        "field_coverage": field_coverage,
    }


def _aggregate(rows: Iterable[dict[str, Any]], keys: tuple[str, ...]) -> list[dict[str, Any]]:
    groups: dict[tuple[Any, ...], dict[str, Any]] = {}
    for row in rows:
        key = tuple(row.get(name) or "" for name in keys)
        if key not in groups:
            groups[key] = {
                **{name: row.get(name) or "" for name in keys},
                "first_timestamp": row.get("timestamp") or row.get("recorded_utc"),
                "last_timestamp": row.get("timestamp") or row.get("recorded_utc"),
                "_rows": [],
            }
        group = groups[key]
        group["_rows"].append(row)
        timestamp = row.get("timestamp") or row.get("recorded_utc") or ""
        group["first_timestamp"] = min(group["first_timestamp"] or timestamp, timestamp)
        group["last_timestamp"] = max(group["last_timestamp"] or timestamp, timestamp)
    result: list[dict[str, Any]] = []
    for group in groups.values():
        summary = _field_summary(group.pop("_rows"))
        result.append(
            {
                **group,
                "model_calls": summary["records"],
                "complete_records": summary["complete_records"],
                "coverage": summary["coverage"],
                "status": summary["status"],
                **summary["totals"],
                **{
                    f"{name}_known_sum": summary["known_totals"][name]
                    for name in FIELDS
                },
                **{
                    f"{name}_unknown_records": summary["unknown_records"][name]
                    for name in FIELDS
                },
            }
        )
    return sorted(result, key=lambda item: tuple(str(item.get(name, "")) for name in keys))


def token_report(root: Path, slug: str, *, group_by: str = "presentation_id") -> dict[str, Any]:
    require_gate(root, slug)
    allowed = {"presentation_id", "role", "unit_id", "round", "channel", "model", "thread_id", "stage"}
    if group_by not in allowed:
        raise MPresError(f"group-by must be one of {sorted(allowed)}")
    rows = _read(root, slug)
    overall = _field_summary(rows)
    grouped = _aggregate(rows, (group_by,))
    groups: list[dict[str, Any]] = []
    for row in grouped:
        groups.append(
            {
                group_by: row[group_by],
                "records": row["model_calls"],
                "totals": {field: row[field] for field in FIELDS},
                "known_totals": {
                    field: row[f"{field}_known_sum"] for field in FIELDS
                },
                "unknown_records": {
                    field: row[f"{field}_unknown_records"] for field in FIELDS
                },
                "complete_records": row["complete_records"],
                "coverage": row["coverage"],
                "status": row["status"],
            }
        )
    return {
        "schema_version": 3,
        "generated_utc": utc_now(),
        "task_slug": slug,
        "group_by": group_by,
        "record_count": len(rows),
        "complete_record_count": overall["complete_records"],
        "coverage": overall["coverage"],
        "status": overall["status"],
        "totals": overall["totals"],
        "known_totals": overall["known_totals"],
        "unknown_records": overall["unknown_records"],
        "field_coverage": overall["field_coverage"],
        "groups": groups,
        "measurement_policy": (
            "exact exported counters only; no estimates; missing values remain null and make coverage partial"
        ),
    }


def save_token_snapshot(root: Path, slug: str, *, group_by: str = "presentation_id") -> dict[str, Any]:
    report = token_report(root, slug, group_by=group_by)
    path = _usage_root(root, slug) / "summary.json"
    write_json_atomic(path, report)
    return {**report, "path": relative_display(path, root)}


def initialize_collector(
    root: Path,
    slug: str,
    *,
    sessions_root: Path,
    root_thread_id: str,
    task_started_at: str | None = None,
    session_date_floor: str | None = None,
) -> dict[str, Any]:
    require_gate(root, slug)
    if not root_thread_id.strip():
        raise MPresError("Collector initialization requires the root Codex thread ID.")
    sessions_root = sessions_root.expanduser().resolve()
    started = parse_utc(task_started_at) if task_started_at else datetime.now(UTC)
    if started is None:
        raise MPresError("task-started-at must be an ISO timestamp.")
    floor = session_date_floor or started.date().isoformat()
    value = {
        "schema_version": 1,
        "task_slug": slug,
        "sessions_root": str(sessions_root),
        "root_thread_id": root_thread_id.strip(),
        "task_started_at": started.isoformat().replace("+00:00", "Z"),
        "session_date_floor": floor,
        "initialized_utc": utc_now(),
        "content_payloads_extracted": False,
        "counter_source": "Codex event_msg.token_count.info.last_token_usage",
    }
    path = _collector_config_path(root, slug)
    write_json_atomic(path, value)
    return {**value, "path": relative_display(path, root)}


def _read_meta(path: Path) -> dict[str, Any] | None:
    try:
        with path.open(encoding="utf-8") as handle:
            first = json.loads(handle.readline())
    except (OSError, json.JSONDecodeError):
        return None
    if first.get("type") != "session_meta":
        return None
    payload = first.get("payload") or {}
    thread_id = payload.get("id") or payload.get("session_id")
    if not thread_id:
        return None
    return {
        "path": path,
        "thread_id": str(thread_id),
        "parent_thread_id": payload.get("parent_thread_id"),
        "agent_path": payload.get("agent_path") or "/root",
        "agent_nickname": payload.get("agent_nickname") or "",
        "declared_role": payload.get("agent_role") or "",
    }


def _discover_threads(sessions_root: Path, root_thread_id: str, date_floor: str) -> dict[str, dict[str, Any]]:
    all_meta: dict[str, dict[str, Any]] = {}
    for path in sessions_root.rglob("rollout-*.jsonl"):
        date_parts = path.parts[-4:-1]
        if len(date_parts) == 3 and all(part.isdigit() for part in date_parts):
            date_text = "-".join(date_parts)
            if date_text < date_floor:
                continue
        meta = _read_meta(path)
        if meta:
            all_meta[meta["thread_id"]] = meta
    selected = {root_thread_id}
    changed = True
    while changed:
        changed = False
        for thread_id, meta in all_meta.items():
            if thread_id not in selected and meta.get("parent_thread_id") in selected:
                selected.add(thread_id)
                changed = True
    return {thread_id: all_meta[thread_id] for thread_id in selected if thread_id in all_meta}


def _identity(meta: dict[str, Any], overrides: dict[str, Any]) -> dict[str, str]:
    thread_id = meta["thread_id"]
    override = overrides.get(thread_id) if isinstance(overrides, dict) else None
    if isinstance(override, dict):
        return {
            "role": str(override.get("role") or "worker"),
            "stage": str(override.get("stage") or "support"),
            "presentation_id": str(override.get("presentation_id") or "task"),
            "unit_id": str(override.get("unit_id") or ""),
            "channel": str(override.get("channel") or ""),
            "identity_attribution": "explicit",
        }
    path = str(meta.get("agent_path") or "")
    declared = str(meta.get("declared_role") or "")
    if path == "/root":
        role, stage = "planner", "planning-supervision"
    elif declared in {
        "lesson-author",
        "author-coordinator",
        "deck-revision-author",
        "specialist-reviewer",
        "diagnostic-reviewer",
        "delegated-planner",
    }:
        role = declared
        if role == "delegated-planner":
            stage = "planning-supervision"
        elif role == "diagnostic-reviewer":
            stage = "diagnosis"
        elif "review" in role:
            stage = "review"
        elif "author" in role:
            stage = "authoring"
        else:
            stage = "release"
    elif "diagnostic" in path:
        role, stage = "diagnostic-reviewer", "diagnosis"
    elif "review" in path:
        role, stage = "specialist-reviewer", "review"
    elif "lesson" in path or "author" in path:
        role, stage = "lesson-author", "authoring"
    else:
        role, stage = declared or "worker", "support"
    presentation = re.search(r"p\d{2,}", path)
    unit = re.search(r"(?:lesson|unit)[-_]?\d+", path, re.IGNORECASE)
    channel = next((name for name in ("language", "domain_accuracy", "layout", "pedagogy", "audience") if name in path), "")
    return {
        "role": role,
        "stage": stage,
        "presentation_id": presentation.group(0) if presentation else "task",
        "unit_id": unit.group(0) if unit else "",
        "channel": channel,
        "identity_attribution": "path-inferred" if path != "/root" else "root-exact",
    }


def _token_rows(meta: dict[str, Any], task_started_at: datetime, overrides: dict[str, Any]) -> list[dict[str, Any]]:
    identity = _identity(meta, overrides)
    rows: list[dict[str, Any]] = []
    call_index = 0
    try:
        with meta["path"].open(encoding="utf-8") as handle:
            for line in handle:
                if '"type":"token_count"' not in line and '"type": "token_count"' not in line:
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                payload = record.get("payload") or {}
                if record.get("type") != "event_msg" or payload.get("type") != "token_count":
                    continue
                timestamp = parse_utc(record.get("timestamp"))
                if timestamp is None or timestamp < task_started_at:
                    continue
                usage = ((payload.get("info") or {}).get("last_token_usage") or {})
                if not usage:
                    continue
                call_index += 1
                values = {
                    name: _optional_int(usage.get(name), name)
                    for name in FIELDS
                }
                if (
                    values["total_tokens"] is None
                    and values["input_tokens"] is not None
                    and values["output_tokens"] is not None
                ):
                    values["total_tokens"] = (
                        int(values["input_tokens"]) + int(values["output_tokens"])
                    )
                rows.append(
                    {
                        "schema_version": 2,
                        "timestamp": timestamp.isoformat().replace("+00:00", "Z"),
                        "thread_id": meta["thread_id"],
                        "parent_thread_id": meta.get("parent_thread_id") or "",
                        "agent_path": meta.get("agent_path") or "",
                        "agent_nickname": meta.get("agent_nickname") or "",
                        "call_index": call_index,
                        **identity,
                        **values,
                        "content_payloads_extracted": False,
                    }
                )
    except OSError:
        return []
    return rows


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def collect_tokens(root: Path, slug: str) -> dict[str, Any]:
    require_gate(root, slug)
    config_path = _collector_config_path(root, slug)
    if not config_path.is_file():
        raise MPresError("Token collector is not initialized.")
    config = json.loads(config_path.read_text(encoding="utf-8"))
    sessions_root = Path(str(config["sessions_root"])).expanduser().resolve()
    started = parse_utc(config.get("task_started_at"))
    if started is None:
        raise MPresError("Collector config has an invalid task_started_at.")
    attribution_path = _usage_root(root, slug) / "attribution.yaml"
    attribution_value = read_yaml(attribution_path) if attribution_path.is_file() else {}
    overrides = attribution_value.get("threads", {}) if isinstance(attribution_value, dict) else {}
    threads = _discover_threads(
        sessions_root,
        str(config["root_thread_id"]),
        str(config["session_date_floor"]),
    )
    rows: list[dict[str, Any]] = []
    for meta in threads.values():
        rows.extend(_token_rows(meta, started, overrides))
    rows.sort(key=lambda item: (item["timestamp"], item["thread_id"], item["call_index"]))
    output = _usage_root(root, slug)
    output.mkdir(parents=True, exist_ok=True)
    _write_csv(output / "usage-by-call.csv", rows)
    _write_csv(
        output / "usage-by-thread.csv",
        _aggregate(rows, ("thread_id", "role", "presentation_id", "unit_id", "channel", "stage")),
    )
    _write_csv(output / "usage-by-role.csv", _aggregate(rows, ("role", "presentation_id", "stage")))
    summary = _field_summary(rows)
    now = datetime.now(UTC)
    recent = [row for row in rows if (parse_utc(row["timestamp"]) or now) >= now - timedelta(hours=1)]
    latest = {
        "schema_version": 3,
        "generated_utc": now.isoformat().replace("+00:00", "Z"),
        "task_slug": slug,
        "root_thread_id": config["root_thread_id"],
        "selected_threads": len(threads),
        "model_calls": len(rows),
        "recent_60m_model_calls": len(recent),
        "complete_record_count": summary["complete_records"],
        "coverage": summary["coverage"],
        "status": summary["status"],
        "totals": summary["totals"],
        "known_totals": summary["known_totals"],
        "unknown_records": summary["unknown_records"],
        "field_coverage": summary["field_coverage"],
        "counter_source": "Codex event_msg.token_count.info.last_token_usage",
        "content_payloads_extracted": False,
    }
    write_json_atomic(output / "latest.json", latest)
    return latest


def collector_status(root: Path, slug: str) -> dict[str, Any]:
    require_gate(root, slug)
    config_path = _collector_config_path(root, slug)
    latest_path = _usage_root(root, slug) / "latest.json"
    config = json.loads(config_path.read_text(encoding="utf-8")) if config_path.is_file() else None
    latest = json.loads(latest_path.read_text(encoding="utf-8")) if latest_path.is_file() else None
    generated = parse_utc(latest.get("generated_utc")) if isinstance(latest, dict) else None
    age = int((datetime.now(UTC) - generated).total_seconds()) if generated else None
    policy = read_yaml(task_path(root, slug) / "TOKEN-COLLECTOR-POLICY.yaml") or {}
    warning_seconds = int(policy.get("freshness_warning_seconds", 900) or 900) if isinstance(policy, dict) else 900
    return {
        "initialized": config is not None,
        "config": config,
        "latest": latest,
        "age_seconds": age,
        "fresh": age is not None and age <= warning_seconds,
        "freshness_warning_seconds": warning_seconds,
        "content_payloads_extracted": False,
        "ready_for_production": config is not None,
    }


def require_collector_initialized(root: Path, slug: str) -> dict[str, Any]:
    """Fail closed before production when the task policy requires exact counters."""

    require_gate(root, slug)
    policy = read_yaml(task_path(root, slug) / "TOKEN-COLLECTOR-POLICY.yaml") or {}
    required = isinstance(policy, dict) and policy.get("required_before_production") is True
    enabled = not isinstance(policy, dict) or policy.get("enabled") is not False
    status = collector_status(root, slug)
    if enabled and required and not status.get("initialized"):
        raise MPresError(
            "Token collector must be initialized before production. Run `mpres token "
            "collector-init` after task confirmation; unavailable counters may not be reported as zero."
        )
    return status
