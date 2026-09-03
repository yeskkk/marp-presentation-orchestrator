from __future__ import annotations

import re
import shutil
from pathlib import Path
from typing import Any

try:
    from slugify import slugify as _slugify
except ImportError:
    _slugify = None

from mpres.logs import append_log
from mpres.milestones import record_milestone
from mpres.production_profiles import PRODUCTION_MODES, profile_for
from mpres.runtime_profile import (
    PROFILE_FILENAME,
    assert_runtime_profile_unchanged,
    load_runtime_profile,
    snapshot_for_confirmation,
)
from mpres.state import SCHEMA_VERSION, initialize_state, load_state, save_state
from mpres.transactions import transactional_task_mutation
from mpres.util import (
    MPresError,
    read_yaml,
    relative_display,
    task_path,
    task_sha256,
    text_placeholders,
    utc_now,
)

STOP_MODES = {"pilot", "each", "all"}


def _copy_policy_templates(
    root: Path,
    task: Path,
    slug: str,
    kind: str,
    production_mode: str,
) -> None:
    profile = profile_for(production_mode, kind)
    templates = {
        PROFILE_FILENAME: "policies/TASK-RUNTIME-PROFILE.template.yaml",
        "EXECUTION-POLICY.yaml": "policies/EXECUTION-POLICY.template.yaml",
        "REVIEW-PROFILE.yaml": "policies/REVIEW-PROFILE.template.yaml",
        "REVIEW-PROTOCOL.md": "policies/REVIEW-PROTOCOL.template.md",
        "CLASSROOM-SELF-CONTAINMENT-STANDARD.md": "policies/CLASSROOM-SELF-CONTAINMENT-STANDARD.template.md",
        "MARP-AUTHORING-STANDARD.md": "policies/MARP-AUTHORING-STANDARD.template.md",
        "THREAD-LIFECYCLE.md": "policies/THREAD-LIFECYCLE.template.md",
        "REFERENCE-ACCESS-POLICY.yaml": "policies/REFERENCE-ACCESS-POLICY.template.yaml",
        "POLICY-PRECEDENCE.yaml": "policies/POLICY-PRECEDENCE.template.yaml",
        "TOKEN-COLLECTOR-POLICY.yaml": "policies/TOKEN-COLLECTOR-POLICY.template.yaml",
        "WORKER-ASSIGNMENT-WRITING-STANDARD.md": "policies/WORKER-ASSIGNMENT-WRITING-STANDARD.template.md",
        "WORKER-PROMPT-PREAMBLE.md": "policies/WORKER-PROMPT-PREAMBLE.template.md",
    }
    for destination, template_name in templates.items():
        source = root / "templates" / template_name
        text = source.read_text(encoding="utf-8")
        replacements = {
            "[[TASK_SLUG]]": slug,
            "[[REPOSITORY_PATH]]": ".",
            "[[TASK_KIND_CODE]]": kind,
            "[[MCQ_ENABLED]]": "true" if kind == "course" else "false",
            "[[AUTHORING_STAGE_PROFILE]]": profile.stage_profile,
            "[[PRODUCTION_MODE]]": production_mode,
        }
        for old, new in replacements.items():
            text = text.replace(old, new)
        (task / destination).write_text(text, encoding="utf-8", newline="\n")


def _choose_slug(title: str, slug: str | None) -> str:
    if slug:
        selected = slug
    elif _slugify is not None:
        selected = _slugify(title, lowercase=True, separator="-", max_length=64)
    else:
        import unicodedata

        ascii_hint = unicodedata.normalize("NFKD", title).encode("ascii", "ignore").decode().lower()
        ascii_hint = re.sub(r"[^a-z0-9]+", "-", ascii_hint).strip("-")[:48]
        timestamp = utc_now().replace(":", "").replace("-", "").replace("T", "-")[:15]
        selected = f"{ascii_hint or 'presentation'}-{timestamp}"
    selected = re.sub(r"[^A-Za-z0-9._-]+", "-", selected).strip("-.")
    if not selected:
        selected = "presentation-" + utc_now().replace(":", "").replace("-", "")[:15]
    return selected


def _stage_description(mode: str, kind: str) -> tuple[str, str, str]:
    profile = profile_for(mode, kind)
    labels = {
        "01_scope_sources": "scope_sources",
        "02_learner_need": "learner_need",
        "03_domain_development": "domain_development",
        "04_entry_diagnostics": "entry_diagnostics",
        "05_learner_language": "learner_language",
        "06_marp_integration": "marp_integration",
        "02_audience_domain": "audience_domain",
        "03_narrative_language": "narrative_language",
        "04_marp_integration": "marp_integration",
        "m01_baseline_audit": "baseline_audit",
        "m02_delta_design_patch": "delta_design_patch",
        "m03_integration_semantic_check": "integration_semantic_check",
        "r01_defect_scope": "defect_scope",
        "r02_patch_regression": "patch_regression",
    }
    stage_list = "\n".join(
        f"{index}. `{labels.get(stage, stage)}`" for index, stage in enumerate(profile.stages, start=1)
    )
    if mode == "legacy_migration":
        description = (
            "迁移任务完全跳过绿地六阶段流程；每个课次仍固定由一名 lesson-author 在同一 thread 内完成三阶段 migration profile。"
        )
        mcq = (
            "迁移阶段保留并修正既有互动；课程 unit 仍须最终包含 2—3 道合格诊断性选择题。"
            if kind == "course"
            else "学术报告不设选择题数量配额。"
        )
    elif mode == "targeted_revision":
        description = "定点修订只执行缺陷界定和补丁回归两个阶段，不扩张范围。"
        mcq = "仅当受影响时回归检查互动题；不得借机重写整课。"
    else:
        description = (
            "每个 lesson-author 在一份 planner-approved assignment 和同一个 thread 内采用任务选定的绿地写作阶段。"
        )
        mcq = (
            "课程 unit 必须设计 2—3 道高质量诊断性选择题并完成唯一 canonical interaction record。"
            if kind == "course"
            else "学术报告不设选择题数量配额；保留互动仍须有明确作用。"
        )
    return description, stage_list, mcq


def create_task(
    *,
    root: Path,
    title: str,
    slug: str | None,
    kind: str,
    stop_mode: str,
    sessions: int | None,
    minutes: int | None,
    production_mode: str = "greenfield_full",
) -> tuple[str, Path]:
    title = title.strip()
    if not title:
        raise MPresError("The title/topic is required.")
    if kind not in {"course", "report"}:
        raise MPresError("Task kind must be course or report.")
    if production_mode not in PRODUCTION_MODES:
        raise MPresError("Unsupported production mode: " + production_mode)
    if stop_mode not in STOP_MODES:
        raise MPresError("Stop mode must be pilot, each, or all.")
    if kind == "course" and (sessions is None or minutes is None):
        raise MPresError("A course requires --sessions and --minutes.")
    if sessions is not None and sessions <= 0:
        raise MPresError("--sessions must be positive.")
    if minutes is not None and minutes <= 0:
        raise MPresError("--minutes must be positive.")

    profile = profile_for(production_mode, kind)
    selected_slug = _choose_slug(title, slug)
    task = task_path(root, selected_slug)
    if task.exists():
        raise MPresError(f"Task directory already exists: {task}")

    for directory in [
        task / "state",
        task / "logs",
        task / "downloads" / "restricted-originals",
        task / "downloads" / "text",
        task / "downloads" / "restricted-metadata",
        task / "downloads" / "tmp",
        task / "review-cache",
        task / "token-usage",
        task / "planning",
        task / "engine-incidents",
    ]:
        directory.mkdir(parents=True, exist_ok=True)

    template = (root / "templates" / "TASK.template.md").read_text(encoding="utf-8")
    description, stage_list, mcq_requirement = _stage_description(production_mode, kind)
    replacements = {
        "[[TASK_TITLE]]": title,
        "[[TASK_SLUG]]": selected_slug,
        "[[TASK_KIND]]": "课程" if kind == "course" else "单次报告",
        "[[TASK_KIND_CODE]]": kind,
        "[[STOP_MODE]]": stop_mode,
        "[[TASK_NAME]]": title,
        "[[SESSION_COUNT_OR_NA]]": str(sessions) if sessions is not None else "不适用",
        "[[MINUTES_OR_NA]]": str(minutes) if minutes is not None else "不适用",
        "[[PRODUCTION_MODE]]": production_mode,
        "[[AUTHORING_STAGE_PROFILE]]": profile.stage_profile,
        "[[AUTHORING_STAGE_DESCRIPTION]]": description,
        "[[AUTHORING_STAGE_LIST]]": stage_list,
        "[[MCQ_STAGE_REQUIREMENT]]": mcq_requirement,
    }
    for old, new in replacements.items():
        template = template.replace(old, new)
    (task / "TASK.md").write_text(template, encoding="utf-8", newline="\n")
    _copy_policy_templates(root, task, selected_slug, kind, production_mode)

    profile_template = (root / "templates" / "structured" / "PRODUCTION-PROFILE.template.yaml").read_text(encoding="utf-8")
    for old, new in {
        "[[TASK_KIND]]": kind,
        "[[PRODUCTION_MODE]]": production_mode,
        "[[STAGE_PROFILE]]": profile.stage_profile,
        "[[STAGE_LIST_FLOW]]": "[" + ", ".join(profile.stages) + "]",
        "[[UNIT_GRANULARITY]]": profile.unit_granularity,
    }.items():
        profile_template = profile_template.replace(old, new)
    (task / "PRODUCTION-PROFILE.yaml").write_text(profile_template, encoding="utf-8", newline="\n")
    shutil.copy2(
        root / "templates" / "structured" / "PERFORMANCE-BUDGET.template.yaml",
        task / "PERFORMANCE-BUDGET.yaml",
    )
    shutil.copy2(
        root / "templates" / "structured" / "MILESTONE-CHECKPOINT.template.json",
        task / "state" / "MILESTONE-CHECKPOINT.json",
    )
    (task / "THREAD-REGISTRY.yaml").write_text(
        (root / "templates" / "structured" / "THREAD-REGISTRY.template.yaml").read_text(encoding="utf-8"),
        encoding="utf-8",
        newline="\n",
    )
    (task / "policy-change-requests").mkdir(parents=True, exist_ok=True)
    (task / "downloads" / "INDEX.md").write_text(
        "# Extracted reference-text index\n\n"
        "Workers may read only files under `downloads/text/`. Original files and ingestion "
        "metadata are system-only and must never appear in assignments or review bundles.\n\n"
        "No sources have been ingested. Use `mpres reference ingest <task-slug> <source>`.\n",
        encoding="utf-8",
        newline="\n",
    )
    (task / "token-usage" / "README.md").write_text(
        "# Token usage\n\nCollect exact counters at workflow milestones; unavailable values remain unavailable.\n",
        encoding="utf-8",
        newline="\n",
    )

    now = utc_now()
    state: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "task_slug": selected_slug,
        "title": title,
        "kind": kind,
        "production_mode": production_mode,
        "stage_profile": profile.stage_profile,
        "stop_mode": stop_mode,
        "pilot_pause_completed": False,
        "sessions": sessions,
        "minutes": minutes,
        "phase": "task_draft",
        "created_utc": now,
        "updated_utc": now,
        "presented_task_sha256": None,
        "presented_utc": None,
        "presented_runtime_profile": None,
        "confirmed_task_sha256": None,
        "confirmed_utc": None,
        "confirmed_runtime_profile": None,
        "runtime_profile_locked_utc": None,
        "confirmation_sequence": 0,
        "presentations": [],
        "last_delivery_sequence": 0,
        "engine_incident_index": {
            "schema_version": 1,
            "recurrence_key": "incident_id",
            "deterministic_recurrence_threshold": 2,
            "incidents": {},
        },
        "open_engine_incident_circuits": [],
        "presented_operational_workarounds": {},
        "confirmed_operational_workarounds": {},
    }
    initialize_state(root, selected_slug, state)
    from mpres.threads import initialize_thread_registry

    initialize_thread_registry(root, selected_slug)
    from mpres.engine_incidents import initialize_incident_index

    initialize_incident_index(root, selected_slug)
    append_log(
        root,
        selected_slug,
        actor="planner",
        kind="decision",
        message=(
            "Created a profile-driven Marp task. The main agent alone writes or revises TASK.md; "
            "all later planner operations may be delegated. Control-plane scheduling is deterministic, "
            "five reviewers read the full deck, and engine bugs require a policy amendment rather than a hot patch."
        ),
        data={"title": title, "kind": kind, "stop_mode": stop_mode, "production_mode": production_mode},
    )
    return selected_slug, task


@transactional_task_mutation
def present_task(root: Path, slug: str) -> dict[str, Any]:
    state = load_state(root, slug)
    pending_amendment = state.get("pending_policy_change_request")
    if state.get("presentations") and not pending_amendment:
        raise MPresError(
            "TASK.md is frozen after production initialization unless a material policy change "
            "has first been proposed with `mpres policy propose`."
        )
    task_md = task_path(root, slug) / "TASK.md"
    runtime_profile = load_runtime_profile(root, slug)
    from mpres.engine_incidents import operational_workaround_snapshots

    workaround_snapshots = operational_workaround_snapshots(root, slug)
    confirmed_runtime_profile = state.get("confirmed_runtime_profile")
    if confirmed_runtime_profile is not None:
        assert_runtime_profile_unchanged(root, slug, confirmed_runtime_profile)
    placeholders = text_placeholders(task_md)
    if placeholders:
        raise MPresError(
            "TASK.md still contains planning placeholders: " + ", ".join(placeholders[:8])
        )
    if len(task_md.read_text(encoding="utf-8").strip()) < 1600:
        raise MPresError("TASK.md is too short to contain the required planning detail.")
    digest = task_sha256(task_md)
    snapshot = task_path(root, slug) / "state" / "TASK.presented.md"
    shutil.copy2(task_md, snapshot)
    state["phase_before_confirmation"] = state.get("phase")
    state["confirmation_kind"] = "policy_amendment" if pending_amendment else "initial"
    state["phase"] = "awaiting_user_confirmation"
    state["presented_task_sha256"] = digest
    state["presented_runtime_profile"] = runtime_profile
    state["presented_operational_workarounds"] = workaround_snapshots
    state["presented_task_snapshot"] = relative_display(snapshot, root)
    state["presented_utc"] = utc_now()
    state["confirmed_task_sha256"] = None
    state["confirmed_utc"] = None
    save_state(root, slug, state)
    append_log(
        root,
        slug,
        actor="planner",
        kind="decision",
        message="Presented the exact top-level TASK.md to the user; waiting for explicit approval.",
        data={
            "task_sha256": digest,
            "path": relative_display(task_md, root),
            "runtime_profile": runtime_profile,
            "runtime_profile_path": relative_display(
                task_path(root, slug) / PROFILE_FILENAME, root
            ),
            "operational_workarounds": workaround_snapshots,
        },
    )
    return state


@transactional_task_mutation
def confirm_task(root: Path, slug: str) -> dict[str, Any]:
    state = load_state(root, slug)
    if state.get("phase") != "awaiting_user_confirmation":
        raise MPresError("TASK.md has not been presented for the current confirmation cycle.")
    task_md = task_path(root, slug) / "TASK.md"
    current = task_sha256(task_md)
    if current != state.get("presented_task_sha256"):
        raise MPresError(
            "TASK.md changed after it was presented. Run `mpres task present` again and obtain new approval."
        )
    presented = task_path(root, slug) / "state" / "TASK.presented.md"
    if not presented.is_file() or presented.read_bytes() != task_md.read_bytes():
        raise MPresError("The stored presented TASK.md snapshot is missing or does not match.")
    confirmed = task_path(root, slug) / "state" / "TASK.confirmed.md"
    shutil.copy2(task_md, confirmed)
    runtime_profile = snapshot_for_confirmation(root, slug)
    from mpres.engine_incidents import operational_workaround_snapshots

    workaround_snapshots = operational_workaround_snapshots(root, slug)
    if workaround_snapshots != state.get("presented_operational_workarounds", {}):
        raise MPresError(
            "An operational workaround changed after TASK.md was presented. Run `mpres task "
            "present` again and obtain confirmation of the exact structured plan."
        )
    if runtime_profile != state.get("presented_runtime_profile"):
        raise MPresError(
            f"{PROFILE_FILENAME} changed after the task was presented. Run `mpres task present` "
            "again and obtain confirmation of the exact task-level runtime choices."
        )
    if state.get("confirmed_runtime_profile") is not None:
        assert_runtime_profile_unchanged(
            root,
            slug,
            state.get("confirmed_runtime_profile"),
        )
    else:
        state["confirmed_runtime_profile"] = runtime_profile
        state["runtime_profile_locked_utc"] = utc_now()
    state["confirmed_task_sha256"] = current
    state["confirmed_operational_workarounds"] = workaround_snapshots
    state["confirmed_task_snapshot"] = relative_display(confirmed, root)
    state["confirmed_utc"] = utc_now()
    state["confirmation_sequence"] = int(state.get("confirmation_sequence", 0)) + 1
    if state.get("confirmation_kind") == "policy_amendment":
        state["phase"] = state.get("phase_before_confirmation") or "working"
        state["policy_reconfirmed_utc"] = state["confirmed_utc"]
    else:
        state["phase"] = "confirmed"
    state.pop("phase_before_confirmation", None)
    state.pop("confirmation_kind", None)
    save_state(root, slug, state)
    record_milestone(root, slug, "task_confirmed", data={"confirmation_sequence": state["confirmation_sequence"]})
    append_log(
        root,
        slug,
        actor="planner",
        kind="decision",
        message="Recorded explicit user confirmation for the top-level TASK.md.",
        data={"task_sha256": current},
    )
    return state


def restore_confirmed_task(root: Path, slug: str) -> dict[str, Any]:
    state = load_state(root, slug)
    expected = state.get("confirmed_task_sha256")
    if not expected:
        raise MPresError("No confirmed TASK.md snapshot exists for this task.")
    snapshot_value = state.get("confirmed_task_snapshot")
    snapshot = (
        root / snapshot_value
        if snapshot_value
        else task_path(root, slug) / "state" / "TASK.confirmed.md"
    )
    if not snapshot.is_file():
        raise MPresError("The stored confirmed TASK.md snapshot is missing.")
    task_md = task_path(root, slug) / "TASK.md"
    shutil.copy2(snapshot, task_md)
    if task_sha256(task_md) != expected:
        raise MPresError("Restored TASK.md does not match the confirmed version.")
    append_log(
        root,
        slug,
        actor="planner",
        kind="decision",
        message="Restored TASK.md from its user-confirmed snapshot.",
        data={"task_sha256": expected},
    )
    return task_status(root, slug)


def gate_status(root: Path, slug: str) -> tuple[bool, str, dict[str, Any]]:
    state = load_state(root, slug)
    task_md = task_path(root, slug) / "TASK.md"
    if not task_md.exists():
        return False, "TASK.md is missing.", state
    confirmed = state.get("confirmed_task_sha256")
    if not confirmed:
        return False, "No confirmed TASK.md hash exists.", state
    if task_sha256(task_md) != confirmed:
        return False, "TASK.md differs from the confirmed version; confirmation is invalid.", state
    try:
        assert_runtime_profile_unchanged(
            root,
            slug,
            state.get("confirmed_runtime_profile"),
        )
    except MPresError as exc:
        return False, str(exc), state
    return True, "Confirmation gate passed.", state


def require_gate(
    root: Path,
    slug: str,
    *,
    allow_pending_policy_change: bool = False,
    allow_engine_circuit: bool = False,
) -> dict[str, Any]:
    ok, message, state = gate_status(root, slug)
    if not ok:
        raise MPresError(message)
    pending = state.get("pending_policy_change_request")
    if pending and not allow_pending_policy_change:
        raise MPresError(
            f"Task policy amendment {pending!r} is pending. Revise and reconfirm TASK.md, then "
            "confirm the amendment before resuming production."
        )
    from mpres.engine_incidents import open_circuit_ids

    open_circuits = open_circuit_ids(state)
    if open_circuits and not allow_engine_circuit:
        raise MPresError(
            "Workflow-engine circuit breaker is open for: " + ", ".join(open_circuits)
            + ". Production is blocked. Inspect `mpres engine status`, then apply an exact "
            "user-preapproved operational workaround."
        )
    return state


def task_status(root: Path, slug: str) -> dict[str, Any]:
    ok, gate_message, state = gate_status(root, slug)
    task = task_path(root, slug)
    return {
        **state,
        "task_path": relative_display(task, root),
        "task_md_current_sha256": task_sha256(task / "TASK.md") if (task / "TASK.md").exists() else None,
        "gate_ok": ok,
        "gate_message": gate_message,
    }


def list_tasks(root: Path) -> list[dict[str, Any]]:
    tasks_root = root / "tasks"
    if not tasks_root.exists():
        return []
    result: list[dict[str, Any]] = []
    for path in sorted(tasks_root.iterdir()):
        if not path.is_dir() or not (path / "state" / "task.json").exists():
            continue
        try:
            result.append(task_status(root, path.name))
        except MPresError as exc:
            result.append({"task_slug": path.name, "phase": "invalid", "error": str(exc)})
    return result


@transactional_task_mutation
def continue_task(root: Path, slug: str) -> dict[str, Any]:
    state = require_gate(root, slug)
    if state.get("phase") != "awaiting_user_continuation":
        raise MPresError("Task is not paused for user continuation.")
    if state.get("stop_mode") == "pilot" and not state.get("pilot_pause_completed"):
        state["pilot_pause_completed"] = True
    state["phase"] = "working"
    from mpres.scheduling import rebalance_active_presentations, sync_work_plan

    window = rebalance_active_presentations(
        root,
        slug,
        state,
        allow_next=state.get("stop_mode") != "each",
    )
    activated = window["activated"]
    save_state(root, slug, state)
    from mpres.production import materialize_active_author_coordinators

    materialize_active_author_coordinators(root, slug, state=state)
    sync_work_plan(root, slug, state=state)
    append_log(
        root,
        slug,
        actor="planner",
        kind="decision",
        message="User instructed the workflow to continue after a delivery pause.",
        data={"activated_presentations": activated},
    )
    return state
