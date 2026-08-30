from __future__ import annotations

import os
import shutil
import uuid
from pathlib import Path
from typing import Any

from mpres.assets import validate_assets
from mpres.logs import append_log
from mpres.marp_source import lint_deck
from mpres.pdf_inspection import inspect_pdf_file
from mpres.production import check_assignment
from mpres.state import get_presentation, load_state
from mpres.tasks import require_gate
from mpres.util import (
    MPresError,
    copy_source_tree,
    directory_inventory,
    ensure_within,
    local_marp_binary,
    make_tree_writable,
    read_yaml,
    relative_display,
    run_command,
    task_path,
    text_placeholders,
    utc_now,
    write_json_atomic,
)

RENDER_PIPELINE = "marp-markdown-to-pdf"


def source_and_build_paths(
    root: Path, slug: str, presentation_id: str, stage: str
) -> tuple[Path, Path]:
    task = task_path(root, slug)
    if stage == "author":
        base = task / "workers" / "author-coordinator" / "drafts" / presentation_id
    elif stage == "release":
        base = task / "workers" / "release-coordinator" / "approved" / presentation_id
    else:
        raise MPresError("Render stage must be author or release.")
    return base / "source", base / "build"


def _marp_command(root: Path, source: Path, output: Path, policy: dict[str, Any]) -> list[str]:
    binary = local_marp_binary(root)
    if binary is None:
        raise MPresError("Marp CLI is not installed. Run `npm install` or the bootstrap script.")
    command: list[str]
    if binary.suffix.lower() == ".js":
        node = shutil.which("node")
        if not node:
            raise MPresError("Node.js is required to run Marp CLI.")
        command = [node, str(binary)]
    else:
        command = [str(binary)]
    marp_policy = policy.get("marp", {}) if isinstance(policy, dict) else {}
    command.extend(
        [
            str(source / "presentation.md"),
            "--pdf",
            "--allow-local-files",
            "--html",
            "--theme-set",
            str(source / "theme.css"),
            "--output",
            str(output),
        ]
    )
    browser = str(marp_policy.get("browser", "auto") or "auto")
    if browser != "auto":
        command.extend(["--browser", browser])
    return command


def _required_source_files(source: Path) -> list[Path]:
    return [
        source / "presentation.md",
        source / "theme.css",
        source / "DECK-MANIFEST.yaml",
        source / "PEDAGOGY-MAP.md",
        source / "EXAMPLE-MAP.md",
        source / "TERMINOLOGY.md",
        source / "SEMANTIC-OBJECTS.yaml",
        source / "ASSET-DECISIONS.yaml",
        source / "GEOGEBRA-RESOURCES.yaml",
        source / "SELF-CHECK.md",
    ]


def _validate_source_files(source: Path) -> None:
    missing = [path for path in _required_source_files(source) if not path.is_file()]
    if missing:
        raise MPresError("Presentation source is missing: " + ", ".join(str(path) for path in missing))
    unfinished: list[str] = []
    for path in source.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in {".md", ".yaml", ".yml", ".json", ".css"}:
            continue
        placeholders = text_placeholders(path)
        if placeholders:
            unfinished.append(f"{path.relative_to(source)}: {', '.join(placeholders[:3])}")
    if unfinished:
        raise MPresError("Presentation source still contains placeholders: " + "; ".join(unfinished[:10]))


def render_presentation(
    root: Path,
    slug: str,
    presentation_id: str,
    *,
    stage: str,
    source_override: Path | None = None,
    timeout: int = 1800,
) -> dict[str, Any]:
    require_gate(root, slug)
    state = load_state(root, slug)
    presentation = get_presentation(state, presentation_id)
    if stage == "author":
        allowed = {"authoring", "initial_changes", "incremental_changes", "terminal_revision"}
        if presentation.get("status") not in allowed:
            raise MPresError(f"Author rendering is not allowed in status {presentation.get('status')!r}.")
        role = "author-coordinator"
    elif stage == "release":
        if presentation.get("status") != "release_approved":
            raise MPresError("Release rendering requires release_approved status.")
        role = "release-coordinator"
    else:
        raise MPresError("Render stage must be author or release.")
    assignment = check_assignment(root, slug, role, presentation_id)
    if not assignment.get("ready"):
        raise MPresError(f"{role} assignment is incomplete: {assignment.get('placeholders', [])[:8]}")

    expected_source, build = source_and_build_paths(root, slug, presentation_id, stage)
    source = source_override.resolve() if source_override else expected_source.resolve()
    ensure_within(source, expected_source, label="render source")
    if source != expected_source.resolve():
        raise MPresError(f"Render source must be the stage source root: {expected_source}")
    _validate_source_files(source)
    task = task_path(root, slug)
    policy = read_yaml(task / "EXECUTION-POLICY.yaml") or {}
    if not isinstance(policy, dict):
        raise MPresError("EXECUTION-POLICY.yaml must be a mapping.")

    source_lint = lint_deck(source, policy=policy)
    asset_report = validate_assets(
        root,
        slug,
        presentation_id,
        source_root=source,
        stage=stage,
    )
    if not source_lint.get("success") or not asset_report.get("success"):
        build.mkdir(parents=True, exist_ok=True)
        write_json_atomic(build / f"source-lint-{stage}.json", source_lint)
        write_json_atomic(build / f"asset-validation-{stage}.json", asset_report)
        raise MPresError("Source lint or asset validation failed; inspect the build reports.")

    build.mkdir(parents=True, exist_ok=True)
    logs = build / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    snapshot = build / "source-snapshot"
    copy_source_tree(source, snapshot, read_only=True)
    final_pdf = build / f"{presentation_id}.pdf"
    if final_pdf.exists():
        final_pdf.unlink()
    work = build / ".work"
    if work.exists():
        make_tree_writable(work)
        shutil.rmtree(work)
    copy_source_tree(snapshot, work)
    command = _marp_command(root, work, final_pdf, policy)
    environment = os.environ.copy()
    process = run_command(command, cwd=work, env=environment, timeout=timeout)
    stdout_log = logs / "marp-stdout.log"
    stderr_log = logs / "marp-stderr.log"
    stdout_log.write_text(process.stdout, encoding="utf-8", newline="\n")
    stderr_log.write_text(process.stderr, encoding="utf-8", newline="\n")

    unexpected_html = sorted(path for path in build.rglob("*.html") if path.is_file())
    if unexpected_html:
        for path in unexpected_html:
            path.unlink(missing_ok=True)
    pdf_report = inspect_pdf_file(
        final_pdf,
        expected_pages=int(source_lint.get("slide_count", 0)),
        warning_min_text_pt=float((policy.get("pdf_limits") or {}).get("warning_min_text_pt", 12) or 12),
        error_min_text_pt=float((policy.get("pdf_limits") or {}).get("error_min_text_pt", 8) or 8),
    ) if final_pdf.is_file() else {
        "success": False,
        "errors": ["Marp CLI did not produce the expected PDF."],
        "warnings": [],
    }
    write_json_atomic(build / f"source-lint-{stage}.json", source_lint)
    write_json_atomic(build / f"asset-validation-{stage}.json", asset_report)
    write_json_atomic(build / f"pdf-inspection-{stage}.json", pdf_report)
    success = process.returncode == 0 and pdf_report.get("success") is True and not unexpected_html
    report = {
        "schema_version": 1,
        "render_transaction_id": str(uuid.uuid4()),
        "pipeline": RENDER_PIPELINE,
        "task_slug": slug,
        "presentation_id": presentation_id,
        "stage": stage,
        "started_and_finished_utc": utc_now(),
        "source": relative_display(source, root),
        "source_snapshot": relative_display(snapshot, root),
        "source_inventory": directory_inventory(snapshot),
        "command": command,
        "returncode": process.returncode,
        "stdout_log": relative_display(stdout_log, root),
        "stderr_log": relative_display(stderr_log, root),
        "pdf": relative_display(final_pdf, root) if final_pdf.is_file() else None,
        "pdf_size_bytes": final_pdf.stat().st_size if final_pdf.is_file() else None,
        "source_lint": relative_display(build / f"source-lint-{stage}.json", root),
        "asset_validation": relative_display(build / f"asset-validation-{stage}.json", root),
        "pdf_inspection": relative_display(build / f"pdf-inspection-{stage}.json", root),
        "html_artifacts_generated": [],
        "errors": [
            *([] if process.returncode == 0 else ["Marp CLI returned a nonzero exit status."]),
            *pdf_report.get("errors", []),
            *(["An unexpected HTML artifact was generated and removed."] if unexpected_html else []),
        ],
        "warnings": [*source_lint.get("warnings", []), *asset_report.get("warnings", []), *pdf_report.get("warnings", [])],
        "success": success,
        "integrity_policy": "frozen snapshot and structured records; no hashes except TASK.md confirmation",
    }
    report_path = build / f"render-report-{stage}.json"
    write_json_atomic(report_path, report)
    append_log(
        root,
        slug,
        actor=role,
        kind="render" if success else "error",
        presentation_id=presentation_id,
        message=(
            "Rendered Marp Markdown directly to PDF and passed structural inspection."
            if success
            else f"Marp PDF render or inspection failed; see {relative_display(report_path, root)}."
        ),
        data={"report": relative_display(report_path, root), "success": success},
    )
    if not success:
        raise MPresError(f"Marp render did not pass. See {report_path}")
    return report
