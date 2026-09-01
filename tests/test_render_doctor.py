from __future__ import annotations

from pathlib import Path

from mpres.doctor import doctor_report
from mpres.rendering import render_presentation
from mpres.util import read_json

from .conftest import initialize_one_deck, install_fake_marp, prepare_author_source


def test_pinned_marp_version_renders_pdf_only(project_root: Path) -> None:
    slug, task = initialize_one_deck(project_root)
    prepare_author_source(project_root, slug, task)
    install_fake_marp(project_root, version="4.5.0")
    report = render_presentation(project_root, slug, "p01", stage="author", timeout=120)
    assert report["success"] is True
    build = task / "workers" / "author-coordinator" / "drafts" / "p01" / "build"
    assert (build / "p01.pdf").is_file()
    assert not list(build.rglob("*.html"))
    assert read_json(build / "pdf-inspection-author.json")["success"] is True
    doctor = doctor_report(project_root, run_pdf_probe=True)
    assert doctor["marp"]["version_policy"] == "exact-pinned-version"
    assert doctor["marp"]["expected_version"] == "4.5.0"
    assert doctor["marp"]["version_matches_lock"] is True
    assert "4.5.0" in str(doctor["marp"]["version"])
    assert doctor["pdf_probe"]["ok"] is True
