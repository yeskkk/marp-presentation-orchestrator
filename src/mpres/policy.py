from __future__ import annotations

from pathlib import Path
from typing import Any
import json
import tomllib

from mpres.state import REVIEW_CHANNELS, REVIEW_ROUNDS, load_state, save_state
from mpres.tasks import gate_status, require_gate
from mpres.util import MPresError, read_yaml, task_path, utc_now, write_yaml_atomic

MATERIAL_FIELDS = {
    "review_round_count",
    "review_channels",
    "author_revision_release_rule",
    "reference_pdf_access",
    "output_format",
    "inspection_policy",
    "assignment_ownership",
    "course_multiple_choice_quota",
}


def policy_audit(root: Path, slug: str) -> dict[str, Any]:
    gate_ok, gate_message, state = gate_status(root, slug)
    task = task_path(root, slug)
    execution = read_yaml(task / "EXECUTION-POLICY.yaml") or {}
    review = read_yaml(task / "REVIEW-PROFILE.yaml") or {}
    access = read_yaml(task / "REFERENCE-ACCESS-POLICY.yaml") or {}
    errors: list[str] = []
    warnings: list[str] = []
    if not gate_ok:
        errors.append(gate_message)
    rounds = review.get("rounds") if isinstance(review, dict) else None
    if not isinstance(rounds, list) or len(rounds) != 1 or rounds[0].get("name") != "full":
        errors.append("REVIEW-PROFILE.yaml must define exactly one full-deck round named full.")
    channels = rounds[0].get("channels") if isinstance(rounds, list) and rounds else None
    if tuple(channels or ()) != REVIEW_CHANNELS:
        errors.append("Review channels do not match the repository state machine.")
    if REVIEW_ROUNDS != ("full",):
        errors.append("Repository state machine is not configured for one review round.")
    review_policy = execution.get("review", {}) if isinstance(execution, dict) else {}
    if int(review_policy.get("mandatory_full_deck_rounds", 0) or 0) != 1:
        errors.append("EXECUTION-POLICY.yaml must require one full-deck review round.")
    if review_policy.get("post_review_verification") != "none":
        errors.append("Post-review verification must be none.")
    if review_policy.get("author_completed_revision_is_sufficient_for_release") is not True:
        errors.append("Completed author revision must be sufficient for release.")
    if execution.get("reasoning_effort_default") != "high":
        errors.append("Default worker reasoning effort must be high.")
    if (execution.get("marp") or {}).get("version_policy") != "unpinned_latest_at_install_time":
        errors.append("Marp version policy must remain unpinned.")
    if (execution.get("authoring") or {}).get("planner_writes_every_assignment") is not True:
        errors.append("The planner must personally write every exact assignment.")
    interaction = execution.get("interaction", {}) if isinstance(execution, dict) else {}
    course = interaction.get("course_multiple_choice_per_unit", {}) if isinstance(interaction, dict) else {}
    if course.get("minimum") != 2 or course.get("maximum") != 3:
        errors.append("Course MCQ quota must be 2–3 per content unit.")
    if not isinstance(access, dict):
        errors.append("REFERENCE-ACCESS-POLICY.yaml must be a mapping.")
    else:
        if access.get("mode") != "extracted_text_only":
            errors.append("Reference policy mode must be extracted_text_only.")
        if access.get("workers_may_open_original_pdf") is not False:
            errors.append("Workers must be forbidden from opening original PDFs.")
        if access.get("workers_may_receive_original_pdf_path") is not False:
            errors.append("Worker contexts must not receive original PDF paths.")
        if access.get("original_pdf_storage") != "restricted-originals":
            errors.append("Original PDFs must be stored under restricted-originals.")
    if state.get("kind") == "report" and course.get("minimum") == 2:
        # This is not a conflict because the report-specific quota is separate.
        report_quota = interaction.get("academic_report_multiple_choice_per_unit", {})
        if report_quota.get("minimum") != 0:
            errors.append("Academic reports must be exempt from the course MCQ quota.")
    if (task / "REVIEW-WORKFLOW-MIGRATION.md").exists():
        errors.append(
            "Legacy review migration file exists. Remove it and update/reconfirm TASK.md; sidecar migration may not override the task plan."
        )
    task_text = (task / "TASK.md").read_text(encoding="utf-8", errors="replace")
    legacy_phrases = ("三轮审核", "incremental review", "final review", "terminal closure")
    for phrase in legacy_phrases:
        if phrase.lower() in task_text.lower():
            errors.append(f"TASK.md contains obsolete multi-round review wording: {phrase}")
    package_lock = root / "package-lock.json"
    if package_lock.exists():
        errors.append("package-lock.json is forbidden because Marp CLI must not be version-pinned.")
    package_path = root / "package.json"
    try:
        package = json.loads(package_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        errors.append("package.json is missing or invalid.")
        package = {}
    marp_spec = ((package.get("devDependencies") or {}).get("@marp-team/marp-cli")) if isinstance(package, dict) else None
    if marp_spec not in {"latest", "*"}:
        errors.append("package.json must leave @marp-team/marp-cli unpinned (use latest or *).")
    config_paths = [root / ".codex" / "config.toml", *sorted((root / ".codex" / "agents").glob("*.toml"))]
    for config_path in config_paths:
        try:
            with config_path.open("rb") as handle:
                config = tomllib.load(handle)
        except (OSError, tomllib.TOMLDecodeError):
            errors.append(f"Codex config is missing or invalid: {config_path}")
            continue
        if config.get("model") != "gpt-5.6-sol" or config.get("model_reasoning_effort") != "high":
            errors.append(f"Codex config must use gpt-5.6-sol/high: {config_path}")
    return {
        "task_slug": slug,
        "gate_ok": gate_ok,
        "errors": errors,
        "warnings": warnings,
        "ok": not errors,
    }


def propose_policy_change(
    root: Path,
    slug: str,
    *,
    request_id: str,
    fields: list[str],
    reason: str,
) -> dict[str, Any]:
    state = require_gate(root, slug)
    if not request_id.strip() or not reason.strip():
        raise MPresError("Policy proposal requires request ID and reason.")
    if state.get("pending_policy_change_request"):
        raise MPresError(
            "Another material policy change is already awaiting TASK.md reconfirmation."
        )
    unknown = sorted(set(fields) - MATERIAL_FIELDS)
    if unknown:
        raise MPresError("Unknown material policy field(s): " + ", ".join(unknown))
    path = task_path(root, slug) / "policy-change-requests" / f"{request_id}.yaml"
    if path.exists():
        raise MPresError(f"Policy change request already exists: {path}")
    value = {
        "schema_version": 1,
        "request_id": request_id,
        "created_utc": utc_now(),
        "confirmation_sequence_at_proposal": int(state.get("confirmation_sequence", 0)),
        "requested_by": "planner",
        "status": "proposed",
        "fields_to_change": fields,
        "reason": reason.strip(),
        "requires_TASK_reconfirmation": True,
        "authoritative": False,
        "next_action": (
            "Edit TASK.md and affected policy files, run mpres task present, obtain explicit user "
            "confirmation, then run mpres task confirm. This sidecar never overrides TASK.md."
        ),
    }
    write_yaml_atomic(path, value)
    state["pending_policy_change_request"] = request_id
    state["policy_phase_before_proposal"] = state.get("phase")
    save_state(root, slug, state)
    return {**value, "path": str(path)}


def confirm_policy_change(root: Path, slug: str, *, request_id: str) -> dict[str, Any]:
    """Confirm a material amendment only after TASK.md was edited and reconfirmed.

    The sidecar records sequence and user-confirmation timing; it never overrides TASK.md and
    creates no extra hash.
    """

    state = require_gate(root, slug)
    if state.get("pending_policy_change_request") != request_id:
        raise MPresError("This policy change is not the task's pending amendment.")
    path = task_path(root, slug) / "policy-change-requests" / f"{request_id}.yaml"
    value = read_yaml(path)
    if not isinstance(value, dict) or value.get("status") != "proposed":
        raise MPresError("Policy change request is missing or is not proposed.")
    proposed_sequence = int(value.get("confirmation_sequence_at_proposal", 0))
    current_sequence = int(state.get("confirmation_sequence", 0))
    if current_sequence <= proposed_sequence:
        raise MPresError(
            "Material policy changes require editing, presenting, and reconfirming TASK.md after "
            "the proposal was created."
        )
    value.update(
        {
            "status": "confirmed",
            "confirmed_utc": utc_now(),
            "confirmed_by": "user-via-TASK-reconfirmation",
            "authoritative": False,
            "note": "TASK.md and policy files are authoritative; this record is audit history only.",
        }
    )
    audit = policy_audit(root, slug)
    if not audit.get("ok"):
        raise MPresError(
            "Reconfirmed TASK.md and policy files are still inconsistent: "
            + "; ".join(audit.get("errors", [])[:8])
        )
    state.pop("pending_policy_change_request", None)
    state.pop("policy_phase_before_proposal", None)
    state["last_confirmed_policy_change"] = request_id
    save_state(root, slug, state)
    write_yaml_atomic(path, value)
    return {**value, "path": str(path)}
