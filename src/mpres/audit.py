from __future__ import annotations

from pathlib import Path
from typing import Any

from mpres.geogebra import validate_presentation_geogebra_registry
from mpres.production import check_assignment
from mpres.state import REVIEW_CHANNELS, REVIEW_ROUNDS, load_state
from mpres.tasks import gate_status
from mpres.util import read_json, read_yaml, relative_display, source_tree_symlinks, task_path

ALLOWED_HASH_KEYS = {"presented_task_sha256", "confirmed_task_sha256"}


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


def audit_task(root: Path, slug: str) -> dict[str, Any]:
    gate_ok, gate_message, state = gate_status(root, slug)
    task = task_path(root, slug)
    issues: list[dict[str, str]] = []

    def add(severity: str, area: str, message: str) -> None:
        issues.append({"severity": severity, "area": area, "message": message})

    if not gate_ok:
        add("error", "task", gate_message)
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

    for presentation in state.get("presentations", []):
        pid = presentation["id"]
        for role in ("author-coordinator", "review-coordinator", "release-coordinator"):
            assignment = check_assignment(root, slug, role, pid)
            if not assignment.get("ready"):
                add("warning", pid, f"{role} assignment remains incomplete.")
        for unit in presentation.get("content_units", []):
            assignment = check_assignment(root, slug, "lesson-author", pid, unit_id=unit["id"])
            if not assignment.get("ready"):
                add("warning", f"{pid}/{unit['id']}", "lesson-author assignment remains incomplete.")
        author_source = task / "workers" / "author-coordinator" / "drafts" / pid / "source"
        if author_source.is_dir():
            symlinks = source_tree_symlinks(author_source)
            if symlinks:
                add("error", pid, "Author source contains symlinks: " + ", ".join(symlinks[:8]))
        if presentation.get("status") != "finalized":
            continue
        rounds = presentation.get("rounds", {})
        for round_name in REVIEW_ROUNDS:
            row = rounds.get(round_name, {})
            if row.get("status") != "completed":
                add("error", pid, f"Mandatory review round {round_name} is incomplete.")
            missing = [channel for channel in REVIEW_CHANNELS if channel not in row.get("channels", {})]
            if missing:
                add("error", pid, f"Round {round_name} lacks channels: {', '.join(missing)}")
        findings_path = task / "reviews" / pid / "findings.yaml"
        if not findings_path.is_file():
            add("error", pid, "Findings registry is missing.")
        else:
            value = read_yaml(findings_path)
            unresolved = [
                str(item.get("id"))
                for item in (value.get("findings", []) if isinstance(value, dict) else [])
                if isinstance(item, dict) and item.get("review_status") != "resolved"
            ]
            if unresolved:
                add("error", pid, "Finalized deck has unresolved findings: " + ", ".join(unresolved))
        deliverable = task / "deliverables" / pid
        for name in (f"{pid}.pdf", "release.json", "pdf-inspection.json", "source/presentation.md", "source/GEOGEBRA-RESOURCES.yaml"):
            if not (deliverable / name).exists():
                add("error", pid, f"Missing deliverable: {name}")
        if (deliverable / "pdf-inspection.json").is_file() and read_json(deliverable / "pdf-inspection.json").get("success") is not True:
            add("error", pid, "Released PDF inspection does not pass.")
        released_source = deliverable / "source"
        if (released_source / "presentation.md").is_file():
            geogebra = validate_presentation_geogebra_registry(
                released_source,
                (released_source / "presentation.md").read_text(encoding="utf-8"),
            )
            for message in geogebra.get("errors", []):
                add("error", pid, f"Released GeoGebra policy violation: {message}")
        if any(deliverable.rglob("*.html")):
            add("error", pid, "Deliverable contains a forbidden HTML artifact.")
    return {
        "task_slug": slug,
        "phase": state.get("phase"),
        "gate_ok": gate_ok,
        "ok": not any(item["severity"] == "error" for item in issues),
        "issues": issues,
    }
