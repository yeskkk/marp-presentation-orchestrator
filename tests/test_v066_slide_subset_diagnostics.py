from __future__ import annotations

import stat
from pathlib import Path

import pytest

from mpres.diagnostics import (
    diagnostic_status,
    open_diagnostic_case,
    submit_diagnostic_result,
)
from mpres.rendering import render_presentation
from mpres.runtime_profile import load_runtime_profile, resolve_runtime
from mpres.threads import register_thread
from mpres.util import MPresError, read_yaml, write_yaml_atomic

from .conftest import (
    initialize_one_deck,
    planner_write_and_approve,
    prepare_author_source,
    release_zero_finding_deck,
)


def _authoring_deck(project_root: Path, *, slug: str = "test-task") -> tuple[str, Path, Path]:
    slug, task = initialize_one_deck(project_root, slug=slug)
    source = prepare_author_source(project_root, slug, task)
    return slug, task, source


def _write_result(
    path: Path,
    *,
    case_id: str,
    evidence_slide: str,
    action: str = "targeted_patch",
    expansion: bool = False,
    patch_slides: list[str] | None = None,
) -> None:
    patch_slides = [] if patch_slides is None and expansion else (patch_slides or [evidence_slide])
    write_yaml_atomic(
        path,
        {
            "schema_version": 1,
            "case_id": case_id,
            "presentation_id": "p01",
            "diagnostic_status": "complete",
            "summary": (
                "The bounded source shows that the learner-facing sentence names an object but "
                "does not state the instructional purpose that the user expected."
            ),
            "root_cause_hypotheses": [
                {
                    "hypothesis": (
                        "The slide compresses object identification and instructional motivation "
                        "into one vague sentence."
                    ),
                    "evidence": [
                        {
                            "slide_id": evidence_slide,
                            "observation": (
                                "The visible sentence says that a concept is needed without naming "
                                "the concrete problem it resolves."
                            ),
                        }
                    ],
                }
            ],
            "confidence": "low" if expansion else "high",
            "affected_slide_ids": [] if expansion else [evidence_slide],
            "scope_expansion_required": expansion,
            "recommended_action": action,
            "patch_scope": {
                "slide_ids": patch_slides,
                "files": [] if expansion else ["presentation.md"],
                "permitted_changes": (
                    []
                    if expansion
                    else ["Clarify the named learner-facing sentence without changing the page order."]
                ),
                "forbidden_changes": (
                    []
                    if expansion
                    else ["Do not change neighboring examples, interactions, or the teaching sequence."]
                ),
                "regression_checks": (
                    []
                    if expansion
                    else ["Check the changed slide and neighbors, then run the complete deck gates."]
                ),
            },
            "source_modified": False,
            "remaining_uncertainty": (
                "The wider dependency is unknown from this bounded packet."
                if expansion
                else "none"
            ),
        },
    )


def test_open_case_copies_only_target_neighbors_and_filtered_evidence(project_root: Path) -> None:
    slug, task, source = _authoring_deck(project_root)
    render_presentation(project_root, slug, "p01", stage="author", timeout=60)
    original = (source / "presentation.md").read_bytes()

    case = open_diagnostic_case(
        project_root,
        slug,
        "p01",
        user_report=(
            "The first diagnostic question appears to blur the condition and conclusion, and the "
            "surrounding explanation may be responsible."
        ),
        slide_ids=["p01-u01-q1"],
        neighbor_radius=1,
    )

    base = task / "diagnostics" / "p01" / case["case_id"]
    index = read_yaml(base / "evidence" / "SLIDE-INDEX.yaml")
    assert [row["slide_id"] for row in index["included_slides"]] == [
        "p01-u01-s01",
        "p01-u01-q1",
        "p01-u01-a1",
    ]
    subset = (base / "evidence" / "SLIDE-SUBSET.md").read_text(encoding="utf-8")
    assert "p01-u01-q1" in subset
    assert "p01-u01-q2" not in subset
    assert not list(base.rglob("*.pdf"))
    assert not ((base / "evidence").stat().st_mode & stat.S_IWUSR)
    gate = read_yaml(base / "evidence" / "GATE-EVIDENCE.yaml")
    assert gate["available"] is True
    assert case["runtime"]["reasoning_effort"] == "low"
    assert case["runtime"]["agent_may_change"] is False
    assert (source / "presentation.md").read_bytes() == original


def test_page_targets_resolve_to_slide_ids_and_case_ids_increment(project_root: Path) -> None:
    slug, task, _ = _authoring_deck(project_root)
    first = open_diagnostic_case(
        project_root,
        slug,
        "p01",
        user_report="The wording on page three may unintentionally reveal the intended reasoning pattern.",
        page_numbers=[3],
        neighbor_radius=0,
    )
    second = open_diagnostic_case(
        project_root,
        slug,
        "p01",
        user_report="The answer page immediately after the first question may overstate the conclusion.",
        page_numbers=[4],
        neighbor_radius=0,
    )
    assert first["case_id"] == "d0001"
    assert second["case_id"] == "d0002"
    assert first["scope"]["target_slide_ids"] == ["p01-u01-q1"]
    assert second["scope"]["target_slide_ids"] == ["p01-u01-a1"]
    listing = diagnostic_status(project_root, slug, "p01")
    assert listing["case_count"] == 2
    assert [row["case_id"] for row in listing["cases"]] == ["d0001", "d0002"]


def test_fast_path_rejects_unknown_or_excessive_scope(project_root: Path) -> None:
    slug, _, _ = _authoring_deck(project_root)
    with pytest.raises(MPresError, match="Unknown diagnostic slide IDs"):
        open_diagnostic_case(
            project_root,
            slug,
            "p01",
            user_report="The user identified a concrete problem, but the supplied slide identifier is invalid.",
            slide_ids=["missing-slide"],
        )
    with pytest.raises(MPresError, match="Neighbor radius"):
        open_diagnostic_case(
            project_root,
            slug,
            "p01",
            user_report="The user identified a concrete problem and asked for too broad a neighboring range.",
            slide_ids=["p01-u01-q1"],
            neighbor_radius=3,
        )


def test_submit_requires_planner_approval_and_generates_advisory_patch_scope(project_root: Path) -> None:
    slug, task, source = _authoring_deck(project_root)
    original = (source / "presentation.md").read_bytes()
    case = open_diagnostic_case(
        project_root,
        slug,
        "p01",
        user_report=(
            "The introductory sentence does not explain which learner problem motivates the new concept."
        ),
        slide_ids=["p01-u01-s01"],
        neighbor_radius=1,
    )
    base = task / "diagnostics" / "p01" / case["case_id"]
    result_path = base / "response" / "DIAGNOSTIC-RESULT.yaml"
    _write_result(result_path, case_id=case["case_id"], evidence_slide="p01-u01-s01")

    with pytest.raises(MPresError, match="incomplete or unapproved"):
        submit_diagnostic_result(project_root, slug, "p01", case["case_id"])

    planner_write_and_approve(project_root, slug, base / "TASK-DIAGNOSTIC-REVIEWER.md")
    submitted = submit_diagnostic_result(project_root, slug, "p01", case["case_id"])
    assert submitted["case"]["status"] == "completed"
    assert submitted["patch_scope"]["status"] == "proposed_requires_planner_authorization"
    assert submitted["patch_scope"]["automatic_source_edit"] is False
    assert submitted["patch_scope"]["full_deck_gate_after_any_patch"] is True
    assert (source / "presentation.md").read_bytes() == original
    assert not ((base / "response").stat().st_mode & stat.S_IWUSR)


def test_result_cannot_cite_or_patch_outside_packet(project_root: Path) -> None:
    slug, task, _ = _authoring_deck(project_root)
    case = open_diagnostic_case(
        project_root,
        slug,
        "p01",
        user_report="The introductory sentence is vague; check only that page before authorizing any broader work.",
        slide_ids=["p01-u01-s01"],
        neighbor_radius=0,
    )
    base = task / "diagnostics" / "p01" / case["case_id"]
    planner_write_and_approve(project_root, slug, base / "TASK-DIAGNOSTIC-REVIEWER.md")
    result_path = base / "response" / "DIAGNOSTIC-RESULT.yaml"
    _write_result(
        result_path,
        case_id=case["case_id"],
        evidence_slide="p01-u01-s01",
        patch_slides=["p01-u01-q2"],
    )
    with pytest.raises(MPresError, match="exceed the evidence packet"):
        submit_diagnostic_result(project_root, slug, "p01", case["case_id"])


def test_insufficient_evidence_requests_new_scope_without_runtime_change_or_patch(project_root: Path) -> None:
    slug, task, _ = _authoring_deck(project_root)
    case = open_diagnostic_case(
        project_root,
        slug,
        "p01",
        user_report=(
            "The user suspects a continuity problem, but only the local introductory slide is currently identified."
        ),
        slide_ids=["p01-u01-s01"],
        neighbor_radius=0,
    )
    base = task / "diagnostics" / "p01" / case["case_id"]
    planner_write_and_approve(project_root, slug, base / "TASK-DIAGNOSTIC-REVIEWER.md")
    _write_result(
        base / "response" / "DIAGNOSTIC-RESULT.yaml",
        case_id=case["case_id"],
        evidence_slide="p01-u01-s01",
        action="open_larger_diagnostic_case",
        expansion=True,
    )
    submitted = submit_diagnostic_result(project_root, slug, "p01", case["case_id"])
    assert submitted["result"]["confidence"] == "low"
    assert submitted["result"]["scope_expansion_required"] is True
    assert submitted["patch_scope"]["status"] == "scope_expansion_required"
    assert submitted["patch_scope"]["slide_ids"] == []
    assert submitted["patch_scope"]["automatic_source_edit"] is False
    assert case["runtime"]["agent_may_change"] is False


def test_finalized_deck_uses_current_published_source_without_overwriting_release(project_root: Path) -> None:
    slug, task, release = release_zero_finding_deck(project_root, slug="published-diagnostic")
    published_source = project_root / release["source"] / "presentation.md"
    before = published_source.read_bytes()
    case = open_diagnostic_case(
        project_root,
        slug,
        "p01",
        user_report=(
            "After publication, the learner reports that the first question's wording is harder to parse than intended."
        ),
        slide_ids=["p01-u01-q1"],
        neighbor_radius=1,
    )
    assert case["source_anchor"]["kind"] == "published_base_revision"
    assert case["source_anchor"]["hashes_generated"] is False
    assert published_source.read_bytes() == before
    assert (task / "deliverables" / "p01" / "release.json").is_file()


def test_diagnostic_role_is_fixed_reviewer_runtime(project_root: Path) -> None:
    slug, _, _ = _authoring_deck(project_root)
    profile = load_runtime_profile(project_root, slug)
    runtime = resolve_runtime(profile, "diagnostic-reviewer", presentation_id="p01")
    assert runtime["runtime_family"] == "reviewer"
    assert runtime["model"] == "gpt-5.6-sol"
    assert runtime["reasoning_effort"] == "low"
    with pytest.raises(MPresError, match="Runtime mismatch"):
        register_thread(
            project_root,
            slug,
            handle_id="diag-wrong-runtime",
            runtime_name="diagnostic-reviewer",
            role="diagnostic-reviewer",
            actual_model="gpt-5.6-sol",
            actual_reasoning_effort="medium",
            presentation_id="p01",
        )
