from __future__ import annotations

import json
from pathlib import Path

from mpres.references import ingest_reference
from mpres.supervision import supervise_once
from mpres.util import read_json, write_json_atomic

from .conftest import initialize_one_deck, make_confirmed_task


def test_reference_metadata_has_no_hashes(project_root: Path, tmp_path: Path) -> None:
    slug = make_confirmed_task(project_root)
    source = tmp_path / "ref.md"
    source.write_text("# Reference\n\nUseful content.", encoding="utf-8")
    metadata = ingest_reference(project_root, slug, str(source), name=None, ocr_mode="never", max_pages=10)
    text = json.dumps(metadata).lower()
    assert "sha256" not in text and "hash" not in text
    assert metadata["original_size_bytes"] > 0


def test_planner_supervision_wakes_on_delivery(project_root: Path) -> None:
    slug, task = initialize_one_deck(project_root)
    first = supervise_once(project_root, slug, scope="planner", record=True)
    assert first["due"] is True
    second = supervise_once(project_root, slug, scope="planner", record=False)
    assert second["due"] is False
    state_path = task / "state" / "task.json"
    state = read_json(state_path)
    state["last_delivery_sequence"] = 1
    write_json_atomic(state_path, state)
    third = supervise_once(project_root, slug, scope="planner", record=False)
    assert third["due"] is True
    assert third["wake_reason"] == "presentation_delivered"
