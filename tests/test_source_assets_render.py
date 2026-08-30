from __future__ import annotations

from pathlib import Path

import pytest

from mpres.assets import run_python_asset, validate_assets
from mpres.marp_source import lint_deck
from mpres.rendering import render_presentation
from mpres.util import MPresError, read_json, read_yaml

from .conftest import complete_author_source, finalize_canonical_source, initialize_one_deck, install_fake_marp


def test_source_lint_and_pdf_only_render(project_root: Path) -> None:
    slug, task = initialize_one_deck(project_root)
    complete_author_source(task)
    author = finalize_canonical_source(project_root, slug, task)
    lint = lint_deck(author, policy=read_yaml(task / "EXECUTION-POLICY.yaml"))
    assert lint["success"] is True
    install_fake_marp(project_root)
    report = render_presentation(project_root, slug, "p01", stage="author")
    assert report["success"] is True
    build = task / "workers" / "author-coordinator" / "drafts" / "p01" / "build"
    assert (build / "p01.pdf").is_file()
    assert not list(build.rglob("*.html"))
    inspection = read_json(build / "pdf-inspection-author.json")
    assert inspection["page_count"] == 2
    assert inspection["success"] is True


def test_python_asset_disabled_by_default(project_root: Path) -> None:
    slug, task = initialize_one_deck(project_root)
    complete_author_source(task)
    author = finalize_canonical_source(project_root, slug, task)
    script = author / "assets" / "scripts" / "figure.py"
    script.parent.mkdir(parents=True, exist_ok=True)
    script.write_text("print('not run')", encoding="utf-8")
    (author / "ASSET-DECISIONS.yaml").write_text(
        "schema_version: 1\npresentation_id: p01\npolicy:\n  python_generated: disabled\n"
        "assets:\n  - id: fig1\n    path: assets/fig1.svg\n    purpose: diagram\n"
        "    generated_by: python\n    approved: true\n    generator: assets/scripts/figure.py\n"
        "    report: assets/reports/fig1.json\n    contains_text: true\n"
        "    alternatives_considered: [markdown_table, css_layout]\n"
        "    why_image_needed: spatial relation\n",
        encoding="utf-8",
    )
    report = validate_assets(project_root, slug, "p01", source_root=author, stage="author")
    assert report["success"] is False
    with pytest.raises(MPresError, match="disabled"):
        run_python_asset(project_root, slug, "p01", source_root=author, asset_id="fig1")
