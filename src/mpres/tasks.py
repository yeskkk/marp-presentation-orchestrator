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
from mpres.state import SCHEMA_VERSION, load_state, save_state, state_file
from mpres.util import (
    MPresError,
    relative_display,
    task_path,
    task_sha256,
    text_placeholders,
    utc_now,
    write_json_atomic,
    read_yaml,
)

STOP_MODES = {"pilot", "each", "all"}


def _copy_policy_templates(root: Path, task: Path, slug: str, kind: str) -> None:
    templates = {
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
        text = text.replace("[[TASK_SLUG]]", slug)
        text = text.replace("[[REPOSITORY_PATH]]", ".")
        text = text.replace("[[TASK_KIND_CODE]]", kind)
        text = text.replace("[[MCQ_ENABLED]]", "true" if kind == "course" else "false")
        text = text.replace(
            "[[AUTHORING_STAGE_PROFILE]]",
            "course_six" if kind == "course" else "report_compact",
        )
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


def create_task(
    *,
    root: Path,
    title: str,
    slug: str | None,
    kind: str,
    stop_mode: str,
    sessions: int | None,
    minutes: int | None,
) -> tuple[str, Path]:
    title = title.strip()
    if not title:
        raise MPresError("The title/topic is required.")
    if kind not in {"course", "report"}:
        raise MPresError("Task kind must be course or report.")
    if stop_mode not in STOP_MODES:
        raise MPresError("Stop mode must be pilot, each, or all.")
    if kind == "course" and (sessions is None or minutes is None):
        raise MPresError("A course requires --sessions and --minutes.")
    if sessions is not None and sessions <= 0:
        raise MPresError("--sessions must be positive.")
    if minutes is not None and minutes <= 0:
        raise MPresError("--minutes must be positive.")

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
    ]:
        directory.mkdir(parents=True, exist_ok=True)

    template = (root / "templates" / "TASK.template.md").read_text(encoding="utf-8")
    replacements = {
        "[[TASK_TITLE]]": title,
        "[[TASK_SLUG]]": selected_slug,
        "[[TASK_KIND]]": "课程" if kind == "course" else "单次报告",
        "[[TASK_KIND_CODE]]": kind,
        "[[STOP_MODE]]": stop_mode,
        "[[TASK_NAME]]": title,
        "[[SESSION_COUNT_OR_NA]]": str(sessions) if sessions is not None else "不适用",
        "[[MINUTES_OR_NA]]": str(minutes) if minutes is not None else "不适用",
        "[[AUTHORING_STAGE_DESCRIPTION]]": (
            "每个 lesson-author 在一份 planner assignment 和同一个 thread 内采用六阶段课程写作流程；"
            if kind == "course"
            else "每个 lesson-author 在一份 planner assignment 和同一个 thread 内采用四阶段精简报告流程；"
        ),
        "[[AUTHORING_STAGE_LIST]]": (
            "1. `scope_sources`\n2. `learner_need`\n3. `domain_development`\n"
            "4. `entry_diagnostics`\n5. `learner_language`\n6. `marp_integration`"
            if kind == "course"
            else "1. `scope_sources`\n2. `audience_domain`\n"
            "3. `narrative_language`\n4. `marp_integration`"
        ),
        "[[MCQ_STAGE_REQUIREMENT]]": (
            "课程 unit 的 `entry_diagnostics` 阶段必须设计 2—3 道高质量诊断性选择题；"
            "最终集成阶段负责题答相邻分页、manifest 和 option audit。"
            if kind == "course"
            else "学术报告不设选择题数量配额；保留的互动仍须有明确作用并完成审计。"
        ),
    }
    for old, new in replacements.items():
        template = template.replace(old, new)
    (task / "TASK.md").write_text(template, encoding="utf-8", newline="\n")
    _copy_policy_templates(root, task, selected_slug, kind)
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
        "# Token usage\n\nUse exact exported counters only; unavailable values remain unavailable.\n",
        encoding="utf-8",
        newline="\n",
    )

    now = utc_now()
    state: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "task_slug": selected_slug,
        "title": title,
        "kind": kind,
        "stop_mode": stop_mode,
        "pilot_pause_completed": False,
        "sessions": sessions,
        "minutes": minutes,
        "phase": "task_draft",
        "created_utc": now,
        "updated_utc": now,
        "presented_task_sha256": None,
        "presented_utc": None,
        "confirmed_task_sha256": None,
        "confirmed_utc": None,
        "confirmation_sequence": 0,
        "presentations": [],
        "last_delivery_sequence": 0,
    }
    write_json_atomic(state_file(root, selected_slug), state)
    append_log(
        root,
        selected_slug,
        actor="planner",
        kind="decision",
        message=(
            "Created the Marp task planning directory. Remind the user that there is one full-deck "
            "five-channel review, no reviewer recheck of author changes, screenshot-free PDF-only "
            "inspection, high default reasoning, 2–3 course MCQs per unit, extracted-text-only "
            "reference access, planner-owned assignments, and disabled-by-default Python figures."
        ),
        data={"title": title, "kind": kind, "stop_mode": stop_mode},
    )
    return selected_slug, task


def present_task(root: Path, slug: str) -> dict[str, Any]:
    state = load_state(root, slug)
    pending_amendment = state.get("pending_policy_change_request")
    if state.get("presentations") and not pending_amendment:
        raise MPresError(
            "TASK.md is frozen after production initialization unless a material policy change "
            "has first been proposed with `mpres policy propose`."
        )
    task_md = task_path(root, slug) / "TASK.md"
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
        data={"task_sha256": digest, "path": relative_display(task_md, root)},
    )
    return state


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
    state["confirmed_task_sha256"] = current
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
    return True, "Confirmation gate passed.", state


def require_gate(root: Path, slug: str) -> dict[str, Any]:
    ok, message, state = gate_status(root, slug)
    if not ok:
        raise MPresError(message)
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


def continue_task(root: Path, slug: str) -> dict[str, Any]:
    state = require_gate(root, slug)
    if state.get("phase") != "awaiting_user_continuation":
        raise MPresError("Task is not paused for user continuation.")
    if state.get("stop_mode") == "pilot" and not state.get("pilot_pause_completed"):
        state["pilot_pause_completed"] = True
    state["phase"] = "working"
    policy = read_yaml(task_path(root, slug) / "EXECUTION-POLICY.yaml") or {}
    authoring = policy.get("authoring", {}) if isinstance(policy, dict) else {}
    configured = int(authoring.get("max_parallel_presentations", 2) or 2)
    capacity = 1 if state.get("stop_mode") == "each" else max(1, configured)
    active = sum(
        1
        for item in state.get("presentations", [])
        if item.get("active") and item.get("status") != "finalized"
    )
    activated: list[str] = []
    for item in state.get("presentations", []):
        if active >= capacity:
            break
        if not item.get("active") and item.get("status") != "finalized":
            item["active"] = True
            active += 1
            activated.append(str(item.get("id")))
    save_state(root, slug, state)
    append_log(
        root,
        slug,
        actor="planner",
        kind="decision",
        message="User instructed the workflow to continue after a delivery pause.",
        data={"activated_presentations": activated},
    )
    return state
