from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from mpres.geogebra import (
    aggregate_unit_geogebra_records,
    validate_presentation_geogebra_registry,
    validate_unit_geogebra_registry,
)
from mpres.rendering import render_presentation
from mpres.review import request_review
from mpres.util import MPresError, read_json, read_yaml

from .conftest import (
    approve_core_assignments,
    initialize_one_deck,
    install_fake_marp,
    prepare_author_source,
)


def _resource(label: str, unit_id: str) -> dict[str, object]:
    return {
        "title": "同一个动态资源",
        "url": "https://www.geogebra.org/m/abcd1234",
        "author": "GeoGebra author",
        "verification_status": "verified",
        "verified_title": "同一个动态资源",
        "verified_author": "GeoGebra author",
        "verified_activity": "拖动滑块并比较对象变化。",
        "verified_utc": "2026-08-30T00:00:00Z",
        "concept": f"{unit_id} 的动态观察",
        "intended_use": f"供 {unit_id} 的可选探索使用",
        "link_text": label,
        "embedded": False,
    }


def test_author_html_overflow_gate_blocks_pdf_and_review(project_root: Path) -> None:
    slug, task = initialize_one_deck(project_root)
    prepare_author_source(project_root, slug, task)
    install_fake_marp(project_root, overflow_html=True)

    with pytest.raises(MPresError, match="HTML layout inspection failed"):
        render_presentation(project_root, slug, "p01", stage="author", timeout=60)

    build = task / "workers" / "author-coordinator" / "drafts" / "p01" / "build"
    report = read_json(build / "html-layout-inspection-author.json")
    assert report["success"] is False
    assert report["overflow_slide_count"] == 1
    assert not (build / "p01.pdf").exists()
    with pytest.raises(MPresError, match="successful Marp PDF render"):
        request_review(project_root, slug, "p01")


def test_author_layout_report_is_gate_evidence_not_reviewer_bundle(project_root: Path) -> None:
    slug, task = initialize_one_deck(project_root)
    prepare_author_source(project_root, slug, task)
    install_fake_marp(project_root)
    render_presentation(project_root, slug, "p01", stage="author", timeout=60)
    request_review(project_root, slug, "p01")
    # The request records that the author gate passed, but does not expose mechanical reports
    # to specialist reviewers as review evidence.
    request_path = task / "reviews" / "p01" / "full" / "request" / "request.json"
    value = read_json(request_path)
    serialized = str(value).lower()
    assert "html-layout-inspection" not in serialized
    request_dir = request_path.parent
    assert not list(request_dir.rglob("html-layout-inspection*.json"))


def test_course_time_plan_is_advisory_and_organized_by_meeting(project_root: Path) -> None:
    slug, task = initialize_one_deck(project_root, minutes=40)
    approve_core_assignments(project_root, slug, task)
    plan = read_yaml(
        task
        / "workers"
        / "lesson-authors"
        / "p01"
        / "u01"
        / "source"
        / "LESSON-TIME-PLAN.yaml"
    )
    assert plan["organization_basis"] == "course_meeting"
    assert plan["meeting_label"] == "第 1 节课"
    assert plan["policy"] == "advisory_not_hard_gate"
    assert plan["stop_at_class_end"] is True
    assert plan["prepared_material_target_minutes"] == 60
    assert plan["core_path_target_minutes"] == 40
    assert plan["extension_example_target_minutes"] == 20


def test_geogebra_same_resource_may_be_reused_without_deduplication(tmp_path: Path) -> None:
    section = tmp_path / "section.md"
    label_one = "GeoGebra：第一节课拖动滑块观察变化"
    label_two = "GeoGebra：第二次用同一资源比较另一性质"
    section.write_text(
        f"[{label_one}](https://www.geogebra.org/m/abcd1234)\n\n"
        f"[{label_two}](https://www.geogebra.org/m/abcd1234)\n",
        encoding="utf-8",
    )
    unit_one = {
        "schema_version": 2,
        "presentation_id": "p01",
        "unit_id": "u01",
        "relevant": True,
        "rationale": "动态操作适合观察参数变化。",
        "site_scope": "geogebra.org",
        "search_attempted": True,
        "search_queries": ["site:geogebra.org/m 参数变化"],
        "search_outcome": "found_selected",
        "selected_resources": [_resource(label_one, "u01")],
    }
    unit_two = {
        **unit_one,
        "unit_id": "u02",
        "rationale": "同一资源可用于另一课次的不同观察任务。",
        "selected_resources": [_resource(label_two, "u02")],
    }
    registry_one = tmp_path / "unit-one.yaml"
    registry_one.write_text(yaml.safe_dump(unit_one, allow_unicode=True), encoding="utf-8")
    assert validate_unit_geogebra_registry(registry_one, section)["success"] is False
    # A unit registry must match only its own links. Presentation-level reuse is accepted below.
    aggregate = aggregate_unit_geogebra_records([unit_one, unit_two], presentation_id="p01")
    source = tmp_path / "source"
    source.mkdir()
    (source / "GEOGEBRA-RESOURCES.yaml").write_text(
        yaml.safe_dump(aggregate, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )
    report = validate_presentation_geogebra_registry(source, section.read_text(encoding="utf-8"))
    assert report["success"], report["errors"]
    assert report["registered_link_occurrences"] == 2
    assert report["registered_unique_urls"] == 1
