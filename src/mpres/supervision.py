from __future__ import annotations

import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from mpres.logs import append_log, log_file, read_log_tail
from mpres.state import REVIEW_CHANNELS, get_presentation, load_state
from mpres.tasks import require_gate
from mpres.tokens import collector_status
from mpres.util import MPresError, latest_mtime, parse_utc, read_json, read_yaml, relative_display, task_path, utc_now, write_json_atomic


def _seconds_since(value: str | None) -> int | None:
    parsed = parse_utc(value)
    if parsed is None:
        return None
    return max(0, int((datetime.now(UTC) - parsed).total_seconds()))


def _last_log(path: Path, presentation_id: str | None = None) -> dict[str, Any] | None:
    for record in reversed(read_log_tail(path, count=200)):
        if presentation_id and record.get("presentation_id") != presentation_id:
            continue
        return record
    return None


def _signal(log: dict[str, Any] | None, watched: Path) -> tuple[int | None, bool]:
    age = _seconds_since(log.get("utc") if log else None)
    mtime = latest_mtime(watched)
    newer = False
    if mtime is not None and log and log.get("utc"):
        parsed = parse_utc(log["utc"])
        newer = bool(parsed and mtime > parsed.timestamp() + 2)
    return age, newer


def _coordinator(status: str) -> str:
    if status in {"authoring", "author_revision"}:
        return "author-coordinator"
    if status in {"review_requested", "reviewing"}:
        return "review-coordinator"
    if status == "release_ready":
        return "release-coordinator"
    return "planner"


def _planner(root: Path, slug: str, state: dict[str, Any], *, record: bool) -> dict[str, Any]:
    task = task_path(root, slug)
    policy = read_yaml(task / "EXECUTION-POLICY.yaml") or {}
    interval = int((policy.get("planner_supervision") or {}).get("interval_seconds", 1200) or 1200)
    status_path = task / "state" / "supervision-planner.json"
    previous = read_json(status_path) if status_path.is_file() else {}
    elapsed = _seconds_since(previous.get("checked_utc"))
    delivery = int(state.get("last_delivery_sequence", 0))
    seen = int(previous.get("last_seen_delivery_sequence", 0))
    if not previous:
        due, wake = True, "first_check"
    elif delivery > seen:
        due, wake = True, "presentation_delivered"
    elif elapsed is None or elapsed >= interval:
        due, wake = True, "twenty_minute_interval"
    else:
        due, wake = False, "not_due"
    checks: list[dict[str, Any]] = []
    if due:
        for presentation in state.get("presentations", []):
            if not presentation.get("active") or presentation.get("status") == "finalized":
                continue
            pid = presentation["id"]
            actor = _coordinator(str(presentation.get("status")))
            log = _last_log(log_file(root, slug, actor), pid)
            watched = task / "workers" / actor
            if actor == "author-coordinator":
                watched = watched / "drafts" / pid
            elif actor == "review-coordinator":
                watched = task / "reviews" / pid
            else:
                watched = watched / "release-ready" / pid
            age, newer = _signal(log, watched)
            if log is None:
                recommendation = "inspect_or_spawn_coordinator"
                reason = f"No {actor} log exists."
            elif newer and age is not None and age > interval:
                recommendation = "silent_but_durable_progress"
                reason = "Files changed after the last log; request a checkpoint rather than restart."
            elif age is not None and age > interval * 2:
                recommendation = "probably_stalled_restart_from_checkpoint"
                reason = f"No durable coordinator activity for {age} seconds."
            elif age is not None and age > interval:
                recommendation = "inspect_and_steer_coordinator"
                reason = f"Coordinator log is {age} seconds old."
            else:
                recommendation = "healthy"
                reason = "Coordinator has recent durable activity."
            checks.append({
                "presentation_id": pid,
                "status": presentation.get("status"),
                "coordinator": actor,
                "last_log": log,
                "log_age_seconds": age,
                "recommendation": recommendation,
                "reason": reason,
            })
    token_collector: dict[str, Any] | None = None
    if due:
        try:
            token_collector = collector_status(root, slug)
        except MPresError as exc:
            token_collector = {"initialized": False, "fresh": False, "error": str(exc)}
        token_policy = read_yaml(task / "TOKEN-COLLECTOR-POLICY.yaml") or {}
        if isinstance(token_policy, dict) and token_policy.get("required_before_first_coordinator") is True:
            if not token_collector.get("initialized"):
                checks.append(
                    {
                        "presentation_id": "task",
                        "status": state.get("phase"),
                        "coordinator": "token-collector",
                        "last_log": None,
                        "log_age_seconds": None,
                        "recommendation": "initialize_token_collector",
                        "reason": "Token collector is required before coordinator work but is not initialized.",
                    }
                )
            elif not token_collector.get("fresh"):
                checks.append(
                    {
                        "presentation_id": "task",
                        "status": state.get("phase"),
                        "coordinator": "token-collector",
                        "last_log": None,
                        "log_age_seconds": token_collector.get("age_seconds"),
                        "recommendation": "refresh_token_collector",
                        "reason": "Exact token counters are stale; collect before the next high-level decision.",
                    }
                )
    result = {
        "checked_utc": utc_now(),
        "scope": "planner",
        "due": due,
        "wake_reason": wake,
        "interval_seconds": interval,
        "phase": state.get("phase"),
        "last_seen_delivery_sequence": delivery,
        "token_collector": token_collector,
        "checks": checks,
        "requires_attention": any(
            item["recommendation"] not in {"healthy", "silent_but_durable_progress"}
            for item in checks
        ),
    }
    if record and due:
        write_json_atomic(status_path, result)
        append_log(
            root,
            slug,
            actor="planner",
            kind="check",
            message=(
                "Performed high-level supervision after a deck delivery."
                if wake == "presentation_delivered"
                else "Performed the scheduled twenty-minute high-level supervision check."
            ),
            data={"wake_reason": wake, "requires_attention": result["requires_attention"]},
        )
    return result


def _author(root: Path, slug: str, state: dict[str, Any], pid: str) -> dict[str, Any]:
    task = task_path(root, slug)
    presentation = get_presentation(state, pid)
    checks: list[dict[str, Any]] = []
    for unit in presentation.get("content_units", []):
        if unit.get("status") == "integrated":
            continue
        unit_id = unit["id"]
        actor = f"lesson-author:{unit_id}"
        log = _last_log(log_file(root, slug, actor), pid)
        watched = task / "workers" / "lesson-authors" / pid / unit_id / "source"
        age, newer = _signal(log, watched)
        if log is None:
            rec, reason = "spawn_or_resume", "No lesson-author log exists."
        elif newer and age is not None and age > 300:
            rec, reason = "silent_but_durable_progress", "Unit files changed after the latest log."
        elif age is not None and age > 900:
            rec, reason = "restart_from_checkpoint", f"No activity for {age} seconds."
        elif age is not None and age > 300:
            rec, reason = "inspect_and_steer", f"Log is {age} seconds old."
        else:
            rec, reason = "healthy", "Recent activity."
        checks.append({"unit_id": unit_id, "last_log": log, "log_age_seconds": age, "recommendation": rec, "reason": reason})
    return {"checked_utc": utc_now(), "scope": "author", "presentation_id": pid, "checks": checks, "requires_attention": any(item["recommendation"] not in {"healthy", "silent_but_durable_progress"} for item in checks)}


def _review(root: Path, slug: str, state: dict[str, Any], pid: str) -> dict[str, Any]:
    presentation = get_presentation(state, pid)
    round_name = presentation.get("active_round")
    if round_name != "full":
        return {"checked_utc": utc_now(), "scope": "review", "presentation_id": pid, "round": round_name, "checks": [], "requires_attention": False, "note": "No specialist round is active."}
    submitted = presentation.get("rounds", {}).get(round_name, {}).get("channels", {})
    checks: list[dict[str, Any]] = []
    for channel in REVIEW_CHANNELS:
        if channel in submitted:
            continue
        actor = f"specialist-reviewer:{channel}"
        log = _last_log(log_file(root, slug, actor), pid)
        age = _seconds_since(log.get("utc") if log else None)
        if log is None:
            rec, reason = "spawn_or_resume", "No reviewer log exists."
        elif age is not None and age > 900:
            rec, reason = "restart_from_checkpoint", f"Reviewer log is {age} seconds old."
        elif age is not None and age > 300:
            rec, reason = "inspect_and_steer", f"Reviewer log is {age} seconds old."
        else:
            rec, reason = "healthy", "Recent reviewer activity."
        checks.append({"channel": channel, "last_log": log, "log_age_seconds": age, "recommendation": rec, "reason": reason})
    return {"checked_utc": utc_now(), "scope": "review", "presentation_id": pid, "round": round_name, "checks": checks, "requires_attention": any(item["recommendation"] != "healthy" for item in checks)}


def supervise_once(
    root: Path,
    slug: str,
    *,
    scope: str = "planner",
    presentation_id: str | None = None,
    record: bool = False,
) -> dict[str, Any]:
    state = require_gate(root, slug)
    if scope == "planner":
        return _planner(root, slug, state, record=record)
    if not presentation_id:
        raise MPresError("Coordinator supervision requires a presentation ID.")
    if scope == "author":
        result, actor = _author(root, slug, state, presentation_id), "author-coordinator"
    elif scope == "review":
        result, actor = _review(root, slug, state, presentation_id), "review-coordinator"
    else:
        raise MPresError("Scope must be planner, author, or review.")
    if record:
        path = task_path(root, slug) / "state" / f"supervision-{scope}-{presentation_id}.json"
        write_json_atomic(path, result)
        append_log(root, slug, actor=actor, kind="check", presentation_id=presentation_id, message=f"Performed {scope} coordinator supervision.", data={"report": relative_display(path, root), "requires_attention": result["requires_attention"]})
    return result


def watch_supervision(
    root: Path,
    slug: str,
    *,
    scope: str = "planner",
    presentation_id: str | None = None,
    interval: int | None = None,
    iterations: int | None = None,
) -> None:
    poll = interval if interval is not None else (10 if scope == "planner" else 300)
    if poll <= 0:
        raise MPresError("Supervision interval must be positive.")
    completed = 0
    while iterations is None or completed < iterations:
        result = supervise_once(root, slug, scope=scope, presentation_id=presentation_id, record=True)
        if scope != "planner" or result.get("due"):
            completed += 1
        if iterations is not None and completed >= iterations:
            break
        if load_state(root, slug).get("phase") == "complete":
            break
        time.sleep(poll)
