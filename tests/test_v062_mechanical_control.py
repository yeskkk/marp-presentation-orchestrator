from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from mpres.control_jobs import (
    review_aggregation_root,
)
from mpres.production import ROLES, assignment_path
from mpres.rendering import render_presentation
from mpres.review import request_review
from mpres.runtime_profile import ROLE_FAMILIES
from mpres.util import MPresError, read_yaml

from .conftest import initialize_one_deck, install_fake_marp, prepare_author_source


def test_model_coordinator_roles_and_configs_are_removed(project_root: Path) -> None:
    assert "review-coordinator" not in ROLES
    assert "release-coordinator" not in ROLES
    assert "review-coordinator" not in ROLE_FAMILIES
    assert "release-coordinator" not in ROLE_FAMILIES
    assert not (project_root / ".codex" / "agents" / "review-coordinator.toml").exists()
    assert not (project_root / ".codex" / "agents" / "release-coordinator.toml").exists()
    assert not (
        project_root / "compat" / "legacy" / "templates" / "assignments" / "TASK-review-coordinator.template.md"
    ).exists()
    assert not (
        project_root / "compat" / "legacy" / "templates" / "assignments" / "TASK-release-coordinator.template.md"
    ).exists()
    with pytest.raises(MPresError, match="Unknown role"):
        assignment_path(project_root, "unused", "review-coordinator", "p01")
    with pytest.raises(MPresError, match="Unknown role"):
        assignment_path(project_root, "unused", "release-coordinator", "p01")


def test_freeze_registers_runtime_free_aggregation_job(project_root: Path) -> None:
    slug, task = initialize_one_deck(project_root, slug="v062-review-job")
    install_fake_marp(project_root, version="4.5.0")
    prepare_author_source(project_root, slug, task)
    assert render_presentation(project_root, slug, "p01", stage="author", timeout=60)[
        "success"
    ]
    request_review(project_root, slug, "p01")

    job_path = review_aggregation_root(project_root, slug, "p01") / "job.yaml"
    job = read_yaml(job_path)
    assert job["job"] == "review-aggregation"
    assert job["implementation"] == "python-control-plane"
    assert job["model_runtime"] is None
    assert not (task / "workers" / "review-coordinator").exists()


def test_structured_job_templates_are_runtime_free(project_root: Path) -> None:
    review = yaml.safe_load(
        (project_root / "compat" / "legacy" / "templates" / "structured" / "REVIEW-AGGREGATION-JOB.template.yaml")
        .read_text(encoding="utf-8")
        .replace("[[PRESENTATION_ID]]", "p01")
    )
    release = yaml.safe_load(
        (project_root / "compat" / "legacy" / "templates" / "structured" / "RELEASE-JOB.template.yaml")
        .read_text(encoding="utf-8")
        .replace("[[PRESENTATION_ID]]", "p01")
    )
    assert review["model_runtime"] is None
    assert release["model_runtime"] is None
    assert review["implementation"] == release["implementation"] == "python-control-plane"
