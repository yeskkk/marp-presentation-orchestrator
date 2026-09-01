from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from mpres.util import MPresError, read_yaml, task_path

PRODUCTION_MODES = (
    "greenfield_full",
    "greenfield_compact",
    "legacy_migration",
    "targeted_revision",
)

COURSE_FULL_STAGES = (
    "01_scope_sources",
    "02_learner_need",
    "03_domain_development",
    "04_entry_diagnostics",
    "05_learner_language",
    "06_marp_integration",
)
REPORT_COMPACT_STAGES = (
    "01_scope_sources",
    "02_audience_domain",
    "03_narrative_language",
    "04_marp_integration",
)
MIGRATION_STAGES = (
    "m01_baseline_audit",
    "m02_delta_design_patch",
    "m03_integration_semantic_check",
)
TARGETED_REVISION_STAGES = (
    "r01_defect_scope",
    "r02_patch_regression",
)


@dataclass(frozen=True)
class ProductionProfile:
    mode: str
    stage_profile: str
    stages: tuple[str, ...]
    unit_granularity: str
    review_scope: str
    lazy_unit_initialization: bool = True


def profile_for(mode: str, task_kind: str) -> ProductionProfile:
    if mode not in PRODUCTION_MODES:
        raise MPresError(f"Unsupported production mode: {mode!r}.")
    if task_kind not in {"course", "report"}:
        raise MPresError(f"Unsupported task kind: {task_kind!r}.")
    if mode == "greenfield_full":
        if task_kind == "course":
            return ProductionProfile(mode, "course_six", COURSE_FULL_STAGES, "lesson", "full_deck")
        return ProductionProfile(mode, "report_compact", REPORT_COMPACT_STAGES, "content_unit", "full_deck")
    if mode == "greenfield_compact":
        # Compact greenfield work deliberately uses the four-stage profile for both task kinds.
        return ProductionProfile(mode, "greenfield_compact_four", REPORT_COMPACT_STAGES, "lesson", "full_deck")
    if mode == "legacy_migration":
        # The user selected one fixed author per lesson even for migration work.
        return ProductionProfile(mode, "migration_three", MIGRATION_STAGES, "lesson", "full_deck")
    return ProductionProfile(mode, "targeted_revision_two", TARGETED_REVISION_STAGES, "lesson", "full_deck")


def load_production_profile(root: Path, slug: str) -> dict[str, Any]:
    path = task_path(root, slug) / "PRODUCTION-PROFILE.yaml"
    value = read_yaml(path)
    if not isinstance(value, dict):
        raise MPresError(f"Production profile is missing or malformed: {path}")
    mode = str(value.get("mode") or "")
    task_kind = str(value.get("task_kind") or "")
    expected = profile_for(mode, task_kind)
    if value.get("stage_profile") != expected.stage_profile:
        raise MPresError(
            f"PRODUCTION-PROFILE stage_profile {value.get('stage_profile')!r} does not match "
            f"mode {mode!r} ({expected.stage_profile!r})."
        )
    if tuple(value.get("stages") or ()) != expected.stages:
        raise MPresError("PRODUCTION-PROFILE stages do not match its selected mode.")
    if value.get("unit_granularity") != expected.unit_granularity:
        raise MPresError("PRODUCTION-PROFILE unit_granularity is inconsistent.")
    if value.get("review_scope") != "full_deck":
        raise MPresError("Every one of the five reviewers must read the full frozen deck.")
    return value


def stage_ids_for_profile(mode: str, task_kind: str) -> tuple[str, ...]:
    return profile_for(mode, task_kind).stages
