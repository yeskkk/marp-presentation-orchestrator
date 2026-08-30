from __future__ import annotations

from pathlib import Path

import yaml

from mpres.geogebra import validate_unit_geogebra_registry
from mpres.marp_source import lint_deck
from mpres.util import read_yaml

from .conftest import complete_author_source, finalize_canonical_source, initialize_one_deck


RESOURCE_URL = "https://www.geogebra.org/m/abc123xy"


def _write_unit_record(path: Path, *, selected: list[dict[str, object]]) -> None:
    path.write_text(
        yaml.safe_dump(
            {
                "schema_version": 1,
                "presentation_id": "p01",
                "unit_id": "u01",
                "relevant": True,
                "rationale": "A slider can support optional exploration of parameter change.",
                "site_scope": "geogebra.org",
                "search_attempted": True,
                "search_queries": ["site:geogebra.org/m quadratic parameter slider"],
                "search_outcome": "found_selected" if selected else "searched_no_suitable_resource",
                "selected_resources": selected,
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )


def test_registered_geogebra_markdown_link_passes_and_is_aggregated(project_root: Path) -> None:
    slug, task = initialize_one_deck(project_root)
    complete_author_source(task)
    unit = task / "workers" / "lesson-authors" / "p01" / "u01" / "source"
    section = unit / "section.md"
    section.write_text(
        section.read_text(encoding="utf-8")
        + f"\n\n[GeoGebra：拖动参数观察图像]({RESOURCE_URL})\n",
        encoding="utf-8",
    )
    _write_unit_record(
        unit / "GEOGEBRA-RESOURCES.yaml",
        selected=[
            {
                "title": "Quadratic parameter exploration",
                "url": RESOURCE_URL,
                "concept": "How a parameter changes a graph",
                "intended_use": "Optional after-class interactive exploration",
                "link_text": "GeoGebra：拖动参数观察图像",
                "verified_resource": True,
                "checked_utc": "2026-08-30T00:00:00Z",
                "embedded": False,
            }
        ],
    )
    author = finalize_canonical_source(project_root, slug, task)
    report = lint_deck(author, policy=read_yaml(task / "EXECUTION-POLICY.yaml"))
    assert report["success"] is True
    aggregate = read_yaml(author / "GEOGEBRA-RESOURCES.yaml")
    assert aggregate["policy"]["usage"] == "markdown-hyperlinks-only"
    assert aggregate["units"][0]["selected_resources"][0]["url"] == RESOURCE_URL


def test_geogebra_external_domain_is_rejected(tmp_path: Path) -> None:
    section = tmp_path / "section.md"
    section.write_text("[External](https://example.com/m/abc)\n", encoding="utf-8")
    registry = tmp_path / "GEOGEBRA-RESOURCES.yaml"
    _write_unit_record(
        registry,
        selected=[
            {
                "title": "Wrong host",
                "url": "https://example.com/m/abc",
                "concept": "test",
                "intended_use": "test",
                "link_text": "External",
                "verified_resource": True,
                "checked_utc": "2026-08-30T00:00:00Z",
                "embedded": False,
            }
        ],
    )
    report = validate_unit_geogebra_registry(registry, section)
    assert report["success"] is False
    assert any("geogebra.org" in error for error in report["errors"])


def test_geogebra_embedding_is_rejected(tmp_path: Path) -> None:
    section = tmp_path / "section.md"
    section.write_text(
        f'<iframe src="{RESOURCE_URL}"></iframe>\n',
        encoding="utf-8",
    )
    registry = tmp_path / "GEOGEBRA-RESOURCES.yaml"
    _write_unit_record(registry, selected=[])
    report = validate_unit_geogebra_registry(registry, section)
    assert report["success"] is False
    assert any("Markdown hyperlink" in error for error in report["errors"])


def test_unregistered_geogebra_link_is_rejected(tmp_path: Path) -> None:
    section = tmp_path / "section.md"
    section.write_text(f"[GeoGebra activity]({RESOURCE_URL})\n", encoding="utf-8")
    registry = tmp_path / "GEOGEBRA-RESOURCES.yaml"
    _write_unit_record(registry, selected=[])
    report = validate_unit_geogebra_registry(registry, section)
    assert report["success"] is False
    assert any("not selected in its registry" in error for error in report["errors"])


def test_geogebra_query_budget_is_enforced(tmp_path: Path) -> None:
    section = tmp_path / "section.md"
    section.write_text("No selected resource.\n", encoding="utf-8")
    registry = tmp_path / "GEOGEBRA-RESOURCES.yaml"
    _write_unit_record(registry, selected=[])
    data = yaml.safe_load(registry.read_text(encoding="utf-8"))
    data["search_queries"] = [
        f"site:geogebra.org/m topic {index}" for index in range(4)
    ]
    registry.write_text(
        yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )
    report = validate_unit_geogebra_registry(
        registry, section, maximum_queries=3
    )
    assert report["success"] is False
    assert any("exceeds the limit" in error for error in report["errors"])


def test_bare_geogebra_url_is_rejected_even_when_registered(tmp_path: Path) -> None:
    section = tmp_path / "section.md"
    section.write_text(f"Optional exploration: {RESOURCE_URL}\n", encoding="utf-8")
    registry = tmp_path / "GEOGEBRA-RESOURCES.yaml"
    _write_unit_record(
        registry,
        selected=[
            {
                "title": "Parameter explorer",
                "url": RESOURCE_URL,
                "concept": "parameter variation",
                "intended_use": "optional follow-up",
                "link_text": "GeoGebra：拖动参数观察图像",
                "checked_utc": "2026-08-30T00:00:00Z",
                "embedded": False,
            }
        ],
    )
    report = validate_unit_geogebra_registry(registry, section)
    assert report["success"] is False
    assert any("Bare GeoGebra URLs" in error for error in report["errors"])


def test_generic_geogebra_homepage_is_not_a_resource(tmp_path: Path) -> None:
    section = tmp_path / "section.md"
    section.write_text(
        "[GeoGebra：打开主页](https://www.geogebra.org/)\n", encoding="utf-8"
    )
    registry = tmp_path / "GEOGEBRA-RESOURCES.yaml"
    _write_unit_record(
        registry,
        selected=[
            {
                "title": "GeoGebra homepage",
                "url": "https://www.geogebra.org/",
                "concept": "none",
                "intended_use": "generic",
                "link_text": "GeoGebra：打开主页",
                "checked_utc": "2026-08-30T00:00:00Z",
                "embedded": False,
            }
        ],
    )
    report = validate_unit_geogebra_registry(registry, section)
    assert report["success"] is False
    assert any("specific public resource" in error for error in report["errors"])


def test_geogebra_search_query_must_use_site_filter(tmp_path: Path) -> None:
    section = tmp_path / "section.md"
    section.write_text("No selected resource.\n", encoding="utf-8")
    registry = tmp_path / "GEOGEBRA-RESOURCES.yaml"
    _write_unit_record(registry, selected=[])
    data = yaml.safe_load(registry.read_text(encoding="utf-8"))
    data["search_queries"] = ["geogebra.org quadratic parameter slider"]
    registry.write_text(
        yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )
    report = validate_unit_geogebra_registry(registry, section)
    assert report["success"] is False
    assert any("site:geogebra.org" in error for error in report["errors"])


def test_geogebra_named_link_to_third_party_is_rejected(tmp_path: Path) -> None:
    section = tmp_path / "section.md"
    section.write_text(
        "[GeoGebra：拖动参数观察图像](https://example.com/material/abc)\n",
        encoding="utf-8",
    )
    registry = tmp_path / "GEOGEBRA-RESOURCES.yaml"
    _write_unit_record(registry, selected=[])
    report = validate_unit_geogebra_registry(registry, section)
    assert report["success"] is False
    assert any("point directly to geogebra.org" in error for error in report["errors"])


def test_geogebra_html_anchor_is_rejected(tmp_path: Path) -> None:
    section = tmp_path / "section.md"
    section.write_text(
        f'<a href="{RESOURCE_URL}">GeoGebra：拖动参数观察图像</a>\n',
        encoding="utf-8",
    )
    registry = tmp_path / "GEOGEBRA-RESOURCES.yaml"
    _write_unit_record(
        registry,
        selected=[
            {
                "title": "Parameter explorer",
                "url": RESOURCE_URL,
                "concept": "parameter variation",
                "intended_use": "optional follow-up",
                "link_text": "GeoGebra：拖动参数观察图像",
                "checked_utc": "2026-08-30T00:00:00Z",
                "embedded": False,
            }
        ],
    )
    report = validate_unit_geogebra_registry(registry, section)
    assert report["success"] is False
    assert any("ordinary Markdown syntax" in error for error in report["errors"])


def test_geogebra_selected_resource_must_be_mapping(tmp_path: Path) -> None:
    section = tmp_path / "section.md"
    section.write_text("No link.\n", encoding="utf-8")
    registry = tmp_path / "GEOGEBRA-RESOURCES.yaml"
    registry.write_text(
        yaml.safe_dump(
            {
                "schema_version": 1,
                "presentation_id": "p01",
                "unit_id": "u01",
                "relevant": True,
                "rationale": "A dynamic activity could support optional parameter exploration.",
                "site_scope": "geogebra.org",
                "search_attempted": True,
                "search_queries": ["site:geogebra.org/m parameter exploration"],
                "search_outcome": "found_selected",
                "selected_resources": ["not-a-mapping"],
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    report = validate_unit_geogebra_registry(registry, section)
    assert report["success"] is False
    assert any("must be a mapping" in error for error in report["errors"])


def test_geogebra_checked_utc_must_be_explicit_utc(tmp_path: Path) -> None:
    section = tmp_path / "section.md"
    section.write_text(f"[GeoGebra：拖动参数观察图像]({RESOURCE_URL})\n", encoding="utf-8")
    registry = tmp_path / "GEOGEBRA-RESOURCES.yaml"
    _write_unit_record(
        registry,
        selected=[
            {
                "title": "Parameter explorer",
                "url": RESOURCE_URL,
                "concept": "parameter variation",
                "intended_use": "optional follow-up",
                "link_text": "GeoGebra：拖动参数观察图像",
                "checked_utc": "2026-08-30 00:00",
                "embedded": False,
            }
        ],
    )
    report = validate_unit_geogebra_registry(registry, section)
    assert report["success"] is False
    assert any("ISO-8601 UTC" in error for error in report["errors"])
