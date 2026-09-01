from __future__ import annotations

import os
import shutil
import uuid
from pathlib import Path
from typing import Any

from mpres.assets import validate_assets
from mpres.assignments import assignment_contract_status
from mpres.course_consistency import validate_course_consistency
from mpres.density import validate_slide_density
from mpres.html_layout import inspect_marp_html_layout
from mpres.logs import append_log
from mpres.marp_source import lint_deck
from mpres.math_inspection import inspect_math_renderer, inspect_math_source
from mpres.pdf_inspection import inspect_pdf_file
from mpres.production import check_assignment
from mpres.state import get_presentation, load_state
from mpres.tasks import require_gate
from mpres.toolchain import require_pinned_marp
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
        state = load_state(root, slug)
        presentation = get_presentation(state, presentation_id)
        role = "deck-revision-author" if presentation.get("status") == "author_revision" else "author-coordinator"
        base = task / "workers" / role / "drafts" / presentation_id
    elif stage == "release":
        base = task / "workers" / "release-coordinator" / "release-ready" / presentation_id
    elif stage == "maintenance":
        state = load_state(root, slug)
        presentation = get_presentation(state, presentation_id)
        maintenance = presentation.get("maintenance")
        if not isinstance(maintenance, dict) or maintenance.get("status") not in {"open", "author_revision"}:
            raise MPresError("Maintenance rendering requires an active open or author_revision cycle.")
        revision = int(maintenance.get("revision") or 0)
        if revision < 1:
            raise MPresError("Active maintenance revision is malformed.")
        base = task / "maintenance" / presentation_id / f"r{revision:04d}"
    else:
        raise MPresError("Render stage must be author, release, or maintenance.")
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


def _required_source_files(
    source: Path, *, presentation_status: str, stage: str
) -> list[Path]:
    required = [
        source / "presentation.md",
        source / "theme.css",
        source / "DECK-MANIFEST.yaml",
        source / "PEDAGOGY-MAP.md",
        source / "EXAMPLE-MAP.md",
        source / "TERMINOLOGY.md",
        source / "TERMINOLOGY.yaml",
        source / "SEMANTIC-OBJECTS.yaml",
        source / "PRESENTATION-CONTINUITY-MAP.yaml",
        source / "SLIDE-DENSITY-AUDIT.yaml",
        source / "ASSET-DECISIONS.yaml",
        source / "GEOGEBRA-RESOURCES.yaml",
        source / "LESSON-TIME-PLANS.yaml",
        source / "INTERACTION-RECORD.yaml",
        source / "INTERACTION-MANIFEST.yaml",
        source / "MCQ-AUDIT.yaml",
        source / "AUTHOR-CONTEXT-PACKET.yaml",
        source / "SELF-CHECK.md",
    ]
    if presentation_status in {"author_revision", "release_ready"} and stage != "maintenance":
        required.extend(
            [
                source / "AUTHOR-MODIFICATION-CHECKLIST.yaml",
                source / "AUTHOR-RESPONSES.yaml",
                source / "AUTHOR-REVISION.md",
            ]
        )
    if stage == "maintenance":
        required.extend(
            [
                source / "CORRECTIVE-SCOPE.md",
                source / "MAINTENANCE-CHECKLIST.yaml",
                source / "MAINTENANCE-RETROSPECTIVE.md",
            ]
        )
    return required


def _validate_source_files(
    source: Path, *, presentation_status: str, stage: str
) -> None:
    missing = [
        path
        for path in _required_source_files(
            source, presentation_status=presentation_status, stage=stage
        )
        if not path.is_file()
    ]
    if missing:
        raise MPresError("Presentation source is missing: " + ", ".join(str(path) for path in missing))
    deferred_post_review = {
        "AUTHOR-MODIFICATION-CHECKLIST.yaml",
        "AUTHOR-RESPONSES.yaml",
        "AUTHOR-REVISION.md",
    }
    deferred_maintenance = {
        "MAINTENANCE-CHECKLIST.yaml",
        "MAINTENANCE-RETROSPECTIVE.md",
        "MAINTENANCE-AUTHOR-RESPONSES.yaml",
    }
    unfinished: list[str] = []
    for path in source.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in {".md", ".yaml", ".yml", ".json", ".css"}:
            continue
        if presentation_status == "authoring" and path.name in deferred_post_review:
            continue
        if stage == "maintenance" and path.name in deferred_maintenance:
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
    timeout: int = 0,
) -> dict[str, Any]:
    require_gate(root, slug)
    require_pinned_marp(root)
    state = load_state(root, slug)
    presentation = get_presentation(state, presentation_id)
    if stage == "author":
        allowed = {"authoring", "author_revision"}
        if presentation.get("status") not in allowed:
            raise MPresError(f"Author rendering is not allowed in status {presentation.get('status')!r}.")
        role = "deck-revision-author" if presentation.get("status") == "author_revision" else "author-coordinator"
    elif stage == "release":
        if presentation.get("status") != "release_ready":
            raise MPresError("Release rendering requires release_ready status.")
        role = "release-coordinator"
    elif stage == "maintenance":
        maintenance = presentation.get("maintenance")
        if not isinstance(maintenance, dict) or maintenance.get("status") not in {"open", "author_revision"}:
            raise MPresError("Maintenance rendering requires an active corrective cycle.")
        role = "author-coordinator"
    else:
        raise MPresError("Render stage must be author, release, or maintenance.")
    if stage == "maintenance":
        expected_source, build = source_and_build_paths(root, slug, presentation_id, stage)
        assignment_path = expected_source.parent / "TASK-MAINTENANCE.md"
        assignment = assignment_contract_status(assignment_path)
        if not assignment.get("approved") or text_placeholders(assignment_path):
            raise MPresError("The planner-written maintenance assignment is incomplete or unapproved.")
    else:
        assignment = check_assignment(root, slug, role, presentation_id)
        if not assignment.get("ready"):
            raise MPresError(f"{role} assignment is incomplete: {assignment.get('placeholders', [])[:8]}")
        expected_source, build = source_and_build_paths(root, slug, presentation_id, stage)

    source = source_override.resolve() if source_override else expected_source.resolve()
    ensure_within(source, expected_source, label="render source")
    if source != expected_source.resolve():
        raise MPresError(f"Render source must be the stage source root: {expected_source}")
    _validate_source_files(
        source,
        presentation_status=("maintenance" if stage == "maintenance" else str(presentation.get("status"))),
        stage=stage,
    )
    task = task_path(root, slug)
    policy = read_yaml(task / "EXECUTION-POLICY.yaml") or {}
    if not isinstance(policy, dict):
        raise MPresError("EXECUTION-POLICY.yaml must be a mapping.")

    source_lint = lint_deck(source, policy=policy)
    slide_count_for_timeout = max(1, int(source_lint.get("slide_count", 1) or 1))
    effective_timeout = timeout if timeout and timeout > 0 else max(120, min(1800, 60 + slide_count_for_timeout * 4))
    asset_report = validate_assets(
        root,
        slug,
        presentation_id,
        source_root=source,
        stage=stage,
    )
    math_source_report = inspect_math_source(source)
    density_report = validate_slide_density(source)
    course_report = validate_course_consistency(
        root, slug, presentation_id, source=source
    )
    build.mkdir(parents=True, exist_ok=True)
    write_json_atomic(build / f"source-lint-{stage}.json", source_lint)
    write_json_atomic(build / f"asset-validation-{stage}.json", asset_report)
    write_json_atomic(build / f"math-source-inventory-{stage}.json", math_source_report)
    write_json_atomic(build / f"slide-density-audit-{stage}.json", density_report)
    write_json_atomic(build / f"course-consistency-{stage}.json", course_report)
    if not all(
        report.get("success")
        for report in (source_lint, asset_report, math_source_report, density_report, course_report)
    ):
        raise MPresError(
            "Source, asset, mathematics, density, or course-consistency validation failed; "
            "inspect the build reports."
        )

    logs = build / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    snapshot = build / "source-snapshot"
    copy_source_tree(source, snapshot, read_only=True)
    try:
        html_layout_report = inspect_marp_html_layout(
            root,
            snapshot,
            policy=policy,
            timeout=effective_timeout,
        )
    except MPresError as exc:
        html_layout_report = {
            "schema_version": 2,
            "errors": [str(exc)],
            "warnings": [],
            "success": False,
            "temporary_html_retained": False,
            "inspection_policy": "author mechanical self-check; no screenshots or model vision",
        }
    html_layout_path = build / f"html-layout-inspection-{stage}.json"
    write_json_atomic(html_layout_path, html_layout_report)
    math_renderer_report = inspect_math_renderer(math_source_report, html_layout_report)
    write_json_atomic(build / f"math-renderer-probe-{stage}.json", math_renderer_report)
    if not html_layout_report.get("success") or not math_renderer_report.get("success"):
        report = {
            "schema_version": 2,
            "render_transaction_id": str(uuid.uuid4()),
            "pipeline": RENDER_PIPELINE,
            "task_slug": slug,
            "presentation_id": presentation_id,
            "stage": stage,
            "started_and_finished_utc": utc_now(),
            "source": relative_display(source, root),
            "source_snapshot": relative_display(snapshot, root),
            "source_inventory": directory_inventory(snapshot),
            "source_lint": relative_display(build / f"source-lint-{stage}.json", root),
            "asset_validation": relative_display(build / f"asset-validation-{stage}.json", root),
            "math_source_inventory": relative_display(build / f"math-source-inventory-{stage}.json", root),
            "math_renderer_probe": relative_display(build / f"math-renderer-probe-{stage}.json", root),
            "slide_density_audit": relative_display(build / f"slide-density-audit-{stage}.json", root),
            "course_consistency": relative_display(build / f"course-consistency-{stage}.json", root),
            "html_layout_inspection": relative_display(html_layout_path, root),
            "pdf": None,
            "html_artifacts_generated": [],
            "errors": [
                *html_layout_report.get("errors", []),
                *math_renderer_report.get("errors", []),
            ],
            "warnings": [
                *source_lint.get("warnings", []),
                *asset_report.get("warnings", []),
                *html_layout_report.get("warnings", []),
                *math_renderer_report.get("warnings", []),
            ],
            "success": False,
            "integrity_policy": "frozen snapshot and structured records; no hashes except TASK.md confirmation",
        }
        report_path = build / f"render-report-{stage}.json"
        write_json_atomic(report_path, report)
        append_log(
            root,
            slug,
            actor=role,
            kind="error",
            presentation_id=presentation_id,
            message=(
                "Author mechanical HTML layout self-check failed; the deck cannot proceed "
                f"to PDF or review. See {relative_display(html_layout_path, root)}."
            ),
            data={"report": relative_display(report_path, root), "success": False},
        )
        raise MPresError(f"Temporary Marp HTML layout inspection failed. See {html_layout_path}")
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
    process = run_command(command, cwd=work, env=environment, timeout=effective_timeout)
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
    write_json_atomic(build / f"pdf-inspection-{stage}.json", pdf_report)
    success = (
        process.returncode == 0
        and html_layout_report.get("success") is True
        and math_renderer_report.get("success") is True
        and pdf_report.get("success") is True
        and not unexpected_html
    )
    report = {
        "schema_version": 2,
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
        "effective_timeout_seconds": effective_timeout,
        "returncode": process.returncode,
        "stdout_log": relative_display(stdout_log, root),
        "stderr_log": relative_display(stderr_log, root),
        "pdf": relative_display(final_pdf, root) if final_pdf.is_file() else None,
        "pdf_size_bytes": final_pdf.stat().st_size if final_pdf.is_file() else None,
        "source_lint": relative_display(build / f"source-lint-{stage}.json", root),
        "asset_validation": relative_display(build / f"asset-validation-{stage}.json", root),
        "math_source_inventory": relative_display(build / f"math-source-inventory-{stage}.json", root),
        "math_renderer_probe": relative_display(build / f"math-renderer-probe-{stage}.json", root),
        "slide_density_audit": relative_display(build / f"slide-density-audit-{stage}.json", root),
        "course_consistency": relative_display(build / f"course-consistency-{stage}.json", root),
        "html_layout_inspection": relative_display(html_layout_path, root),
        "pdf_inspection": relative_display(build / f"pdf-inspection-{stage}.json", root),
        "html_artifacts_generated": [],
        "errors": [
            *([] if process.returncode == 0 else ["Marp CLI returned a nonzero exit status."]),
            *pdf_report.get("errors", []),
            *(["An unexpected HTML artifact was generated and removed."] if unexpected_html else []),
        ],
        "warnings": [
            *source_lint.get("warnings", []),
            *asset_report.get("warnings", []),
            *html_layout_report.get("warnings", []),
            *math_renderer_report.get("warnings", []),
            *density_report.get("warnings", []),
            *course_report.get("warnings", []),
            *pdf_report.get("warnings", []),
        ],
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
            "Passed the author mechanical HTML overflow self-check, rendered Marp Markdown "
            "to PDF, and passed PDF structural inspection."
            if success
            else f"Marp PDF render or inspection failed; see {relative_display(report_path, root)}."
        ),
        data={"report": relative_display(report_path, root), "success": success},
    )
    if not success:
        raise MPresError(f"Marp render did not pass. See {report_path}")
    return report
