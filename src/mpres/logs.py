from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from mpres.util import MPresError, task_path, utc_now

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
}


def _actor_filename(actor: str) -> str:
    return actor.replace(":", "--").replace("/", "-") + ".jsonl"


def log_file(root: Path, slug: str, actor: str) -> Path:
    task = task_path(root, slug)
    if actor in {"planner", "system"}:
        return task / "logs" / "planner.jsonl"
    if not ACTOR_RE.fullmatch(actor):
        raise MPresError(f"Unsafe log actor: {actor!r}")
    return task / "logs" / "roles" / _actor_filename(actor)


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
    path = log_file(root, slug, actor)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
    return record


def read_log_tail(path: Path, count: int = 20) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()[-count:]
    records: list[dict[str, Any]] = []
    for line in lines:
        try:
            value = json.loads(line)
            records.append(value if isinstance(value, dict) else {"message": str(value)})
        except json.JSONDecodeError:
            records.append({"utc": None, "kind": "error", "message": f"Malformed log line: {line}"})
    return records
