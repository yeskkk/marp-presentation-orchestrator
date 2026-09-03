from __future__ import annotations

from pathlib import Path
from typing import Any

from mpres.assignments import batch_plan_status
from mpres.state import get_presentation, load_state
from mpres.stages import stage_status
from mpres.tasks import require_gate
from mpres.util import (
    MPresError,
    read_yaml,
    relative_display,
    task_path,
    text_placeholders,
    utc_now,
    write_yaml_atomic,
)


def _mapping(path: Path, *, label: str) -> dict[str, Any]:
    value = read_yaml(path)
    if not isinstance(value, dict):
        raise MPresError(f"{label} is missing or malformed: {path}")
    placeholders = text_placeholders(path)
    if placeholders:
        raise MPresError(f"{label} still contains placeholders: {placeholders[:8]}")
    return value


def _presentation_batch_row(plan: dict[str, Any], presentation_id: str) -> dict[str, Any]:
    for row in plan.get("presentations", []):
        if isinstance(row, dict) and row.get("id") == presentation_id:
            return row
    raise MPresError(f"Approved batch plan has no presentation {presentation_id}.")


def compile_author_context_packet(
    root: Path,
    slug: str,
    presentation_id: str,
    *,
    source_root: Path,
) -> dict[str, Any]:
    """Compile one durable deck context packet from accepted lesson handoffs.

    The packet is deliberately self-contained enough for a later deck-revision-author. It points to
    integrated lesson snapshots rather than live lesson-author workspaces, so original lesson threads
    may be closed immediately after handoff.
    """

    require_gate(root, slug)
    state = load_state(root, slug)
    presentation = get_presentation(state, presentation_id)
    batch = batch_plan_status(root, slug)
    if not batch.get("approved") or not isinstance(batch.get("value"), dict):
        raise MPresError("A planner-approved batch plan is required to compile author context.")
    plan = batch["value"]
    presentation_plan = _presentation_batch_row(plan, presentation_id)
    unit_plan_by_id = {
        str(row.get("id")): row
        for row in presentation_plan.get("units", [])
        if isinstance(row, dict) and row.get("id")
    }

    units: list[dict[str, Any]] = []
    for unit in presentation.get("content_units", []):
        unit_id = str(unit.get("id"))
        integrated = source_root / "sections" / unit_id
        manifest = _mapping(integrated / "UNIT-MANIFEST.yaml", label="Integrated UNIT-MANIFEST")
        context = _mapping(integrated / "UNIT-CONTEXT-PACKET.yaml", label="Integrated UNIT-CONTEXT-PACKET")
        delta = _mapping(integrated / "UNIT-DELTA.yaml", label="Integrated UNIT-DELTA")
        plan_row = unit_plan_by_id.get(unit_id)
        if not isinstance(plan_row, dict):
            raise MPresError(f"Approved batch plan has no unit {presentation_id}/{unit_id}.")
        stages = stage_status(root, slug, presentation_id, unit_id)
        if stages.get("sequence_status") != "completed":
            raise MPresError(f"Cannot compile author context before {presentation_id}/{unit_id} stages complete.")
        units.append(
            {
                "id": unit_id,
                "title": unit.get("title"),
                "global_meeting_number": unit.get("global_meeting_number"),
                "deck_local_ordinal": unit.get("deck_local_ordinal"),
                "meeting_label": unit.get("meeting_label"),
                "organization_basis": unit.get("organization_basis"),
                "fixed_author_policy": "one fixed lesson-author for all profile stages",
                "integrated_snapshot": relative_display(integrated, root),
                "slide_ids": manifest.get("slide_ids") or [],
                "assignment_source": batch.get("path"),
                "unit_scope": plan_row.get("unit_scope"),
                "audience_context": plan_row.get("audience_context"),
                "prior_knowledge_to_reactivate": plan_row.get("prior_knowledge_to_reactivate"),
                "local_decision_rights": plan_row.get("local_decision_rights") or [],
                "approved_text_sources": context.get("approved_text_sources") or [],
                "baseline": delta.get("baseline") or {},
                "required_changes": delta.get("required_changes") or [],
                "continuity_risks": delta.get("continuity_risks") or [],
                "stage_handoff": {
                    "profile": stages.get("stage_profile"),
                    "stage_order": stages.get("stage_order") or [],
                    "sequence_status": stages.get("sequence_status"),
                    "completed_utc": stages.get("completed_utc"),
                },
            }
        )

    continuity_path = source_root / "PRESENTATION-CONTINUITY-MAP.yaml"
    continuity: dict[str, Any] | None = None
    if continuity_path.is_file() and not text_placeholders(continuity_path):
        value = read_yaml(continuity_path)
        if isinstance(value, dict):
            continuity = value

    packet = {
        "schema_version": 2,
        "task_slug": slug,
        "presentation_id": presentation_id,
        "presentation_title": presentation.get("title"),
        "created_utc": utc_now(),
        "created_for": ["author-coordinator-handoff", "deck-revision-author"],
        "production_mode": state.get("production_mode"),
        "stage_profile": state.get("stage_profile"),
        "planner_semantic_owner": True,
        "planner_actor": plan.get("planner_actor"),
        "assignment_semantics_source": batch.get("path"),
        "main_agent_exclusive_work": ["write_or_revise_TASK_md"],
        "all_other_planner_work_may_be_delegated": True,
        "one_fixed_author_per_lesson": True,
        "original_lesson_author_threads_may_be_closed": True,
        "invariants": {
            "batch_hard_constraints": (plan.get("common") or {}).get("hard_constraints") or [],
            "presentation_common_constraints": presentation_plan.get("common_constraints") or [],
            "full_deck_review": {
                "reviewer_count": 5,
                "each_reviewer_reads_entire_frozen_deck": True,
                "post_revision_reviewer_round": False,
            },
            "course_registry_paths": [
                relative_display(task_path(root, slug) / "COURSE-TERMINOLOGY.yaml", root),
                relative_display(task_path(root, slug) / "COURSE-SEMANTIC-OBJECTS.yaml", root),
                relative_display(task_path(root, slug) / "CROSS-DECK-HANDOFFS.yaml", root),
            ],
        },
        "cross_unit_dependencies": continuity or {
            "status": "captured_by_integrated_unit_snapshots_and_presentation_maps",
            "continuity_map_path": relative_display(continuity_path, root),
        },
        "units": units,
        "review_handoff": None,
        "mechanical_gates_to_rerun_after_revision": [
            "source_lint",
            "asset_and_geogebra_validation",
            "course_consistency",
            "slide_density",
            "math_source_and_renderer",
            "temporary_html_overflow",
            "pdf_inspection",
        ],
    }
    path = source_root / "AUTHOR-CONTEXT-PACKET.yaml"
    write_yaml_atomic(path, packet)
    return {**packet, "path": relative_display(path, root)}


def enrich_revision_context_packet(
    root: Path,
    slug: str,
    presentation_id: str,
    *,
    source_root: Path,
    frozen_source: Path,
    finding_registry: Path,
    review_plan: Path,
) -> dict[str, Any]:
    """Enrich the revision context once and preserve it on workspace recovery."""

    require_gate(root, slug)
    path = source_root / "AUTHOR-CONTEXT-PACKET.yaml"
    if path.is_file() and not text_placeholders(path):
        packet = read_yaml(path)
    else:
        frozen_packet = frozen_source / "AUTHOR-CONTEXT-PACKET.yaml"
        if not frozen_packet.is_file() or text_placeholders(frozen_packet):
            raise MPresError("Frozen source lacks the durable AUTHOR-CONTEXT-PACKET.yaml.")
        packet = read_yaml(frozen_packet)
    if not isinstance(packet, dict):
        raise MPresError("AUTHOR-CONTEXT-PACKET.yaml is malformed.")
    registry = _mapping(finding_registry, label="Finding registry")
    plan = _mapping(review_plan, label="Review plan")
    finding_ids = [
        str(row.get("id"))
        for row in registry.get("findings", [])
        if isinstance(row, dict) and row.get("id")
    ]
    expected_handoff = {
        "frozen_source": relative_display(frozen_source, root),
        "finding_registry": relative_display(finding_registry, root),
        "review_plan": relative_display(review_plan, root),
        "review_scope": plan.get("scope"),
        "all_five_reviewers_read_entire_deck": plan.get("all_five_reviewers_read_entire_deck"),
        "finding_ids": finding_ids,
        "finding_count": len(finding_ids),
        "target_role": "deck-revision-author",
        "original_lesson_authors_reopened": False,
    }
    existing_handoff = packet.get("review_handoff")
    if isinstance(existing_handoff, dict):
        mismatches = [
            key for key, value in expected_handoff.items() if existing_handoff.get(key) != value
        ]
        if mismatches:
            raise MPresError(
                "Existing revision context belongs to a different review handoff and will not be overwritten: "
                + ", ".join(mismatches)
            )
        return {
            **packet,
            "path": relative_display(path, root),
            "already_enriched": True,
        }

    packet["created_for"] = ["deck-revision-author"]
    packet["revision_handoff_utc"] = utc_now()
    packet["original_lesson_author_threads_may_be_closed"] = True
    packet["review_handoff"] = expected_handoff
    write_yaml_atomic(path, packet)
    return {
        **packet,
        "path": relative_display(path, root),
        "already_enriched": False,
    }
