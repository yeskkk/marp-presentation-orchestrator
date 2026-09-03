from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
import yaml

from mpres.state import (
    ConcurrentStateUpdateError,
    load_state,
    mutable_state_status,
    save_state,
)
from mpres.threads import list_threads, register_thread
from mpres.transactions import database_path, transactional_task_mutation

from .conftest import initialize_one_deck, make_confirmed_task


def test_stale_task_snapshot_is_rejected_without_losing_newer_update(project_root: Path) -> None:
    slug, _ = make_confirmed_task(project_root, slug="v064-stale-state")
    first = load_state(project_root, slug)
    stale = load_state(project_root, slug)

    first["first_writer_marker"] = "committed"
    save_state(project_root, slug, first)

    stale["stale_writer_marker"] = "must-not-overwrite"
    with pytest.raises(ConcurrentStateUpdateError, match="Concurrent update detected"):
        save_state(project_root, slug, stale)

    current = load_state(project_root, slug)
    assert current["first_writer_marker"] == "committed"
    assert "stale_writer_marker" not in current
    assert current["state_revision"] == first["state_revision"]


def test_decorated_task_mutations_serialize_concurrent_writers(project_root: Path) -> None:
    slug, _ = make_confirmed_task(project_root, slug="v064-serialized-state")

    @transactional_task_mutation
    def increment(root: Path, slug: str) -> int:
        state = load_state(root, slug)
        current = int(state.get("parallel_counter", 0))
        time.sleep(0.005)
        state["parallel_counter"] = current + 1
        save_state(root, slug, state)
        return current + 1

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda _: increment(project_root, slug), range(24)))

    assert sorted(results) == list(range(1, 25))
    state = load_state(project_root, slug)
    assert state["parallel_counter"] == 24


def test_separate_process_task_mutations_preserve_every_update(project_root: Path) -> None:
    slug, _ = make_confirmed_task(project_root, slug="v064-process-state")
    source_root = Path(__file__).resolve().parents[1]
    script = r"""
import sys
import time
from pathlib import Path
from mpres.state import load_state, save_state
from mpres.transactions import transactional_task_mutation

@transactional_task_mutation
def increment(root: Path, slug: str) -> None:
    state = load_state(root, slug)
    current = int(state.get("process_counter", 0))
    time.sleep(0.02)
    state["process_counter"] = current + 1
    save_state(root, slug, state)

increment(Path(sys.argv[1]), sys.argv[2])
"""

    def launch(_: int) -> int:
        env = {
            **os.environ,
            "PYTHONPATH": str(source_root / "src"),
            "MPRES_LOG_MODE": "direct-test",
            "PYTHONDONTWRITEBYTECODE": "1",
        }
        completed = subprocess.run(
            [sys.executable, "-c", script, str(project_root), slug],
            cwd=source_root,
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=60,
            check=False,
        )
        assert completed.returncode == 0, completed.stdout
        return completed.returncode

    with ThreadPoolExecutor(max_workers=6) as pool:
        assert list(pool.map(launch, range(12))) == [0] * 12

    state = load_state(project_root, slug)
    assert state["process_counter"] == 12


def test_task_transaction_rolls_back_state_and_projection(project_root: Path) -> None:
    slug, task = make_confirmed_task(project_root, slug="v064-rollback")
    before = load_state(project_root, slug)
    projection_before = json.loads((task / "state" / "task.json").read_text(encoding="utf-8"))

    @transactional_task_mutation
    def failing_update(root: Path, slug: str) -> None:
        state = load_state(root, slug)
        state["should_rollback"] = True
        save_state(root, slug, state)
        raise RuntimeError("force rollback")

    with pytest.raises(RuntimeError, match="force rollback"):
        failing_update(project_root, slug)

    after = load_state(project_root, slug)
    projection_after = json.loads((task / "state" / "task.json").read_text(encoding="utf-8"))
    assert "should_rollback" not in after
    assert after == before
    assert projection_after == projection_before


def test_concurrent_thread_registration_preserves_every_handle(project_root: Path) -> None:
    slug, _ = make_confirmed_task(project_root, slug="v064-thread-registry")

    def register(index: int) -> str:
        handle = f"parallel-{index:02d}"
        row = register_thread(
            project_root,
            slug,
            handle_id=handle,
            runtime_name="author",
            role="lesson-author",
            actual_model="gpt-5.6-sol",
            actual_reasoning_effort="medium",
        )
        return str(row["handle_id"])

    with ThreadPoolExecutor(max_workers=6) as pool:
        handles = list(pool.map(register, range(6)))

    registry = list_threads(project_root, slug)
    stored = {str(row["handle_id"]) for row in registry["handles"]}
    assert stored == set(handles)
    assert registry["registry_revision"] == 6


def test_v063_projection_is_imported_and_repaired_on_first_v064_load(project_root: Path) -> None:
    slug, task = initialize_one_deck(project_root, slug="v064-auto-migration")
    db = database_path(project_root, slug)
    assert db.is_file()
    db.unlink()

    state_path = task / "state" / "task.json"
    state_projection = json.loads(state_path.read_text(encoding="utf-8"))
    state_projection.pop("state_revision", None)
    state_path.write_text(json.dumps(state_projection, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    registry_path = task / "THREAD-REGISTRY.yaml"
    registry_projection = yaml.safe_load(registry_path.read_text(encoding="utf-8"))
    registry_projection.pop("registry_revision", None)
    registry_path.write_text(
        yaml.safe_dump(registry_projection, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )

    # The status command itself is a valid first v0.6.4 access and must import
    # both legacy projections before reporting the store.
    status = mutable_state_status(project_root, slug)
    imported_state = load_state(project_root, slug)
    imported_registry = list_threads(project_root, slug)
    assert imported_state["state_revision"] == 0
    assert imported_registry["registry_revision"] == 0
    assert json.loads(state_path.read_text(encoding="utf-8"))["state_revision"] == 0
    assert yaml.safe_load(registry_path.read_text(encoding="utf-8"))["registry_revision"] == 0

    assert status["single_writer"] == "sqlite-begin-immediate"
    assert {item["document_id"] for item in status["documents"]} == {
        "task-state",
        "thread-registry",
    }
    assert status["ok"] is True


def test_parallel_review_channel_state_updates_are_all_preserved(project_root: Path) -> None:
    from mpres.rendering import render_presentation
    from mpres.review import request_review, submit_channel_review
    from mpres.state import REVIEW_CHANNELS
    from .conftest import install_fake_marp, planner_write_and_approve, prepare_author_source

    slug, task = initialize_one_deck(project_root, slug="v064-parallel-review")
    install_fake_marp(project_root, version="4.5.0")
    prepare_author_source(project_root, slug, task)
    assert render_presentation(project_root, slug, "p01", stage="author", timeout=60)[
        "success"
    ]
    request_review(project_root, slug, "p01")

    inputs: dict[str, tuple[Path, Path]] = {}
    for index, channel in enumerate(REVIEW_CHANNELS, start=1):
        channel_root = (
            task / "workers" / "specialist-reviewers" / "p01" / "full" / channel
        )
        planner_write_and_approve(
            project_root, slug, channel_root / "TASK-SPECIALIST-REVIEWER.md"
        )
        report = channel_root / f"parallel-{channel}-report.md"
        report.write_text(
            f"# {channel} full-deck review\n\n" + "完整范围、证据、判断与结论。\n" * 45,
            encoding="utf-8",
        )
        findings = channel_root / f"parallel-{channel}-findings.yaml"
        findings.write_text(
            yaml.safe_dump(
                {
                    "schema_version": 3,
                    "presentation_id": "p01",
                    "round": "full",
                    "channel": channel,
                    "findings": [
                        {
                            "id": f"{channel.upper()}-{index:03d}",
                            "channel": channel,
                            "round_opened": "full",
                            "location": {"slide_id": "p01-u01-q1"},
                            "issue": "A concrete issue was found in the full frozen deck.",
                            "learner_impact": "The learner could misunderstand the intended object.",
                            "acceptance_criteria": "Revise the named slide and record exact evidence.",
                            "verification_method": "Inspect the author response and revised source.",
                        }
                    ],
                },
                allow_unicode=True,
                sort_keys=False,
            ),
            encoding="utf-8",
        )
        inputs[channel] = (report, findings)

    def submit(channel: str) -> str:
        report, findings = inputs[channel]
        result = submit_channel_review(
            project_root,
            slug,
            "p01",
            round_name="full",
            channel=channel,
            report_path=report,
            findings_path=findings,
        )
        assert result["attempt"] == 1
        return channel

    with ThreadPoolExecutor(max_workers=5) as pool:
        completed = set(pool.map(submit, REVIEW_CHANNELS))

    assert completed == set(REVIEW_CHANNELS)
    state = load_state(project_root, slug)
    channels = state["presentations"][0]["rounds"]["full"]["channels"]
    assert set(channels) == set(REVIEW_CHANNELS)
    assert all(channels[channel]["attempt"] == 1 for channel in REVIEW_CHANNELS)
