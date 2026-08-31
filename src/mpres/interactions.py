from __future__ import annotations

from pathlib import Path
from typing import Any

from mpres.util import MPresError, read_yaml

MCQ_RATIONALES = {
    "counterintuitive_conclusion",
    "error_prone_condition",
    "concept_discrimination",
    "method_choice",
    "transfer",
    "model_boundary",
}


def _mapping(path: Path) -> dict[str, Any]:
    value = read_yaml(path)
    if not isinstance(value, dict):
        raise MPresError(f"Structured interaction file must be a mapping: {path}")
    return value


def validate_interaction_records(
    interactions_value: dict[str, Any],
    mcq_value: dict[str, Any],
    *,
    task_kind: str,
) -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []
    interactions = interactions_value.get("interactions") or []
    items = mcq_value.get("items") or []
    if not isinstance(interactions, list) or any(not isinstance(item, dict) for item in interactions):
        errors.append("INTERACTION-MANIFEST interactions must be a list of mappings.")
        interactions = []
    if not isinstance(items, list) or any(not isinstance(item, dict) for item in items):
        errors.append("MCQ-AUDIT items must be a list of mappings.")
        items = []

    prompt_ids: list[str] = []
    response_ids: list[str] = []
    mcq_interactions: dict[str, dict[str, Any]] = {}
    for item in interactions:
        prompt = str(item.get("prompt_slide") or "").strip()
        response = str(item.get("response_slide") or "").strip()
        fmt = str(item.get("format") or "").strip()
        purpose = str(item.get("purpose") or "").strip()
        leakage = str(item.get("answer_leakage_check") or "").strip()
        if not prompt or not response:
            errors.append("Every interaction needs prompt_slide and response_slide.")
            continue
        if prompt == response:
            errors.append(f"Interaction {prompt} may not pair a slide with itself.")
        if len(purpose) < 12:
            errors.append(f"Interaction {prompt} needs a substantive diagnostic purpose.")
        if len(leakage) < 12:
            errors.append(f"Interaction {prompt} needs an answer-leakage check.")
        prompt_ids.append(prompt)
        response_ids.append(response)
        if fmt == "multiple_choice":
            mcq_interactions[prompt] = item
        elif fmt not in {"open_response", "worked_example_pause", "other"}:
            errors.append(f"Interaction {prompt} has unsupported format {fmt!r}.")
    if len(prompt_ids) != len(set(prompt_ids)):
        errors.append("Interaction prompt slide IDs must be unique within a unit.")
    if len(response_ids) != len(set(response_ids)):
        errors.append("Interaction response slide IDs must be unique within a unit.")

    audit_by_prompt: dict[str, dict[str, Any]] = {}
    for item in items:
        prompt = str(item.get("prompt_slide") or "").strip()
        response = str(item.get("response_slide") or "").strip()
        if not prompt:
            errors.append("Every MCQ audit item needs prompt_slide.")
            continue
        if prompt in audit_by_prompt:
            errors.append(f"MCQ audit repeats prompt slide {prompt}.")
        audit_by_prompt[prompt] = item
        if response != str(mcq_interactions.get(prompt, {}).get("response_slide") or "").strip():
            errors.append(f"MCQ audit response_slide does not match interaction pair for {prompt}.")
        if str(item.get("selection_rationale") or "").strip() not in MCQ_RATIONALES:
            errors.append(
                f"MCQ {prompt} selection_rationale must be one of {sorted(MCQ_RATIONALES)}."
            )
        if item.get("requires_fresh_inference") is not True:
            errors.append(f"MCQ {prompt} must record requires_fresh_inference: true.")
        information_state = item.get("information_state")
        if not isinstance(information_state, dict):
            errors.append(f"MCQ {prompt} information_state must be a mapping.")
        else:
            available = information_state.get("available_before_prompt")
            withheld = information_state.get("intentionally_withheld")
            if not isinstance(available, list) or not available or any(
                not str(value).strip() for value in available
            ):
                errors.append(
                    f"MCQ {prompt} must list the prerequisite information available before the prompt."
                )
            if not isinstance(withheld, list) or any(not str(value).strip() for value in withheld):
                errors.append(
                    f"MCQ {prompt} intentionally_withheld must be a list, even when empty."
                )
        if len(str(item.get("new_inference") or "").strip()) < 12:
            errors.append(f"MCQ {prompt} must state the new inference required from the learner.")
        if len(str(item.get("decision_unit") or "").strip()) < 8:
            errors.append(f"MCQ {prompt} must define one coherent decision_unit.")
        if item.get("prerequisite_available") is not True:
            errors.append(f"MCQ {prompt} must confirm prerequisite_available: true.")
        if len(str(item.get("cue_leakage_audit") or "").strip()) < 12:
            errors.append(f"MCQ {prompt} needs a substantive cue_leakage_audit.")
        composite = item.get("composite_option_check")
        if not isinstance(composite, dict):
            errors.append(f"MCQ {prompt} composite_option_check must be a mapping.")
        else:
            if composite.get("single_decision") is not True:
                errors.append(f"MCQ {prompt} options must implement one single decision.")
            if len(str(composite.get("rationale") or "").strip()) < 12:
                errors.append(f"MCQ {prompt} composite_option_check needs a rationale.")
        if len(str(item.get("preceding_comparison") or "").strip()) < 12:
            errors.append(
                f"MCQ {prompt} must explain why it is not a mechanical repeat of the preceding slide."
            )
        if len(str(item.get("purpose") or "").strip()) < 12:
            errors.append(f"MCQ {prompt} needs a substantive purpose.")
        labels = item.get("visible_labels") or []
        option_audit = item.get("option_audit") or {}
        if not isinstance(labels, list) or len(labels) < 2:
            errors.append(f"MCQ {prompt} visible_labels must list at least two labels.")
            labels = []
        if not isinstance(option_audit, dict):
            errors.append(f"MCQ {prompt} option_audit must be a mapping.")
            option_audit = {}
        normalized_labels = [str(label).strip().upper() for label in labels]
        if set(normalized_labels) != {str(key).strip().upper() for key in option_audit}:
            errors.append(f"MCQ {prompt} option_audit keys must match visible_labels exactly.")
        truth_values: list[str] = []
        for label in normalized_labels:
            row = option_audit.get(label) or option_audit.get(label.lower())
            if not isinstance(row, dict):
                errors.append(f"MCQ {prompt} option {label} audit must be a mapping.")
                continue
            if row.get("stem_compatible") is not True:
                errors.append(f"MCQ {prompt} option {label} must set stem_compatible: true.")
            truth = str(row.get("truth_status") or "").strip()
            truth_values.append(truth)
            if truth not in {"correct", "incorrect"}:
                errors.append(f"MCQ {prompt} option {label} truth_status is invalid.")
            if len(str(row.get("wording_check") or "").strip()) < 8:
                errors.append(f"MCQ {prompt} option {label} needs a wording_check.")
            if truth == "correct" and len(str(row.get("justification") or "").strip()) < 8:
                errors.append(f"MCQ {prompt} correct option {label} needs justification.")
            if truth == "incorrect" and len(str(row.get("misconception") or "").strip()) < 8:
                errors.append(f"MCQ {prompt} distractor {label} needs a misconception.")
        if "correct" not in truth_values or "incorrect" not in truth_values:
            errors.append(f"MCQ {prompt} needs at least one correct option and one distractor.")

    missing_audit = sorted(set(mcq_interactions) - set(audit_by_prompt))
    extra_audit = sorted(set(audit_by_prompt) - set(mcq_interactions))
    if missing_audit:
        errors.append("MCQ interactions missing audit rows: " + ", ".join(missing_audit))
    if extra_audit:
        errors.append("MCQ audit rows lack interaction entries: " + ", ".join(extra_audit))

    mcq_count = len(mcq_interactions)
    if task_kind == "course":
        if not 2 <= mcq_count <= 3:
            errors.append(
                f"Every course lesson must contain 2–3 diagnostic multiple-choice items; found {mcq_count}."
            )
    elif task_kind == "report":
        if mcq_count:
            warnings.append(
                "Academic reports are exempt from the MCQ quota; retained MCQs still need a clear purpose."
            )
    else:
        errors.append(f"Unsupported task kind: {task_kind!r}.")

    return {
        "schema_version": 1,
        "task_kind": task_kind,
        "interaction_count": len(interactions),
        "mcq_count": mcq_count,
        "prompt_ids": prompt_ids,
        "response_ids": response_ids,
        "errors": errors,
        "warnings": warnings,
        "success": not errors,
    }


def validate_unit_interactions(
    interaction_path: Path,
    mcq_path: Path,
    *,
    task_kind: str,
) -> dict[str, Any]:
    if not interaction_path.is_file():
        return {"success": False, "errors": [f"Missing {interaction_path}"], "warnings": []}
    if not mcq_path.is_file():
        return {"success": False, "errors": [f"Missing {mcq_path}"], "warnings": []}
    return validate_interaction_records(
        _mapping(interaction_path), _mapping(mcq_path), task_kind=task_kind
    )


def aggregate_unit_interactions(
    unit_records: list[dict[str, Any]],
    mcq_records: list[dict[str, Any]],
    *,
    presentation_id: str,
    task_kind: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    interactions_units: list[dict[str, Any]] = []
    mcq_units: list[dict[str, Any]] = []
    seen: set[str] = set()
    for interaction, mcq in zip(unit_records, mcq_records, strict=True):
        unit_id = str(interaction.get("unit_id") or "").strip()
        if not unit_id or unit_id in seen:
            raise MPresError(f"Invalid or duplicate interaction unit ID: {unit_id!r}")
        seen.add(unit_id)
        if interaction.get("presentation_id") != presentation_id:
            raise MPresError(f"Interaction unit {unit_id} belongs to another presentation.")
        if mcq.get("presentation_id") != presentation_id or mcq.get("unit_id") != unit_id:
            raise MPresError(f"MCQ audit unit mismatch for {unit_id}.")
        report = validate_interaction_records(interaction, mcq, task_kind=task_kind)
        if not report.get("success"):
            raise MPresError(
                f"Interaction/MCQ contract for {presentation_id}/{unit_id} is invalid: "
                + "; ".join(report.get("errors", [])[:8])
            )
        interactions_units.append(interaction)
        mcq_units.append(mcq)
    return (
        {
            "schema_version": 1,
            "presentation_id": presentation_id,
            "task_kind": task_kind,
            "units": interactions_units,
        },
        {
            "schema_version": 1,
            "presentation_id": presentation_id,
            "task_kind": task_kind,
            "quota": {
                "course_minimum": 2,
                "course_maximum": 3,
                "academic_report_exempt": True,
            },
            "units": mcq_units,
        },
    )


def validate_presentation_interactions(
    source_root: Path,
    manifest_rows: list[dict[str, Any]],
    *,
    task_kind: str,
) -> dict[str, Any]:
    """Cross-check aggregate interaction files against the rendered-deck manifest.

    Unit handoff validation enforces the 2–3 course-MCQ quota before integration. This second
    check prevents the integrated deck or its aggregate registries from drifting afterwards.
    """

    errors: list[str] = []
    warnings: list[str] = []
    interaction_path = source_root / "INTERACTION-MANIFEST.yaml"
    mcq_path = source_root / "MCQ-AUDIT.yaml"
    if not interaction_path.is_file() or not mcq_path.is_file():
        return {
            "success": False,
            "errors": ["INTERACTION-MANIFEST.yaml and MCQ-AUDIT.yaml are required."],
            "warnings": [],
        }
    interaction_value = _mapping(interaction_path)
    mcq_value = _mapping(mcq_path)
    interaction_units = interaction_value.get("units") or []
    mcq_units = mcq_value.get("units") or []
    if not isinstance(interaction_units, list) or any(
        not isinstance(item, dict) for item in interaction_units
    ):
        errors.append("Aggregate interaction units must be a list of mappings.")
        interaction_units = []
    if not isinstance(mcq_units, list) or any(not isinstance(item, dict) for item in mcq_units):
        errors.append("Aggregate MCQ units must be a list of mappings.")
        mcq_units = []
    interaction_by_unit = {
        str(item.get("unit_id") or "").strip(): item for item in interaction_units
    }
    mcq_by_unit = {str(item.get("unit_id") or "").strip(): item for item in mcq_units}
    registered_units = set(interaction_by_unit) | set(mcq_by_unit)
    manifest_units = {
        str(item.get("unit") or "").strip()
        for item in manifest_rows
        if isinstance(item, dict)
        and str(item.get("unit") or "").strip() in registered_units
    }
    if set(interaction_by_unit) != manifest_units:
        errors.append(
            "Aggregate interaction unit IDs must match the registered content-unit IDs in "
            "DECK-MANIFEST; front matter and non-content support slides are ignored."
        )
    if set(mcq_by_unit) != manifest_units:
        errors.append(
            "Aggregate MCQ unit IDs must match the registered content-unit IDs in "
            "DECK-MANIFEST; front matter and non-content support slides are ignored."
        )
    rows_by_id = {
        str(item.get("id")): item
        for item in manifest_rows
        if isinstance(item, dict) and item.get("id")
    }
    counts: dict[str, int] = {}
    for unit_id in sorted(manifest_units):
        interaction = interaction_by_unit.get(unit_id, {})
        mcq = mcq_by_unit.get(unit_id, {})
        interactions = interaction.get("interactions") or []
        items = mcq.get("items") or []
        if not isinstance(interactions, list) or not isinstance(items, list):
            errors.append(f"Interaction/MCQ rows for {unit_id} must be lists.")
            continue
        mcq_interactions = [
            item
            for item in interactions
            if isinstance(item, dict) and item.get("format") == "multiple_choice"
        ]
        counts[unit_id] = len(mcq_interactions)
        if task_kind == "course" and not 2 <= counts[unit_id] <= 3:
            errors.append(
                f"Course content unit {unit_id} must contain 2–3 diagnostic MCQs; "
                f"found {counts[unit_id]}."
            )
        if task_kind == "report" and counts[unit_id]:
            warnings.append(
                f"Academic report unit {unit_id} is exempt from the MCQ quota; retained MCQs "
                "still need a clear diagnostic purpose."
            )
        audit_ids = {
            str(item.get("prompt_slide") or "").strip()
            for item in items
            if isinstance(item, dict)
        }
        prompt_ids = {
            str(item.get("prompt_slide") or "").strip() for item in mcq_interactions
        }
        if audit_ids != prompt_ids:
            errors.append(f"Aggregate MCQ audit rows do not match interactions for {unit_id}.")
        for item in interactions:
            if not isinstance(item, dict):
                continue
            prompt = str(item.get("prompt_slide") or "").strip()
            response = str(item.get("response_slide") or "").strip()
            prompt_row = rows_by_id.get(prompt)
            response_row = rows_by_id.get(response)
            if prompt_row is None or response_row is None:
                errors.append(f"Interaction {prompt}->{response} is absent from DECK-MANIFEST.")
                continue
            if str(prompt_row.get("unit") or "").strip() != unit_id or str(
                response_row.get("unit") or ""
            ).strip() != unit_id:
                errors.append(f"Interaction {prompt}->{response} crosses content-unit boundaries.")
            if str(prompt_row.get("paired_with") or "").strip() != response:
                errors.append(f"DECK-MANIFEST prompt {prompt} does not pair with {response}.")
            if str(response_row.get("paired_with") or "").strip() != prompt:
                errors.append(f"DECK-MANIFEST response {response} does not pair with {prompt}.")
    return {
        "schema_version": 2,
        "task_kind": task_kind,
        "mcq_count_by_unit": counts,
        "errors": errors,
        "warnings": warnings,
        "success": not errors,
    }
