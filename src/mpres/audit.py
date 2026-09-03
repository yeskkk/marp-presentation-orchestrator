from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from mpres.control_jobs import release_workspace, review_aggregation_root
from mpres.geogebra import validate_presentation_geogebra_registry
from mpres.engine_incidents import audit_engine_incidents
from mpres.policy import policy_audit
from mpres.production import assignment_path, check_assignment
from mpres.revision_routing import build_revision_routing
from mpres.state import REVIEW_CHANNELS, mutable_state_status
from mpres.stages import all_stages_completed
from mpres.threads import expected_runtime, list_threads
from mpres.tasks import gate_status
from mpres.util import (
    read_json,
    read_yaml,
    relative_display,
    source_tree_symlinks,
    task_path,
)

ALLOWED_HASH_KEYS = {"presented_task_sha256", "confirmed_task_sha256"}
FORBIDDEN_REFERENCE_PATH_RE = re.compile(
    r"downloads/(?:restricted-originals|originals|restricted-metadata)(?:/|\\)",
    re.IGNORECASE,
)


def _hash_keys(value: Any, prefix: str = "") -> list[str]:
    found: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            path = f"{prefix}.{key}" if prefix else str(key)
            if "sha" in str(key).lower() or "hash" in str(key).lower():
                found.append(path)
            found.extend(_hash_keys(child, path))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            found.extend(_hash_keys(child, f"{prefix}[{index}]"))
    return found


def _response_coverage(findings: list[dict[str, Any]], responses_path: Path) -> tuple[bool, str]:
    if not responses_path.is_file():
        return False, "AUTHOR-RESPONSES.yaml is missing."
    value = read_yaml(responses_path)
    rows = value.get("responses") if isinstance(value, dict) else None
    if not isinstance(rows, list) or any(not isinstance(item, dict) for item in rows):
        return False, "AUTHOR-RESPONSES.yaml must contain one response mapping per finding."
    finding_ids = {str(item.get("id")) for item in findings if item.get("id")}
    response_ids = {str(item.get("id")) for item in rows if item.get("id")}
    if finding_ids != response_ids:
        return False, "Author response IDs do not match the historical findings exactly."
    return True, ""


def _checklist_complete(path: Path) -> tuple[bool, str]:
    if not path.is_file():
        return False, "AUTHOR-MODIFICATION-CHECKLIST.yaml is missing."
    value = read_yaml(path)
    steps = value.get("steps") if isinstance(value, dict) else None
    if not isinstance(steps, dict) or not steps or any(item is not True for item in steps.values()):
        return False, "Author modification checklist is incomplete."
    if not value.get("completed_utc") or len(str(value.get("author_declaration") or "").strip()) < 20:
        return False, "Author modification checklist lacks completion time or declaration."
    return True, ""


def _audit_single_project_log(task: Path, add: Any) -> None:
    logs_root = task / "logs"
    unexpected = [
        path
        for path in logs_root.rglob("*")
        if path.is_file() and path.name != "project.jsonl"
    ] if logs_root.is_dir() else []
    for path in unexpected:
        add(
            "error",
            "logging",
            f"Only logs/project.jsonl is allowed; remove {path.relative_to(task)}.",
        )
    project_log = logs_root / "project.jsonl"
    if not project_log.is_file():
        add("warning", "logging", "The project-level log has not been created yet.")
        return
    sequences: list[int] = []
    for line_number, line in enumerate(project_log.read_text(encoding="utf-8", errors="replace").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            add("error", "logging", f"Malformed project-log JSON at line {line_number}.")
            continue
        if not isinstance(record, dict) or not record.get("utc") or not record.get("actor"):
            add("error", "logging", f"Incomplete project-log record at line {line_number}.")
        sequence = record.get("daemon_sequence") if isinstance(record, dict) else None
        if isinstance(sequence, int):
            sequences.append(sequence)
    if sequences and (sequences != sorted(sequences) or len(sequences) != len(set(sequences))):
        add("error", "logging", "Project-log daemon_sequence values are not strictly increasing.")


def _audit_routing(task: Path, pid: str, findings: list[dict[str, Any]], add: Any) -> None:
    routing_path = task / "reviews" / pid / "REVISION-ROUTING.yaml"
    if not routing_path.is_file():
        add("error", pid, "REVISION-ROUTING.yaml is missing.")
        return
    value = read_yaml(routing_path)
    routes = value.get("routes") if isinstance(value, dict) else None
    if not isinstance(routes, list):
        add("error", pid, "REVISION-ROUTING.yaml is malformed.")
        return
    finding_ids = {str(item.get("id")) for item in findings if isinstance(item, dict) and item.get("id")}
    routed_ids = {str(item.get("finding_id")) for item in routes if isinstance(item, dict)}
    if finding_ids != routed_ids:
        add("error", pid, "Revision routing does not cover the finding registry exactly.")



def _assignment_exists(
    root: Path,
    slug: str,
    role: str,
    presentation_id: str,
    *,
    unit_id: str | None = None,
    round_name: str | None = None,
    channel: str | None = None,
) -> bool:
    return assignment_path(
        root,
        slug,
        role,
        presentation_id,
        unit_id=unit_id,
        round_name=round_name,
        channel=channel,
    ).is_file()


def _audit_review_plan(task: Path, pid: str, add: Any) -> None:
    path = task / "reviews" / pid / "REVIEW-PLAN.yaml"
    if not path.is_file():
        add("error", pid, "REVIEW-PLAN.yaml is required after the deck is frozen.")
        return
    value = read_yaml(path)
    if not isinstance(value, dict):
        add("error", pid, "REVIEW-PLAN.yaml is malformed.")
        return
    if value.get("scope") != "full_deck":
        add("error", pid, "Review scope must be full_deck.")
    if value.get("all_five_reviewers_read_entire_deck") is not True:
        add("error", pid, "All five reviewers must each read the entire frozen deck.")
    if tuple(value.get("channels") or ()) != REVIEW_CHANNELS:
        add("error", pid, "REVIEW-PLAN.yaml does not name the five required channels in order.")
    if value.get("reviewer_rechecks_post_revision") is not False:
        add("error", pid, "The workflow must not create a post-revision reviewer round.")

def audit_task(root: Path, slug: str) -> dict[str, Any]:
    gate_ok, gate_message, state = gate_status(root, slug)
    task = task_path(root, slug)
    issues: list[dict[str, str]] = []

    def add(severity: str, area: str, message: str) -> None:
        issues.append({"severity": severity, "area": area, "message": message})

    if not gate_ok:
        add("error", "task", gate_message)
    policy = policy_audit(root, slug)
    for message in policy.get("errors", []):
        add("error", "policy", message)
    for message in policy.get("warnings", []):
        add("warning", "policy", message)
    incident_audit = audit_engine_incidents(root, slug, state)
    for message in incident_audit.get("errors", []):
        add("error", "engine-incidents", message)
    for message in incident_audit.get("warnings", []):
        add("warning", "engine-incidents", message)
    _audit_single_project_log(task, add)

    for path in task.rglob("*"):
        if not path.is_file():
            continue
        lower = path.name.lower()
        if "sha256" in lower or path.suffix.lower() == ".sha":
            add("error", "hash-policy", f"Non-TASK hash file is forbidden: {relative_display(path, root)}")
        if path.suffix.lower() in {".html", ".htm"}:
            add("error", "output-policy", f"Persistent HTML artifact is forbidden: {relative_display(path, root)}")
        if lower.endswith((".png", ".jpg", ".jpeg", ".webp")) and "screenshot" in lower:
            add("error", "inspection-policy", f"Screenshot review evidence is forbidden: {relative_display(path, root)}")
    for key in _hash_keys(state):
        if key.split(".")[-1] not in ALLOWED_HASH_KEYS:
            add("error", "hash-policy", f"Non-TASK hash field appears in state: {key}")

    stage_assignments = list(task.glob("workers/**/STAGE-ASSIGNMENT.md"))
    for path in stage_assignments:
        add("error", "authoring-stages", f"Stage-specific assignments are forbidden in v0.6.0: {relative_display(path, root)}")
    context_files = [
        *task.glob("workers/**/TASK-*.md"),
        *task.glob("review-cache/**/*.md"),
        *task.glob("review-cache/**/*.json"),
    ]
    for path in context_files:
        text = path.read_text(encoding="utf-8", errors="replace")
        if FORBIDDEN_REFERENCE_PATH_RE.search(text):
            add("error", "reference-access", f"Worker-visible context exposes a restricted reference path: {relative_display(path, root)}")
    restricted_root = task / "downloads" / "restricted-originals"
    if restricted_root.is_dir():
        for path in restricted_root.glob("*"):
            if path.is_file() and path.stat().st_mode & 0o444:
                add("error", "reference-access", f"Restricted original remains readable: {relative_display(path, root)}")

    if state.get("kind") == "course":
        for name in ("COURSE-TERMINOLOGY.yaml", "COURSE-SEMANTIC-OBJECTS.yaml", "CROSS-DECK-HANDOFFS.yaml"):
            if not (task / name).is_file():
                add("error", "course-consistency", f"Missing course-level registry: {name}")

    for presentation in state.get("presentations", []):
        pid = str(presentation["id"])
        status = str(presentation.get("status") or "authoring")

        # Assignment/workspace lifecycle is a hard policy boundary. Reviewers appear only after
        # freeze, the revision author only after aggregation, and release only in release_ready.
        author_exists = _assignment_exists(root, slug, "author-coordinator", pid)
        author_lane_materialized = bool(presentation.get("active") or status != "authoring")
        if author_lane_materialized:
            if not author_exists:
                add("error", pid, "Active presentation lacks its author-coordinator workspace.")
            elif not check_assignment(root, slug, "author-coordinator", pid).get("ready"):
                add("warning", pid, "Required author-coordinator assignment remains incomplete or unapproved.")
        elif author_exists:
            add("error", pid, "Future author-coordinator workspace was materialized before activation.")

        review_started = status in {
            "review_requested", "reviewing", "author_revision", "release_ready", "finalized"
        }
        revision_started = status in {"author_revision", "release_ready", "finalized"}
        release_started = status in {"release_ready", "finalized"}

        review_job = review_aggregation_root(root, slug, pid) / "job.yaml"
        if review_started:
            if not review_job.is_file():
                add("error", pid, "Mechanical review-aggregation job was not registered after deck freeze.")
            if revision_started and not (
                review_aggregation_root(root, slug, pid) / "receipt.json"
            ).is_file():
                add("error", pid, "Completed review lacks its mechanical aggregation receipt.")
            _audit_review_plan(task, pid, add)
        else:
            if review_job.exists():
                add("error", pid, "Review-aggregation job was created before the deck was frozen.")
            if (task / "reviews" / pid / "REVIEW-PLAN.yaml").exists():
                add("error", pid, "REVIEW-PLAN.yaml was created before the deck was frozen.")

        for channel in REVIEW_CHANNELS:
            exists = _assignment_exists(
                root,
                slug,
                "specialist-reviewer",
                pid,
                round_name="full",
                channel=channel,
            )
            if review_started:
                if not exists:
                    add("error", pid, f"Full-deck reviewer assignment is missing for channel {channel}.")
                elif not check_assignment(
                    root,
                    slug,
                    "specialist-reviewer",
                    pid,
                    round_name="full",
                    channel=channel,
                ).get("ready"):
                    add("warning", pid, f"Reviewer assignment remains incomplete for channel {channel}.")
            elif exists:
                add("error", pid, f"Reviewer {channel} was materialized before deck freeze.")

        revision_exists = _assignment_exists(root, slug, "deck-revision-author", pid)
        if revision_started:
            if not revision_exists:
                add("error", pid, "Deck revision author was not materialized after review aggregation.")
            elif not check_assignment(root, slug, "deck-revision-author", pid).get("ready"):
                add("warning", pid, "Required deck-revision-author assignment remains incomplete or unapproved.")
        elif revision_exists:
            add("error", pid, "Deck revision author was created before the five-channel review aggregated.")

        release_job = release_workspace(root, slug, pid) / "job.yaml"
        if release_started:
            if not release_job.is_file():
                add("error", pid, "Mechanical release job was not registered in release_ready.")
            if status == "finalized" and not (
                release_workspace(root, slug, pid) / "receipt.json"
            ).is_file():
                add("error", pid, "Finalized presentation lacks its mechanical release receipt.")
        elif release_job.exists():
            add("error", pid, "Release job was created before release_ready.")

        for unit in presentation.get("content_units", []):
            unit_id = str(unit.get("id"))
            unit_status = str(unit.get("status") or "uninitialized")
            unit_assignment_exists = _assignment_exists(
                root, slug, "lesson-author", pid, unit_id=unit_id
            )
            if unit_status == "uninitialized":
                if unit_assignment_exists:
                    add("error", f"{pid}/{unit_id}", "Lesson workspace was created before the unit entered the critical-path queue.")
            else:
                if not unit_assignment_exists:
                    add("error", f"{pid}/{unit_id}", "Materialized unit lacks its expanded lesson-author assignment.")
                elif not check_assignment(root, slug, "lesson-author", pid, unit_id=unit_id).get("ready"):
                    add("warning", f"{pid}/{unit_id}", "Materialized lesson-author assignment is incomplete.")
            if status == "finalized" and not all_stages_completed(root, slug, pid, unit_id):
                add("error", f"{pid}/{unit_id}", "The profile-selected one-thread authoring stage sequence is incomplete.")

        source_roots = [task / "workers" / "author-coordinator" / "drafts" / pid / "source"]
        revision_source = task / "workers" / "deck-revision-author" / "drafts" / pid / "source"
        if revision_source.is_dir():
            source_roots.append(revision_source)
        for source in source_roots:
            if source.is_dir():
                symlinks = source_tree_symlinks(source)
                if symlinks:
                    add("error", pid, "Author source contains symlinks: " + ", ".join(symlinks[:8]))
        for legacy in ("initial", "incremental", "final", "terminal", "closure"):
            if (task / "reviews" / pid / legacy).exists():
                add("error", pid, f"Legacy multi-round review path is invalid: {legacy}")

        maintenance = presentation.get("maintenance")
        if isinstance(maintenance, dict) and maintenance.get("status") not in {None, "published", "abandoned"}:
            revision = int(maintenance.get("revision") or 0)
            base = task / "maintenance" / pid / f"r{revision:04d}"
            if not (base / "TASK-MAINTENANCE.md").is_file():
                add("error", pid, "Active maintenance lacks its planner-written assignment.")

        if presentation.get("status") != "finalized":
            continue
        full = presentation.get("rounds", {}).get("full", {})
        if full.get("status") != "completed":
            add("error", pid, "The sole full-deck review is incomplete.")
        missing_channels = [channel for channel in REVIEW_CHANNELS if channel not in full.get("channels", {})]
        if missing_channels:
            add("error", pid, "Full review lacks channels: " + ", ".join(missing_channels))
        findings_path = task / "reviews" / pid / "findings.yaml"
        findings_value = read_yaml(findings_path) if findings_path.is_file() else None
        findings = findings_value.get("findings", []) if isinstance(findings_value, dict) else []
        if not isinstance(findings, list):
            add("error", pid, "Findings registry is missing or malformed.")
            findings = []
        obsolete_fields = {"review_status", "review_rationale", "resolved", "closed_utc", "last_reviewed_round"}
        for finding in findings:
            if not isinstance(finding, dict):
                add("error", pid, "Findings registry contains a non-mapping entry.")
                continue
            present = sorted(obsolete_fields & set(finding))
            if present:
                add("error", pid, f"Finding {finding.get('id')!r} contains obsolete resolution fields: " + ", ".join(present))
        _audit_routing(task, pid, [item for item in findings if isinstance(item, dict)], add)

        deliverable = task / "deliverables" / pid
        response_ok, response_error = _response_coverage(
            [item for item in findings if isinstance(item, dict)],
            deliverable / "AUTHOR-RESPONSES.yaml",
        )
        if not response_ok:
            add("error", pid, response_error)
        checklist_ok, checklist_error = _checklist_complete(deliverable / "AUTHOR-MODIFICATION-CHECKLIST.yaml")
        if not checklist_ok:
            add("error", pid, checklist_error)
        required = (
            f"{pid}.pdf",
            "release.json",
            "pdf-inspection.json",
            "source-lint.json",
            "asset-validation.json",
            "html-layout-inspection.json",
            "math-source-inventory.json",
            "math-renderer-probe.json",
            "slide-density-audit.json",
            "course-consistency.json",
            "source/presentation.md",
            "source/LESSON-TIME-PLANS.yaml",
            "source/GEOGEBRA-RESOURCES.yaml",
            "source/INTERACTION-RECORD.yaml",
            "source/INTERACTION-MANIFEST.yaml",
            "source/MCQ-AUDIT.yaml",
            "source/TERMINOLOGY.yaml",
            "source/SEMANTIC-OBJECTS.yaml",
            "source/PRESENTATION-CONTINUITY-MAP.yaml",
            "source/SLIDE-DENSITY-AUDIT.yaml",
            "source/AUTHOR-CONTEXT-PACKET.yaml",
        )
        for name in required:
            if not (deliverable / name).exists():
                add("error", pid, f"Missing deliverable: {name}")
        for report_name, label in (
            ("pdf-inspection.json", "PDF inspection"),
            ("source-lint.json", "source lint"),
            ("asset-validation.json", "asset validation"),
            ("html-layout-inspection.json", "temporary HTML layout inspection"),
            ("math-source-inventory.json", "math source inventory"),
            ("math-renderer-probe.json", "math renderer probe"),
            ("slide-density-audit.json", "slide-density audit"),
            ("course-consistency.json", "course consistency"),
        ):
            report_path = deliverable / report_name
            if report_path.is_file() and read_json(report_path).get("success") is not True:
                add("error", pid, f"Released {label} does not pass.")
        released_source = deliverable / "source"
        if (released_source / "presentation.md").is_file():
            geogebra = validate_presentation_geogebra_registry(
                released_source,
                (released_source / "presentation.md").read_text(encoding="utf-8"),
            )
            for message in geogebra.get("errors", []):
                add("error", pid, f"Released GeoGebra policy violation: {message}")

    try:
        registry = list_threads(root, slug)
        finalized_ids = {
            str(item.get("id"))
            for item in state.get("presentations", [])
            if item.get("status") == "finalized"
        }
        for handle in registry.get("handles", []):
            if not isinstance(handle, dict):
                continue
            role = str(handle.get("role") or "")
            try:
                expected = expected_runtime(
                    root,
                    slug,
                    role,
                    channel=(str(handle.get("channel")) if handle.get("channel") else None),
                    presentation_id=(
                        str(handle.get("presentation_id"))
                        if handle.get("presentation_id")
                        else None
                    ),
                )
            except Exception as exc:
                add("error", "thread-lifecycle", f"Cannot determine runtime policy for {role}: {exc}")
                continue
            if handle.get("actual_model") != expected["model"] or handle.get("actual_reasoning_effort") != expected["reasoning_effort"]:
                add(
                    "error",
                    "thread-lifecycle",
                    f"Thread {handle.get('handle_id')} does not match the confirmed task runtime profile.",
                )
            if handle.get("state") == "active" and str(handle.get("presentation_id")) in finalized_ids:
                add("error", "thread-lifecycle", f"Thread {handle.get('handle_id')} remains active for a finalized presentation.")
    except Exception as exc:
        add("error", "thread-lifecycle", f"Thread registry could not be audited: {exc}")

    try:
        store_status = mutable_state_status(root, slug)
        document_ids = {
            str(item.get("document_id"))
            for item in store_status.get("documents", [])
            if isinstance(item, dict)
        }
        missing_documents = sorted({"task-state", "thread-registry"} - document_ids)
        if missing_documents:
            add(
                "error",
                "mutable-state",
                "Transactional store lacks canonical document(s): " + ", ".join(missing_documents),
            )
        if store_status.get("single_writer") != "sqlite-begin-immediate":
            add("error", "mutable-state", "Task mutable state is not using the SQLite single-writer transaction boundary.")
        for item in store_status.get("documents", []):
            if isinstance(item, dict) and not item.get("projection_exists"):
                add(
                    "error",
                    "mutable-state",
                    f"Projection is missing for transactional document {item.get('document_id')!r}.",
                )
            elif isinstance(item, dict) and not item.get("projection_matches"):
                add(
                    "error",
                    "mutable-state",
                    f"Projection is stale for transactional document {item.get('document_id')!r}.",
                )
    except Exception as exc:
        add("error", "mutable-state", f"Transactional mutable-state store could not be audited: {exc}")

    return {
        "task_slug": slug,
        "phase": state.get("phase"),
        "gate_ok": gate_ok,
        "ok": not any(item["severity"] == "error" for item in issues),
        "issues": issues,
    }
