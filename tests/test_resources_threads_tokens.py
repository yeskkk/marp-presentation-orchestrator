from __future__ import annotations

import json
from pathlib import Path

import fitz
import pytest
import yaml

from mpres.geogebra import validate_unit_geogebra_registry
from mpres.references import ingest_reference
from mpres.threads import assign_thread, register_thread, release_thread, validate_handoff
from mpres.tokens import import_session, token_report
from mpres.util import MPresError

from .conftest import initialize_one_deck, write_unit_source


def test_reference_workers_receive_only_extracted_text(project_root: Path, tmp_path: Path) -> None:
    slug, task = initialize_one_deck(project_root)
    pdf = tmp_path / "reference.pdf"
    document = fitz.open()
    page = document.new_page()
    page.insert_text((72, 72), "Reference text that must be extracted for workers.")
    document.save(pdf)
    document.close()
    result = ingest_reference(
        project_root, slug, str(pdf), name=None, ocr_mode="never", max_pages=5
    )
    assert "downloads/text/" in result["text_path"]
    assert "restricted-originals" in result["restricted_original_path"]
    original = project_root / result["restricted_original_path"]
    assert original.stat().st_mode & 0o444 == 0
    index = (task / "downloads" / "INDEX.md").read_text(encoding="utf-8")
    assert result["restricted_original_path"] not in index
    assert result["text_path"] in index


def test_geogebra_requires_verified_material_and_plain_markdown_link(project_root: Path) -> None:
    _, task = initialize_one_deck(project_root)
    write_unit_source(task)
    unit = task / "workers" / "lesson-authors" / "p01" / "u01" / "source"
    section = unit / "section.md"
    section.write_text(
        section.read_text(encoding="utf-8")
        + "\n\n[GeoGebra：拖动滑块观察图像变化](https://www.geogebra.org/m/abcd1234)\n",
        encoding="utf-8",
    )
    record = {
        "schema_version": 2,
        "presentation_id": "p01",
        "unit_id": "u01",
        "relevant": True,
        "rationale": "Dynamic manipulation reveals parameter dependence.",
        "site_scope": "geogebra.org",
        "search_attempted": True,
        "search_queries": ["site:geogebra.org/m parameter graph"],
        "search_outcome": "found_selected",
        "selected_resources": [
            {
                "title": "参数图像",
                "url": "https://www.geogebra.org/m/abcd1234",
                "author": "GeoGebra author",
                "verification_status": "verified",
                "verified_title": "参数图像",
                "verified_author": "GeoGebra author",
                "verified_activity": "Drag the slider and compare the graph.",
                "verified_utc": "2026-08-30T00:00:00Z",
                "concept": "parameter dependence",
                "intended_use": "optional exploration",
                "link_text": "GeoGebra：拖动滑块观察图像变化",
                "embedded": False,
            }
        ],
    }
    (unit / "GEOGEBRA-RESOURCES.yaml").write_text(
        yaml.safe_dump(record, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )
    assert validate_unit_geogebra_registry(
        unit / "GEOGEBRA-RESOURCES.yaml", section
    )["success"]
    record["selected_resources"][0]["verification_status"] = "not_checked"
    (unit / "GEOGEBRA-RESOURCES.yaml").write_text(
        yaml.safe_dump(record, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )
    assert not validate_unit_geogebra_registry(
        unit / "GEOGEBRA-RESOURCES.yaml", section
    )["success"]


def test_thread_that_authored_deck_cannot_review_it(project_root: Path) -> None:
    slug, _ = initialize_one_deck(project_root)
    register_thread(
        project_root,
        slug,
        handle_id="t1",
        runtime_name="author",
        role="lesson-author",
        actual_model="gpt-5.6-sol",
        actual_reasoning_effort="high",
    )
    assign_thread(
        project_root,
        slug,
        handle_id="t1",
        assignment_id="lesson-p01-u01",
        role="lesson-author",
        presentation_id="p01",
        unit_id="u01",
    )
    validate_handoff(
        project_root,
        slug,
        handle_id="t1",
        durable_paths=["tasks/test-task/workers/lesson-authors/p01/u01/source"],
        summary="Durable lesson handoff completed.",
    )
    release_thread(
        project_root,
        slug,
        handle_id="t1",
        runtime_operation="reuse",
        capacity_released=False,
    )
    with pytest.raises(MPresError, match="may not review"):
        assign_thread(
            project_root,
            slug,
            handle_id="t1",
            assignment_id="review-language",
            role="specialist-reviewer",
            presentation_id="p01",
            round_name="full",
            channel="language",
        )


def test_token_accounting_never_estimates_missing_values(project_root: Path, tmp_path: Path) -> None:
    slug, _ = initialize_one_deck(project_root)
    source = tmp_path / "tokens.jsonl"
    source.write_text(
        json.dumps(
            {
                "input_tokens": 100,
                "cached_input_tokens": 75,
                "output_tokens": 20,
                "reasoning_tokens": 7,
                "total_tokens": 120,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    import_session(
        project_root,
        slug,
        source,
        presentation_id="p01",
        role="lesson-author",
        unit_id="u01",
        round_name=None,
        channel=None,
        thread_id="t1",
    )
    report = token_report(project_root, slug, group_by="role")
    assert report["groups"][0]["totals"]["total_tokens"] == 120
    assert "no estimates" in report["measurement_policy"]
