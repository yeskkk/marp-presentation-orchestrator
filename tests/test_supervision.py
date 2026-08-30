from __future__ import annotations

from mpres.state import load_state, save_state
from mpres.supervision import supervise_once

from .conftest import initialize_one_deck


def test_planner_supervision_wakes_on_delivery_sequence(project_root) -> None:
    slug, _ = initialize_one_deck(project_root)
    first = supervise_once(project_root, slug, scope="planner", record=True)
    assert first["due"] is True
    second = supervise_once(project_root, slug, scope="planner", record=False)
    assert second["due"] is False
    state = load_state(project_root, slug)
    state["last_delivery_sequence"] = 1
    save_state(project_root, slug, state)
    third = supervise_once(project_root, slug, scope="planner", record=False)
    assert third["due"] is True
    assert third["wake_reason"] == "presentation_delivered"
