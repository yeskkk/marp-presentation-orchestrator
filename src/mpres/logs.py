from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

from mpres.log_daemon import project_log_path, submit_log_record
from mpres.util import MPresError, utc_now

ACTOR_RE = re.compile(r"[a-z0-9][a-z0-9:._-]{0,95}")
VALID_KINDS = {
    "decision",
    "progress",
    "check",
    "warning",
    "error",
    "restart",
    "review",
    "render",
    "handoff",
    "delivery",
    "checkpoint",
    "maintenance",
}


def log_file(root: Path, slug: str, actor: str | None = None) -> Path:
    del actor
    return project_log_path(root, slug)


def _direct_test_write(root: Path, slug: str, record: dict[str, Any]) -> dict[str, Any]:
    """Deterministic test-only transport.

    Production callers always use the persistent daemon. The explicit environment switch avoids
    spawning one daemon per temporary pytest repository while a dedicated daemon test exercises
    real concurrent clients.
    """

    path = project_log_path(root, slug)
    path.parent.mkdir(parents=True, exist_ok=True)
    output = {**record, "recorded_by": "direct-test-transport"}
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(output, ensure_ascii=False, sort_keys=True) + "\n")
    return {"ok": True, "path": str(path), "record": output}


def append_log(
    root: Path,
    slug: str,
    *,
    actor: str,
    kind: str,
    message: str,
    presentation_id: str | None = None,
    unit_id: str | None = None,
    round_name: str | None = None,
    channel: str | None = None,
    data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if actor not in {"planner", "system"} and not ACTOR_RE.fullmatch(actor):
        raise MPresError(f"Unsafe log actor: {actor!r}")
    if kind not in VALID_KINDS:
        raise MPresError(f"Kind must be one of {sorted(VALID_KINDS)}")
    record: dict[str, Any] = {
        "utc": utc_now(),
        "actor": actor,
        "kind": kind,
        "message": message.strip(),
    }
    if presentation_id:
        record["presentation_id"] = presentation_id
    if unit_id:
        record["unit_id"] = unit_id
    if round_name:
        record["round"] = round_name
    if channel:
        record["channel"] = channel
    if data:
        record["data"] = data
    if os.environ.get("MPRES_LOG_MODE") == "direct-test":
        response = _direct_test_write(root, slug, record)
    else:
        response = submit_log_record(root, slug, record)
    return response.get("record", record)


def read_log_tail(
    path: Path,
    count: int = 20,
    *,
    actor: str | None = None,
    presentation_id: str | None = None,
    unit_id: str | None = None,
    round_name: str | None = None,
    channel: str | None = None,
) -> list[dict[str, Any]]:
    """Read the newest matching records from the single project log.

    Filtering happens at read time; writers never receive or expose any concurrency primitive.
    """

    if not path.exists():
        return []
    matches: list[dict[str, Any]] = []
    for line in reversed(path.read_text(encoding="utf-8", errors="replace").splitlines()):
        try:
            value = json.loads(line)
            record = value if isinstance(value, dict) else {"message": str(value)}
        except json.JSONDecodeError:
            record = {"utc": None, "kind": "error", "message": f"Malformed log line: {line}"}
        if actor is not None and record.get("actor") != actor:
            continue
        if presentation_id is not None and record.get("presentation_id") != presentation_id:
            continue
        if unit_id is not None and record.get("unit_id") != unit_id:
            continue
        if round_name is not None and record.get("round") != round_name:
            continue
        if channel is not None and record.get("channel") != channel:
            continue
        matches.append(record)
        if len(matches) >= count:
            break
    matches.reverse()
    return matches
