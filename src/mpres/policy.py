from __future__ import annotations

from pathlib import Path
from typing import Any
import json
import tomllib

from mpres.production_profiles import load_production_profile
from mpres.runtime_profile import PROFILE_FILENAME, load_runtime_profile
from mpres.state import REVIEW_CHANNELS, REVIEW_ROUNDS, load_state, save_state
from mpres.tasks import gate_status, require_gate
from mpres.transactions import transactional_task_mutation
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
    "production_mode",
    "stage_profile",
    "planner_delegation",
    "workflow_engine_technical_fix",
}


def _expect(condition: bool, message: str, errors: list[str]) -> None:
    if not condition:
        errors.append(message)


def policy_audit(root: Path, slug: str) -> dict[str, Any]:
    """Audit task policy against the v0.6.1 execution contract.

    This audit intentionally treats an engine bug as a policy event rather than permission to
    hot-patch the framework inside a live task.
    """

    gate_ok, gate_message, state = gate_status(root, slug)
    task = task_path(root, slug)
    execution = read_yaml(task / "EXECUTION-POLICY.yaml") or {}
    review = read_yaml(task / "REVIEW-PROFILE.yaml") or {}
    access = read_yaml(task / "REFERENCE-ACCESS-POLICY.yaml") or {}
    errors: list[str] = []
    warnings: list[str] = []
    if not gate_ok:
        errors.append(gate_message)

    try:
        profile = load_production_profile(root, slug)
    except MPresError as exc:
        errors.append(str(exc))
        profile = {}
    _expect(execution.get("production_mode") == state.get("production_mode"), "Execution production_mode must match task state.", errors)
    _expect(execution.get("production_mode") == profile.get("mode"), "Execution production_mode must match PRODUCTION-PROFILE.yaml.", errors)
    _expect(execution.get("stage_profile") == state.get("stage_profile"), "Execution stage_profile must match task state.", errors)
    _expect(execution.get("stage_profile") == profile.get("stage_profile"), "Execution stage_profile must match PRODUCTION-PROFILE.yaml.", errors)

    rounds = review.get("rounds") if isinstance(review, dict) else None
    _expect(isinstance(rounds, list) and len(rounds) == 1 and rounds[0].get("name") == "full", "REVIEW-PROFILE.yaml must define exactly one full-deck round named full.", errors)
    channels = rounds[0].get("channels") if isinstance(rounds, list) and rounds else None
    _expect(tuple(channels or ()) == REVIEW_CHANNELS, "Review channels do not match the repository state machine.", errors)
    _expect(REVIEW_ROUNDS == ("full",), "Repository state machine must use exactly one review round.", errors)
    if isinstance(rounds, list) and rounds:
        _expect(rounds[0].get("scope") == "complete_frozen_deck", "The review round must cover the complete frozen deck.", errors)

    review_policy = execution.get("review", {}) if isinstance(execution, dict) else {}
    _expect(int(review_policy.get("mandatory_full_deck_rounds", 0) or 0) == 1, "EXECUTION-POLICY.yaml must require one full-deck review round.", errors)
    _expect(tuple(review_policy.get("channels") or ()) == REVIEW_CHANNELS, "Execution review channels are inconsistent.", errors)
    _expect(review_policy.get("each_reviewer_reads_entire_frozen_deck") is True, "Each of the five reviewers must read the entire frozen deck.", errors)
    _expect(review_policy.get("launch_only_after_freeze") is True, "Review workers may launch only after deck freeze.", errors)
    _expect(review_policy.get("post_review_verification") == "none", "Post-review reviewer verification must be none.", errors)
    _expect(review_policy.get("deck_revision_author_completed_revision_is_sufficient_for_release") is True, "Completed deck-revision-author work must be sufficient for release.", errors)

    try:
        runtime_profile = load_runtime_profile(root, slug)
    except MPresError as exc:
        errors.append(str(exc))
        runtime_profile = {}

    model_policy_path = root / "MODEL-POLICY.yaml"
    try:
        model_policy = read_yaml(model_policy_path)
    except Exception:
        model_policy = None
    if not isinstance(model_policy, dict):
        errors.append("MODEL-POLICY.yaml is missing or invalid.")
        model_policy = {}
    _expect(
        model_policy.get("selection_scope") == "task",
        "MODEL-POLICY.yaml must be validation-only and delegate runtime selection to the task.",
        errors,
    )
    _expect(
        model_policy.get("task_runtime_profile") == PROFILE_FILENAME,
        f"MODEL-POLICY.yaml must name {PROFILE_FILENAME} as the task runtime source.",
        errors,
    )
    _expect(
        model_policy.get("agent_may_select_or_modify_runtime") is False,
        "Project policy must forbid agents from selecting or modifying runtime choices.",
        errors,
    )
    _expect(
        execution.get("runtime_profile_source") == PROFILE_FILENAME,
        f"EXECUTION-POLICY.yaml must reference {PROFILE_FILENAME}.",
        errors,
    )
    _expect(
        execution.get("runtime_changes_during_task") == "forbidden",
        "EXECUTION-POLICY.yaml must forbid runtime changes during production.",
        errors,
    )
    _expect(
        bool(runtime_profile),
        f"{PROFILE_FILENAME} must be present and valid.",
        errors,
    )

    delegation = execution.get("planner_delegation", {}) if isinstance(execution, dict) else {}
    _expect(delegation.get("main_agent_exclusive") == ["write_or_revise_TASK_md"], "Only writing or revising TASK.md may be exclusive to the main agent.", errors)
    _expect(delegation.get("all_other_planner_operations_may_be_delegated") is True, "All planner operations other than TASK.md authorship must be delegable.", errors)
    authoring = execution.get("authoring", {}) if isinstance(execution, dict) else {}
    _expect(authoring.get("one_fixed_author_per_lesson") is True, "Migration and greenfield courses must keep one fixed author per lesson.", errors)
    _expect(authoring.get("lazy_unit_initialization") is True, "Lesson workspaces must be initialized lazily.", errors)
    _expect(authoring.get("planner_owns_assignment_semantics") is True, "Planner must own assignment semantics.", errors)
    _expect(authoring.get("approved_batch_expansion_counts_as_planner_written") is True, "Program expansion of an approved batch plan must count as planner-written assignment work.", errors)
    _expect(authoring.get("original_lesson_author_may_close_after_handoff") is True, "Lesson authors must be allowed to close after handoff.", errors)
    _expect(authoring.get("post_review_revision_role") == "deck-revision-author", "Post-review revision must be owned by deck-revision-author.", errors)
    _expect(authoring.get("speculative_prefreeze_worker_launch") == "forbidden", "Speculative pre-freeze worker launch must be forbidden.", errors)

    release = execution.get("release", {}) if isinstance(execution, dict) else {}
    _expect(release.get("launch_only_in_release_ready") is True, "The mechanical release job may be registered only in release_ready.", errors)
    _expect(release.get("prospective_hold_threads") == "forbidden", "Prospective release hold threads are forbidden.", errors)
    critical = execution.get("critical_path", {}) if isinstance(execution, dict) else {}
    _expect(critical.get("priority_order") == [
        "finish_current_review_revision_or_release",
        "finish_current_presentation",
        "start_next_ready_presentation",
        "prepare_future_metadata_without_model_workers",
    ], "Critical-path priority order is missing or inconsistent.", errors)

    marp = execution.get("marp", {}) if isinstance(execution, dict) else {}
    lock = read_yaml(root / "TOOLCHAIN-LOCK.yaml") or {}
    locked_version = str(((lock.get("marp") or {}).get("version")) or "")
    _expect(marp.get("version_policy") == "exact_pinned_version", "Marp CLI must use an exact pinned version.", errors)
    _expect(str(marp.get("version") or "") == locked_version and bool(locked_version), "Task Marp version must match TOOLCHAIN-LOCK.yaml.", errors)
    _expect(marp.get("smoke_test_required_before_production") is True, "Toolchain smoke test must pass before production.", errors)
    try:
        package = json.loads((root / "package.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        errors.append("package.json is missing or invalid.")
        package = {}
    marp_spec = ((package.get("devDependencies") or {}).get("@marp-team/marp-cli")) if isinstance(package, dict) else None
    _expect(str(marp_spec or "") == locked_version, "package.json must pin @marp-team/marp-cli to TOOLCHAIN-LOCK.yaml exactly.", errors)

    engine = execution.get("engine_changes", {}) if isinstance(execution, dict) else {}
    _expect(engine.get("in_task_hot_patch") == "forbidden", "In-task workflow-engine hot patches must be forbidden.", errors)
    _expect(engine.get("technical_bug_requires_task_policy_amendment") is True, "A technical engine bug must require a task policy amendment.", errors)
    _expect(engine.get("workflow_engine_refactoring_is_separate_work") is True, "Workflow-engine refactoring must be treated as separate work.", errors)

    token_policy = execution.get("token_accounting", {}) if isinstance(execution, dict) else {}
    _expect(token_policy.get("collection_mode") == "workflow_milestones", "Token accounting must run at workflow milestones.", errors)
    _expect(token_policy.get("periodic_model_polling") == "forbidden", "Periodic model polling for token accounting is forbidden.", errors)
    collector_policy = read_yaml(task / "TOKEN-COLLECTOR-POLICY.yaml") or {}
    _expect(
        isinstance(collector_policy, dict)
        and collector_policy.get("required_before_production") is True,
        "Token collector initialization must be required before production.",
        errors,
    )
    _expect(
        isinstance(collector_policy, dict)
        and collector_policy.get("unknown_values_remain_null") is True,
        "Unknown token counters must remain null rather than being reported as zero.",
        errors,
    )

    interaction = execution.get("interaction", {}) if isinstance(execution, dict) else {}
    course = interaction.get("course_multiple_choice_per_unit", {}) if isinstance(interaction, dict) else {}
    _expect(course.get("minimum") == 2 and course.get("maximum") == 3, "Course MCQ quota must be 2–3 per content unit.", errors)
    if state.get("kind") == "report":
        report_quota = interaction.get("academic_report_multiple_choice_per_unit", {})
        _expect(report_quota.get("minimum") == 0, "Academic reports must be exempt from the course MCQ quota.", errors)

    if not isinstance(access, dict):
        errors.append("REFERENCE-ACCESS-POLICY.yaml must be a mapping.")
    else:
        _expect(access.get("mode") == "extracted_text_only", "Reference policy mode must be extracted_text_only.", errors)
        _expect(access.get("workers_may_open_original_pdf") is False, "Workers must be forbidden from opening original PDFs.", errors)
        _expect(access.get("workers_may_receive_original_pdf_path") is False, "Worker contexts must not receive original PDF paths.", errors)
        _expect(access.get("original_pdf_storage") == "restricted-originals", "Original PDFs must be stored under restricted-originals.", errors)

    time_strategy = execution.get("course_time_strategy", {}) if isinstance(execution, dict) else {}
    _expect(time_strategy.get("enforcement") == "advisory_not_hard_gate", "Course time strategy must remain advisory, not a hard duration gate.", errors)
    _expect(float(time_strategy.get("prepared_to_nominal_ratio_default", 0) or 0) == 1.5, "Default prepared/nominal course-time ratio must be 1.5.", errors)
    _expect(time_strategy.get("organization_basis") == "numbered_course_meetings", "Course content must be organized by numbered meetings.", errors)
    inspection = execution.get("inspection", {}) if isinstance(execution, dict) else {}
    _expect(inspection.get("temporary_html_overflow_check") == "author_and_release_gate", "Temporary Marp HTML overflow inspection must be an author/release gate.", errors)
    _expect(inspection.get("reviewer_rechecks_mechanical_overflow") is False, "Reviewers must not recheck mechanical HTML overflow.", errors)
    _expect(inspection.get("screenshots") == "forbidden" and inspection.get("model_vision") == "forbidden", "Screenshots and model vision must remain forbidden.", errors)

    task_text = (task / "TASK.md").read_text(encoding="utf-8", errors="replace")
    legacy_phrases = ("三轮审核", "incremental review", "terminal closure", "planner 亲自编写每个逻辑 worker")
    for phrase in legacy_phrases:
        if phrase.lower() in task_text.lower():
            errors.append(f"TASK.md contains obsolete workflow wording: {phrase}")

    root_config_path = root / ".codex" / "config.toml"
    try:
        with root_config_path.open("rb") as handle:
            root_config = tomllib.load(handle)
    except (OSError, tomllib.TOMLDecodeError):
        errors.append(f"Codex config is missing or invalid: {root_config_path}")
        root_config = {}
    _expect(
        "model" not in root_config and "model_reasoning_effort" not in root_config,
        "Project Codex config must not hard-code planner model or reasoning effort.",
        errors,
    )
    agents_config = root_config.get("agents", {}) if isinstance(root_config, dict) else {}
    _expect(
        "default_subagent_model" not in agents_config
        and "default_subagent_reasoning_effort" not in agents_config,
        "Project Codex config must not hard-code a default subagent runtime.",
        errors,
    )
    required_agent_configs = {
        "delegated-planner",
        "author-coordinator",
        "lesson-author",
        "deck-revision-author",
        "specialist-reviewer",
    }
    present_agent_configs = {path.stem for path in (root / ".codex" / "agents").glob("*.toml")}
    missing_agent_configs = sorted(required_agent_configs - present_agent_configs)
    if missing_agent_configs:
        errors.append("Missing Codex agent configs: " + ", ".join(missing_agent_configs))
    forbidden_agent_configs = {
        "review-coordinator",
        "release-coordinator",
    } & present_agent_configs
    if forbidden_agent_configs:
        errors.append(
            "Model coordinator configs are forbidden in v0.6.2+: "
            + ", ".join(sorted(forbidden_agent_configs))
        )
    for config_path in sorted((root / ".codex" / "agents").glob("*.toml")):
        try:
            with config_path.open("rb") as handle:
                config = tomllib.load(handle)
        except (OSError, tomllib.TOMLDecodeError):
            errors.append(f"Codex agent config is missing or invalid: {config_path}")
            continue
        _expect(
            "model" not in config and "model_reasoning_effort" not in config,
            f"Agent config must obtain runtime from {PROFILE_FILENAME}, not hard-code it: {config_path}",
            errors,
        )

    return {"task_slug": slug, "gate_ok": gate_ok, "errors": errors, "warnings": warnings, "ok": not errors}

@transactional_task_mutation
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


@transactional_task_mutation
def confirm_policy_change(root: Path, slug: str, *, request_id: str) -> dict[str, Any]:
    """Confirm a material amendment only after TASK.md was edited and reconfirmed.

    The sidecar records sequence and user-confirmation timing; it never overrides TASK.md and
    creates no extra hash. This is the sole command allowed through the pending-amendment pause.
    """

    state = require_gate(root, slug, allow_pending_policy_change=True)
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
