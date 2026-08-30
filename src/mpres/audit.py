from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from mpres.geogebra import validate_presentation_geogebra_registry
from mpres.policy import policy_audit
from mpres.production import check_assignment
from mpres.state import REVIEW_CHANNELS
from mpres.stages import all_stages_accepted
from mpres.threads import list_threads
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
        return False, "AUTHOR-RESPONSES.yaml must contain a response mapping for every finding."
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
    if (root / "package-lock.json").exists():
        add(
            "error",
            "marp-version-policy",
            "package-lock.json fixes the dependency graph and is forbidden by the unpinned Marp policy.",
        )

    for path in task.rglob("*"):
        if not path.is_file():
            continue
        lower = path.name.lower()
        if "sha256" in lower or path.suffix.lower() == ".sha":
            add(
                "error",
                "hash-policy",
                f"Non-TASK hash file is forbidden: {relative_display(path, root)}",
            )
        if path.suffix.lower() in {".html", ".htm"}:
            add(
                "error",
                "output-policy",
                f"Persistent HTML artifact is forbidden: {relative_display(path, root)}",
            )
        if lower.endswith((".png", ".jpg", ".jpeg", ".webp")) and "screenshot" in lower:
            add(
                "error",
                "inspection-policy",
                f"Screenshot review evidence is forbidden: {relative_display(path, root)}",
            )
    for key in _hash_keys(state):
        if key.split(".")[-1] not in ALLOWED_HASH_KEYS:
            add("error", "hash-policy", f"Non-TASK hash field appears in state: {key}")

    context_files = [
        *task.glob("workers/**/TASK-*.md"),
        *task.glob("workers/**/STAGE-ASSIGNMENT.md"),
        *task.glob("review-cache/**/*.md"),
        *task.glob("review-cache/**/*.json"),
    ]
    for path in context_files:
        text = path.read_text(encoding="utf-8", errors="replace")
        if FORBIDDEN_REFERENCE_PATH_RE.search(text):
            add(
                "error",
                "reference-access",
                f"Worker-visible context exposes a restricted reference path: {relative_display(path, root)}",
            )
    for path in (task / "downloads" / "restricted-originals").glob("*"):
        if path.is_file() and path.stat().st_mode & 0o444:
            add(
                "error",
                "reference-access",
                f"Restricted original remains readable: {relative_display(path, root)}",
            )

    for presentation in state.get("presentations", []):
        pid = presentation["id"]
        for role in ("author-coordinator", "review-coordinator", "release-coordinator"):
            assignment = check_assignment(root, slug, role, pid)
            if not assignment.get("ready"):
                add("warning", pid, f"{role} assignment remains incomplete or unapproved.")
        for unit in presentation.get("content_units", []):
            assignment = check_assignment(root, slug, "lesson-author", pid, unit_id=unit["id"])
            if not assignment.get("ready"):
                add("warning", f"{pid}/{unit['id']}", "Lesson-author assignment is incomplete.")
        source = task / "workers" / "author-coordinator" / "drafts" / pid / "source"
        if source.is_dir():
            symlinks = source_tree_symlinks(source)
            if symlinks:
                add("error", pid, "Author source contains symlinks: " + ", ".join(symlinks[:8]))
        for legacy in ("initial", "incremental", "final", "terminal", "closure"):
            legacy_path = task / "reviews" / pid / legacy
            if legacy_path.exists():
                add(
                    "error",
                    pid,
                    f"Legacy multi-round review path is not valid in the one-review workflow: {legacy}",
                )
        if presentation.get("status") != "finalized":
            continue
        full = presentation.get("rounds", {}).get("full", {})
        if full.get("status") != "completed":
            add("error", pid, "The sole full-deck review is incomplete.")
        missing_channels = [
            channel for channel in REVIEW_CHANNELS if channel not in full.get("channels", {})
        ]
        if missing_channels:
            add("error", pid, "Full review lacks channels: " + ", ".join(missing_channels))
        findings_path = task / "reviews" / pid / "findings.yaml"
        findings_value = read_yaml(findings_path) if findings_path.is_file() else None
        findings = (
            findings_value.get("findings", []) if isinstance(findings_value, dict) else []
        )
        if not isinstance(findings, list):
            add("error", pid, "Findings registry is missing or malformed.")
            findings = []
        obsolete_fields = {
            "review_status",
            "review_rationale",
            "resolved",
            "closed_utc",
            "last_reviewed_round",
        }
        for finding in findings:
            if not isinstance(finding, dict):
                continue
            present = sorted(obsolete_fields & set(finding))
            if present:
                add(
                    "error",
                    pid,
                    f"Finding {finding.get('id')!r} contains obsolete resolution fields: "
                    + ", ".join(present),
                )
        for unit in presentation.get("content_units", []):
            if not all_stages_accepted(root, slug, pid, str(unit.get("id"))):
                add("error", f"{pid}/{unit.get('id')}", "Authoring stages are not all accepted.")
        deliverable = task / "deliverables" / pid
        response_ok, response_error = _response_coverage(
            [item for item in findings if isinstance(item, dict)],
            deliverable / "AUTHOR-RESPONSES.yaml",
        )
        if not response_ok:
            add("error", pid, response_error)
        checklist_ok, checklist_error = _checklist_complete(
            deliverable / "AUTHOR-MODIFICATION-CHECKLIST.yaml"
        )
        if not checklist_ok:
            add("error", pid, checklist_error)
        for name in (
            f"{pid}.pdf",
            "release.json",
            "pdf-inspection.json",
            "source-lint.json",
            "asset-validation.json",
            "source/presentation.md",
            "source/GEOGEBRA-RESOURCES.yaml",
            "source/INTERACTION-MANIFEST.yaml",
            "source/MCQ-AUDIT.yaml",
        ):
            if not (deliverable / name).exists():
                add("error", pid, f"Missing deliverable: {name}")
        for report_name, label in (
            ("pdf-inspection.json", "PDF inspection"),
            ("source-lint.json", "source lint"),
            ("asset-validation.json", "asset validation"),
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
            if handle.get("state") == "active" and str(handle.get("presentation_id")) in finalized_ids:
                add(
                    "error",
                    "thread-lifecycle",
                    f"Thread {handle.get('handle_id')} remains active for a finalized presentation.",
                )
    except Exception as exc:
        add("error", "thread-lifecycle", f"Thread registry could not be audited: {exc}")

    return {
        "task_slug": slug,
        "phase": state.get("phase"),
        "gate_ok": gate_ok,
        "ok": not any(item["severity"] == "error" for item in issues),
        "issues": issues,
    }
