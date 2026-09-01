from __future__ import annotations

from pathlib import Path
from typing import Any

from mpres.util import MPresError, read_yaml


def validate_lesson_time_plan(
    path: Path,
    *,
    task_kind: str,
    expected_meeting_number: int | None,
    expected_deck_local_ordinal: int | None = None,
    nominal_minutes: int | None = None,
) -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []
    value = read_yaml(path)
    if not isinstance(value, dict):
        return {"success": False, "errors": ["LESSON-TIME-PLAN.yaml must be a mapping."], "warnings": []}
    if value.get("task_kind") != task_kind:
        errors.append("Time plan task_kind does not match the task.")
    if value.get("policy") != "advisory_not_hard_gate":
        errors.append("Time plan policy must be advisory_not_hard_gate.")
    if value.get("stop_at_class_end") is not True:
        errors.append("Course time plan must allow stopping at class end without finishing optional examples.")
    meeting_number = value.get("global_meeting_number", value.get("meeting_number"))
    deck_local_ordinal = value.get("deck_local_ordinal")
    if task_kind == "course":
        if meeting_number != expected_meeting_number:
            errors.append(
                f"Time plan meeting_number must be {expected_meeting_number}, got {meeting_number!r}."
            )
        if expected_deck_local_ordinal is not None and deck_local_ordinal != expected_deck_local_ordinal:
            errors.append(
                f"Time plan deck_local_ordinal must be {expected_deck_local_ordinal}, got {deck_local_ordinal!r}."
            )
        if value.get("organization_basis") != "course_meeting":
            errors.append("Course units must use organization_basis: course_meeting.")
        recorded_nominal = value.get("nominal_class_minutes")
        if nominal_minutes is not None and recorded_nominal != nominal_minutes:
            errors.append(
                f"Time plan nominal_class_minutes must match TASK ({nominal_minutes})."
            )
        prepared = value.get("prepared_material_target_minutes")
        core = value.get("core_path_target_minutes")
        extension = value.get("extension_example_target_minutes")
        for name, number in (("prepared_material_target_minutes", prepared), ("core_path_target_minutes", core), ("extension_example_target_minutes", extension)):
            if not isinstance(number, int) or number < 0:
                errors.append(f"{name} must be a non-negative integer.")
        if isinstance(prepared, int) and isinstance(recorded_nominal, int) and recorded_nominal > 0:
            ratio = prepared / recorded_nominal
            if ratio < 1.2:
                warnings.append(
                    "Prepared material is close to the nominal class duration; consider a larger optional example bank."
                )
            elif ratio > 2.5:
                warnings.append(
                    "Prepared material exceeds 2.5 times the nominal duration; verify that the core/extension boundary is clear."
                )
        if isinstance(core, int) and isinstance(recorded_nominal, int) and core > recorded_nominal * 1.25:
            warnings.append(
                "The declared core path exceeds the nominal class duration by more than 25%; this is advisory, but the stopping point may be unclear."
            )
        bank = value.get("extension_example_bank")
        if not isinstance(bank, dict):
            errors.append("extension_example_bank must be a mapping.")
        elif not isinstance(bank.get("items"), list):
            errors.append("extension_example_bank.items must be a list.")
        elif not bank.get("items"):
            warnings.append(
                "The optional extension example bank is empty; the default 1.5× preparation strategy has not yet been realized."
            )
        core_path = value.get("core_path")
        if not isinstance(core_path, dict) or not str(core_path.get("planned_end_slide_id", "")).strip():
            errors.append("core_path.planned_end_slide_id must identify the natural class stopping point.")
    else:
        if value.get("organization_basis") != "report_section":
            errors.append("Academic-report units must use organization_basis: report_section.")
    return {
        "schema_version": 1,
        "path": str(path),
        "meeting_number": meeting_number,
        "global_meeting_number": meeting_number,
        "deck_local_ordinal": deck_local_ordinal,
        "errors": errors,
        "warnings": warnings,
        "success": not errors,
        "enforcement": "schema and clear stopping point are required; time totals are advisory",
    }


def aggregate_lesson_time_plans(
    plans: list[dict[str, Any]], *, presentation_id: str, task_kind: str
) -> dict[str, Any]:
    seen_units: set[str] = set()
    ordered: list[dict[str, Any]] = []
    for plan in plans:
        if not isinstance(plan, dict):
            raise MPresError("Every lesson time plan must be a mapping.")
        unit_id = str(plan.get("unit_id", "")).strip()
        if not unit_id or unit_id in seen_units:
            raise MPresError(f"Invalid or duplicate lesson time-plan unit: {unit_id!r}")
        seen_units.add(unit_id)
        ordered.append(plan)
    if task_kind == "course":
        ordered.sort(key=lambda item: int(item.get("deck_local_ordinal") or 0))
    return {
        "schema_version": 1,
        "presentation_id": presentation_id,
        "task_kind": task_kind,
        "policy": {
            "enforcement": "advisory_not_hard_gate",
            "default_prepared_to_nominal_ratio": 1.5,
            "extension_examples_are_optional_at_class_end": True,
        },
        "units": ordered,
    }
