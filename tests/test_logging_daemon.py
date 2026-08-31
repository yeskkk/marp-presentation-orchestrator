from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from mpres.log_daemon import daemon_status, stop_log_daemon
from mpres.logs import append_log, log_file

from .conftest import make_confirmed_task


def test_persistent_project_logger_serializes_concurrent_clients(
    project_root: Path, monkeypatch
) -> None:
    slug, task = make_confirmed_task(project_root, slug="log-task")
    monkeypatch.delenv("MPRES_LOG_MODE", raising=False)

    def write(index: int) -> None:
        append_log(
            project_root,
            slug,
            actor=f"lesson-author:u{index % 4}",
            kind="progress",
            presentation_id="p01",
            unit_id=f"u{index % 4}",
            message=f"concurrent-daemon-record-{index:03d}",
            data={"index": index},
        )

    try:
        with ThreadPoolExecutor(max_workers=12) as executor:
            list(executor.map(write, range(120)))
        status = daemon_status(project_root)
        assert status["running"] is True
        path = log_file(project_root, slug)
        records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
        concurrent = [
            row for row in records if str(row.get("message", "")).startswith("concurrent-daemon-record-")
        ]
        assert len(concurrent) == 120
        sequences = [row["daemon_sequence"] for row in concurrent]
        assert len(sequences) == len(set(sequences))
        assert all(row["recorded_by"] == "mpres-log-daemon" for row in concurrent)
        assert not (task / "logs" / "planner.jsonl").exists()
        assert not (task / "logs" / "roles").exists()
    finally:
        stop_log_daemon(project_root)
