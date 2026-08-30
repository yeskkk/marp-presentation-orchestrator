from __future__ import annotations

from pathlib import Path

import pytest

from mpres.production import initialize_production
from mpres.tasks import gate_status, restore_confirmed_task
from mpres.util import MPresError, task_sha256

from .conftest import initialize_one_deck, make_confirmed_task


def test_only_task_md_can_be_hashed(project_root: Path, tmp_path: Path) -> None:
    slug = make_confirmed_task(project_root)
    task = project_root / "tasks" / slug
    assert task_sha256(task / "TASK.md")
    other = tmp_path / "other.md"
    other.write_text("x", encoding="utf-8")
    with pytest.raises(MPresError, match="Only top-level TASK.md"):
        task_sha256(other)


def test_restore_confirmed_task(project_root: Path) -> None:
    slug = make_confirmed_task(project_root)
    task = project_root / "tasks" / slug
    with (task / "TASK.md").open("a", encoding="utf-8") as handle:
        handle.write("\nchanged")
    assert gate_status(project_root, slug)[0] is False
    restored = restore_confirmed_task(project_root, slug)
    assert restored["gate_ok"] is True


def test_production_creates_named_parallel_roles(project_root: Path) -> None:
    slug, task = initialize_one_deck(project_root, stop_mode="pilot")
    assert (task / "workers" / "author-coordinator").is_dir()
    assert (task / "workers" / "lesson-authors" / "p01" / "u01").is_dir()
    assert (task / "workers" / "review-coordinator").is_dir()
    assert (task / "workers" / "specialist-reviewers").is_dir()
    assert (task / "workers" / "release-coordinator").is_dir()
    assert not (task / "workers" / "worker1").exists()
    state = __import__("mpres.state", fromlist=["load_state"]).load_state(project_root, slug)
    assert state["presentations"][0]["active"] is True
    with pytest.raises(MPresError, match="already"):
        initialize_production(project_root, slug, ["p02::x"], ["p02::u01::y"])
