from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path
from typing import Any

from mpres.assignments import (
    assignment_contract_status,
    ensure_assignment_taskbook,
    scaffold_assignment_contract,
)
from mpres.logs import append_log
from mpres.rendering import RENDER_PIPELINE, source_and_build_paths
from mpres.scaffolds import ensure_copy, ensure_json, ensure_text, ensure_tree, ensure_yaml
from mpres.revision_routing import build_revision_routing
from mpres.review import REQUIRED_FINDING_FIELDS, _normalize_findings_file
from mpres.state import REVIEW_CHANNELS, get_presentation, load_state, save_state
from mpres.tasks import require_gate
from mpres.transactions import transactional_task_mutation
from mpres.util import (
    MPresError,
    copy_source_tree,
    make_tree_read_only,
    make_tree_writable,
    parse_utc,
    read_json,
    read_yaml,
    relative_display,
    task_path,
    text_placeholders,
    utc_now,
    write_json_atomic,
    write_yaml_atomic,
)

MAINTENANCE_MODES = {"targeted_patch", "full_corrective_review"}


def maintenance_root(root: Path, slug: str, presentation_id: str, revision: int) -> Path:
    return task_path(root, slug) / "maintenance" / presentation_id / f"r{revision:04d}"


def active_maintenance(root: Path, slug: str, presentation_id: str) -> tuple[dict[str, Any], Path]:
    state = load_state(root, slug)
    presentation = get_presentation(state, presentation_id)
    maintenance = presentation.get("maintenance")
    if not isinstance(maintenance, dict) or maintenance.get("status") in {None, "published", "abandoned"}:
        raise MPresError(f"Presentation {presentation_id} has no active maintenance cycle.")
    revision = int(maintenance.get("revision") or 0)
    if revision < 1:
        raise MPresError("Active maintenance revision is malformed.")
    return maintenance, maintenance_root(root, slug, presentation_id, revision)


def _current_release_source(task: Path, presentation_id: str) -> Path:
    marker = task / "deliverables" / presentation_id / "CURRENT-REVISION.json"
    if marker.is_file():
        value = read_json(marker)
        source = task.parent.parent / str(value.get("source") or "")
        if source.is_dir():
            return source
    source = task / "deliverables" / presentation_id / "source"
    if not source.is_dir():
        raise MPresError("Published source is missing; corrective maintenance cannot start.")
    return source


@transactional_task_mutation
def open_maintenance(
    root: Path,
    slug: str,
    presentation_id: str,
    *,
    mode: str,
    reason: str,
    allowed_changes: list[str],
) -> dict[str, Any]:
    """Open or idempotently repair one corrective-maintenance workspace."""

    require_gate(root, slug)
    if mode not in MAINTENANCE_MODES:
        raise MPresError(f"Maintenance mode must be one of {sorted(MAINTENANCE_MODES)}")
    if len(reason.strip()) < 20:
        raise MPresError("Corrective maintenance requires a substantive reason.")
    if not allowed_changes or any(not item.strip() for item in allowed_changes):
        raise MPresError("Corrective maintenance needs explicit allowed-change boundaries.")

    normalized_changes = [item.strip() for item in allowed_changes]
    state = load_state(root, slug)
    presentation = get_presentation(state, presentation_id)
    if presentation.get("status") != "finalized":
        raise MPresError("Only a finalized presentation may enter corrective maintenance.")

    task = task_path(root, slug)
    history = presentation.setdefault("maintenance_history", [])
    current = presentation.get("maintenance")
    active_cycle = bool(
        isinstance(current, dict)
        and current.get("status") not in {None, "published", "abandoned"}
    )
    if active_cycle:
        assert isinstance(current, dict)
        revision = int(current.get("revision") or 0)
        if revision < 1:
            raise MPresError("Active maintenance revision is malformed.")
        expected_active = {
            "presentation_id": presentation_id,
            "revision": revision,
            "mode": mode,
            "reason": reason.strip(),
            "allowed_changes": normalized_changes,
        }
        mismatches = [
            key for key, value in expected_active.items() if current.get(key) != value
        ]
        if mismatches:
            raise MPresError(
                "This presentation already has an active maintenance cycle with different boundaries: "
                + ", ".join(mismatches)
            )
    else:
        base_revision = 1
        current_marker = task / "deliverables" / presentation_id / "CURRENT-REVISION.json"
        base_release = task / "deliverables" / presentation_id / "release.json"
        if current_marker.is_file():
            base_revision = max(
                base_revision, int(read_json(current_marker).get("revision") or 1)
            )
        elif base_release.is_file():
            base_revision = max(
                base_revision, int(read_json(base_release).get("revision") or 1)
            )
        revision = max(
            [
                base_revision,
                *[
                    int(item.get("revision") or 0)
                    for item in history
                    if isinstance(item, dict)
                ],
            ]
        ) + 1

    base = maintenance_root(root, slug, presentation_id, revision)
    source = base / "source"
    build = base / "build"
    source.parent.mkdir(parents=True, exist_ok=True)
    ensure_tree(_current_release_source(task, presentation_id), source)
    # Release evidence remains read-only; only this distinct author work copy is writable.
    from mpres.util import make_tree_writable, require_no_symlinks
    require_no_symlinks(source)
    make_tree_writable(source)
    build.mkdir(parents=True, exist_ok=True)

    cycle_path = base / "CORRECTIVE-CYCLE.yaml"
    existing_cycle = read_yaml(cycle_path) if cycle_path.is_file() else None
    if existing_cycle is not None:
        if not isinstance(existing_cycle, dict):
            raise MPresError(f"Existing corrective cycle is malformed: {cycle_path}")
        expected = {
            "presentation_id": presentation_id,
            "revision": revision,
            "mode": mode,
            "reason": reason.strip(),
            "allowed_changes": normalized_changes,
        }
        mismatches = [key for key, value in expected.items() if existing_cycle.get(key) != value]
        if mismatches:
            raise MPresError(
                "Existing maintenance scaffold has different boundaries and will not be overwritten: "
                + ", ".join(mismatches)
            )
        opened_utc = str(existing_cycle.get("opened_utc") or utc_now())
    elif active_cycle and isinstance(current, dict):
        opened_utc = str(current.get("opened_utc") or utc_now())
    else:
        opened_utc = utc_now()

    scope_template = (
        root / "templates" / "structured" / "CORRECTIVE-SCOPE.template.md"
    ).read_text(encoding="utf-8")
    scope_template = (
        scope_template.replace("[[PRESENTATION_ID]]", presentation_id)
        .replace("[[REVISION_NUMBER]]", str(revision))
        .replace("[[REASON]]", reason.strip())
        .replace("[[MODE]]", mode)
        .replace("[[ALLOWED_CHANGES]]", "\n".join(f"- {item}" for item in normalized_changes))
    )
    ensure_text(source / "CORRECTIVE-SCOPE.md", scope_template)

    retrospective = (
        root / "templates" / "structured" / "MAINTENANCE-RETROSPECTIVE.template.md"
    ).read_text(encoding="utf-8")
    retrospective = retrospective.replace("[[PRESENTATION_ID]]", presentation_id).replace(
        "[[REVISION_NUMBER]]", str(revision)
    )
    ensure_text(source / "MAINTENANCE-RETROSPECTIVE.md", retrospective)

    checklist = (
        root / "templates" / "structured" / "MAINTENANCE-CHECKLIST.template.yaml"
    ).read_text(encoding="utf-8")
    checklist = (
        checklist.replace("[[PRESENTATION_ID]]", presentation_id)
        .replace("[[REVISION_NUMBER]]", str(revision))
        .replace("[[MODE]]", mode)
    )
    ensure_text(source / "MAINTENANCE-CHECKLIST.yaml", checklist)

    assignment_template = (
        root / "templates" / "assignments" / "TASK-maintenance.template.md"
    ).read_text(encoding="utf-8")
    assignment = (
        assignment_template.replace("[[PRESENTATION_ID]]", presentation_id)
        .replace("[[REVISION_NUMBER]]", str(revision))
        .replace("[[MODE]]", mode)
        .replace("[[REASON]]", reason.strip())
        .replace(
            "[[SOURCE_RELEASE]]",
            relative_display(_current_release_source(task, presentation_id), root),
        )
    )
    assignment_path = base / "TASK-MAINTENANCE.md"
    ensure_assignment_taskbook(assignment_path, assignment)
    scaffold_assignment_contract(
        root,
        assignment_path,
        assignment_id=f"{presentation_id}:maintenance:r{revision:04d}",
        role="corrective-maintenance",
        presentation_id=presentation_id,
        requested_by="planner",
        need=f"Perform {mode} corrective maintenance without overwriting the historical release.",
    )

    desired_cycle = {
        "schema_version": 2,
        "presentation_id": presentation_id,
        "revision": revision,
        "mode": mode,
        "reason": reason.strip(),
        "allowed_changes": normalized_changes,
        "opened_utc": opened_utc,
        "status": "open",
        "source_release": relative_display(_current_release_source(task, presentation_id), root),
        "source": relative_display(source, root),
        "assignment": relative_display(assignment_path, root),
    }
    ensure_yaml(cycle_path, desired_cycle)
    # Canonical task state may have advanced beyond the immutable opening
    # record (for example, to review_requested). Never let a recovery pass
    # reset that lifecycle status from the older CORRECTIVE-CYCLE.yaml file.
    canonical_cycle = (current if active_cycle else None) or existing_cycle or desired_cycle
    assert isinstance(canonical_cycle, dict)
    presentation["maintenance"] = canonical_cycle
    save_state(root, slug, state)

    first_open = not active_cycle and existing_cycle is None
    if first_open:
        append_log(
            root,
            slug,
            actor="planner",
            kind="maintenance",
            presentation_id=presentation_id,
            message=f"Opened corrective maintenance revision r{revision:04d} in {mode} mode.",
            data={"revision": revision, "mode": mode, "path": relative_display(base, root)},
        )
    return {**canonical_cycle, "already_open": not first_open}


def _require_maintenance_assignment(root: Path, base: Path) -> None:
    assignment = base / "TASK-MAINTENANCE.md"
    status = assignment_contract_status(assignment)
    if not status.get("approved") or text_placeholders(assignment):
        raise MPresError("The planner-written maintenance assignment is incomplete or unapproved.")


def _scaffold_review_assignments(root: Path, slug: str, presentation_id: str, base: Path) -> dict[str, Any]:
    task = task_path(root, slug)
    template = (
        root / "templates" / "assignments" / "TASK-specialist-reviewer.template.md"
    ).read_text(encoding="utf-8")
    report_template = (
        root / "templates" / "review" / "review-report.template.md"
    ).read_text(encoding="utf-8")
    request_root = base / "review" / "full" / "request"
    created: list[str] = []
    preserved: list[str] = []
    for channel in REVIEW_CHANNELS:
        channel_root = base / "review" / "full" / channel
        channel_root.mkdir(parents=True, exist_ok=True)
        guidance = (
            root
            / ".agents"
            / "skills"
            / "presentation-specialist-review"
            / "references"
            / f"{channel.replace('_', '-')}.md"
        )
        values = {
            "[[PRESENTATION_ID]]": presentation_id,
            "[[CHANNEL]]": channel,
            "[[REQUEST_PATH]]": relative_display(request_root, root),
            "[[TASK_MD_PATH]]": relative_display(task / "TASK.md", root),
            "[[REVIEW_PROTOCOL_PATH]]": relative_display(task / "REVIEW-PROTOCOL.md", root),
            "[[CHANNEL_GUIDANCE_PATH]]": relative_display(guidance, root),
            "[[REPORT_PATH]]": relative_display(channel_root / "report.md", root),
            "[[FINDINGS_PATH]]": relative_display(channel_root / "findings.yaml", root),
        }
        assignment = template
        for old, new in values.items():
            assignment = assignment.replace(old, new)
        assignment_path = channel_root / "TASK-SPECIALIST-REVIEWER.md"
        result = ensure_assignment_taskbook(assignment_path, assignment)
        created.extend(result["created"])
        preserved.extend(result["preserved"])
        contract = scaffold_assignment_contract(
            root,
            assignment_path,
            assignment_id=f"{presentation_id}:maintenance:{base.name}:{channel}",
            role="specialist-reviewer",
            presentation_id=presentation_id,
            round_name="full",
            channel=channel,
            requested_by="planner",
            need=f"Review corrective maintenance {base.name} in the isolated {channel} channel.",
        )
        created.extend(contract["created"])
        preserved.extend(contract["preserved"])
        report = report_template.replace("[[CHANNEL]]", channel).replace(
            "[[PRESENTATION_ID]]", presentation_id
        ).replace("[[ROUND]]", "full")
        result2 = ensure_text(channel_root / "report.md", report)
        created.extend(result2.created)
        preserved.extend(result2.preserved)
        result3 = ensure_yaml(
            channel_root / "findings.yaml",
            {
                "schema_version": 1,
                "presentation_id": presentation_id,
                "round": "full",
                "channel": channel,
                "findings": [],
            },
        )
        created.extend(result3.created)
        preserved.extend(result3.preserved)
    return {"created": created, "preserved": preserved, "changed": bool(created)}



@transactional_task_mutation
def request_maintenance_review(root: Path, slug: str, presentation_id: str) -> dict[str, Any]:
    """Create or repair the sole full-review request for a maintenance cycle."""

    require_gate(root, slug)
    maintenance, base = active_maintenance(root, slug, presentation_id)
    if maintenance.get("mode") != "full_corrective_review":
        raise MPresError("Only a full-corrective-review maintenance cycle may request specialist review.")
    if maintenance.get("status") not in {"open", "review_requested", "reviewing"}:
        raise MPresError(
            "A maintenance review may be requested or resumed only before aggregation."
        )
    _require_maintenance_assignment(root, base)
    render_report = read_json(base / "build" / "render-report-maintenance.json")
    if render_report.get("success") is not True or render_report.get("pipeline") != RENDER_PIPELINE:
        raise MPresError("A successful maintenance render is required before corrective review.")

    request_root = base / "review" / "full" / "request"
    request_path = request_root / "request.json"
    existing_request = read_json(request_path) if request_path.is_file() else None
    if existing_request is not None:
        expected = {
            "presentation_id": presentation_id,
            "revision": maintenance["revision"],
            "mode": maintenance["mode"],
        }
        mismatches = [key for key, value in expected.items() if existing_request.get(key) != value]
        if mismatches:
            raise MPresError(
                "Existing maintenance review request has a different identity and will not be overwritten: "
                + ", ".join(mismatches)
            )
        created_utc = str(existing_request.get("created_utc") or utc_now())
    else:
        created_utc = utc_now()

    request_root.mkdir(parents=True, exist_ok=True)
    source = request_root / "source"
    rendered = request_root / "rendered"
    make_tree_writable(request_root)
    ensure_tree(base / "build" / "source-snapshot", source)
    rendered.mkdir(parents=True, exist_ok=True)
    pdf = base / "build" / f"{presentation_id}.pdf"
    ensure_copy(pdf, rendered / pdf.name)
    desired_request = {
        "schema_version": 1,
        "presentation_id": presentation_id,
        "revision": maintenance["revision"],
        "mode": maintenance["mode"],
        "created_utc": created_utc,
        "source_path": relative_display(source, root),
        "pdf_path": relative_display(rendered / pdf.name, root),
        "status": "pending",
        "post_revision_review": "none",
    }
    ensure_json(request_path, desired_request)
    make_tree_read_only(request_root)
    scaffold = _scaffold_review_assignments(root, slug, presentation_id, base)

    first_request = maintenance.get("status") == "open" and existing_request is None
    if maintenance.get("status") == "open":
        maintenance["status"] = "review_requested"
        maintenance["review"] = {
            "channels": {},
            "request": relative_display(request_path, root),
        }
        state = load_state(root, slug)
        get_presentation(state, presentation_id)["maintenance"] = maintenance
        save_state(root, slug, state)
    elif not isinstance(maintenance.get("review"), dict):
        raise MPresError("Active maintenance review state is missing its canonical review record.")

    if first_request:
        append_log(
            root,
            slug,
            actor="author-coordinator",
            kind="maintenance",
            presentation_id=presentation_id,
            message=(
                f"Requested the one full five-channel review for maintenance revision "
                f"r{maintenance['revision']:04d}."
            ),
        )
    canonical = existing_request or desired_request
    return {
        **canonical,
        "already_requested": existing_request is not None,
        "scaffold_created": scaffold["created"],
        "scaffold_preserved": scaffold["preserved"],
    }


@transactional_task_mutation
def submit_maintenance_channel(
    root: Path,
    slug: str,
    presentation_id: str,
    *,
    channel: str,
    report_path: Path,
    findings_path: Path,
) -> dict[str, Any]:
    require_gate(root, slug)
    if channel not in REVIEW_CHANNELS:
        raise MPresError(f"Unknown review channel: {channel}")
    maintenance, base = active_maintenance(root, slug, presentation_id)
    if maintenance.get("status") not in {"review_requested", "reviewing"}:
        raise MPresError("Maintenance is not accepting specialist reviews.")
    assignment = base / "review" / "full" / channel / "TASK-SPECIALIST-REVIEWER.md"
    if not assignment_contract_status(assignment).get("approved"):
        raise MPresError("The planner-written maintenance reviewer assignment is not approved.")
    report_path = report_path.resolve()
    findings_path = findings_path.resolve()
    if not report_path.is_file() or text_placeholders(report_path):
        raise MPresError("Maintenance specialist report is missing or incomplete.")
    if len(report_path.read_text(encoding="utf-8").strip()) < 250:
        raise MPresError("Maintenance specialist report is too short.")
    submitted = _normalize_findings_file(findings_path)
    for item in submitted:
        if item.get("channel") != channel or item.get("round_opened") != "full":
            raise MPresError(f"Finding {item.get('id')} has the wrong channel or round.")
    review = maintenance.setdefault("review", {"channels": {}})
    prior = (review.get("channels") or {}).get(channel)
    previous_attempt = int(prior.get("attempt") or 0) if isinstance(prior, dict) else 0
    if previous_attempt:
        previous_path = root / str(prior["submission"]) / "findings.yaml"
        previous = _normalize_findings_file(previous_path)
        previous_by_id = {str(item["id"]): item for item in previous}
        current_by_id = {str(item["id"]): item for item in submitted}
        if set(previous_by_id) != set(current_by_id):
            raise MPresError("A maintenance review resubmission may not add or remove finding IDs.")
        stable = (
            "id",
            "channel",
            "round_opened",
            "issue",
            "learner_impact",
            "acceptance_criteria",
            "verification_method",
        )
        for finding_id in previous_by_id:
            if any(previous_by_id[finding_id].get(key) != current_by_id[finding_id].get(key) for key in stable):
                raise MPresError(
                    f"Resubmission of {finding_id} changes substantive fields; only location, evidence_path and reviewer_note may change."
                )
    attempt = previous_attempt + 1
    channel_root = base / "review" / "full" / channel
    submission = channel_root / "submissions" / f"attempt-{attempt:04d}"
    submission.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="mpres-maint-review-", dir=submission.parent) as raw:
        staged = Path(raw)
        shutil.copy2(report_path, staged / "report.md")
        write_yaml_atomic(
            staged / "findings.yaml",
            {
                "schema_version": 1,
                "presentation_id": presentation_id,
                "round": "full",
                "channel": channel,
                "findings": submitted,
            },
        )
        write_json_atomic(
            staged / "receipt.json",
            {
                "schema_version": 1,
                "channel": channel,
                "attempt": attempt,
                "supersedes_attempt": previous_attempt or None,
                "submitted_utc": utc_now(),
                "finding_ids": [str(item["id"]) for item in submitted],
            },
        )
        os.replace(staged, submission)
    shutil.copy2(submission / "report.md", channel_root / "report.md")
    shutil.copy2(submission / "findings.yaml", channel_root / "findings.yaml")
    review.setdefault("channels", {})[channel] = {
        "attempt": attempt,
        "submission": relative_display(submission, root),
        "finding_count": len(submitted),
        "submitted_utc": utc_now(),
    }
    maintenance["status"] = "reviewing"
    state = load_state(root, slug)
    get_presentation(state, presentation_id)["maintenance"] = maintenance
    save_state(root, slug, state)
    append_log(
        root,
        slug,
        actor=f"specialist-reviewer:{channel}",
        kind="maintenance",
        presentation_id=presentation_id,
        channel=channel,
        message=f"Submitted maintenance review attempt {attempt} for {channel}.",
    )
    return review["channels"][channel]


@transactional_task_mutation
def aggregate_maintenance_review(
    root: Path,
    slug: str,
    presentation_id: str,
    *,
    aggregate_path: Path,
) -> dict[str, Any]:
    require_gate(root, slug)
    maintenance, base = active_maintenance(root, slug, presentation_id)
    if maintenance.get("status") not in {"review_requested", "reviewing"}:
        raise MPresError("Maintenance review is not ready for aggregation.")
    channels = (maintenance.get("review") or {}).get("channels") or {}
    missing = [channel for channel in REVIEW_CHANNELS if channel not in channels]
    if missing:
        raise MPresError("Cannot aggregate maintenance review before all channels submit: " + ", ".join(missing))
    aggregate_path = aggregate_path.resolve()
    if not aggregate_path.is_file() or text_placeholders(aggregate_path):
        raise MPresError("Maintenance aggregate report is missing or incomplete.")
    if len(aggregate_path.read_text(encoding="utf-8").strip()) < 350:
        raise MPresError("Maintenance aggregate report is too short.")
    collected: list[dict[str, Any]] = []
    ids: set[str] = set()
    submissions: dict[str, str] = {}
    for channel in REVIEW_CHANNELS:
        submission = root / str(channels[channel]["submission"])
        receipt = submission / "receipt.json"
        report = submission / "report.md"
        findings = submission / "findings.yaml"
        if not receipt.is_file() or not report.is_file() or len(report.read_text(encoding="utf-8").strip()) < 250:
            raise MPresError(f"Current maintenance {channel} handoff is incomplete.")
        rows = _normalize_findings_file(findings)
        for item in rows:
            finding_id = str(item["id"])
            if finding_id in ids:
                raise MPresError(f"Maintenance finding ID is duplicated across channels: {finding_id}")
            ids.add(finding_id)
            collected.append(item)
        submissions[channel] = relative_display(submission, root)
    request = read_json(base / "review" / "full" / "request" / "request.json")
    routing = build_revision_routing(
        root,
        slug,
        presentation_id,
        findings=collected,
        request_source=root / str(request["source_path"]),
    )
    review_root = base / "review" / "full"
    canonical = review_root / "aggregate.md"
    canonical.write_text(aggregate_path.read_text(encoding="utf-8"), encoding="utf-8", newline="\n")
    write_yaml_atomic(
        review_root / "findings.yaml",
        {
            "schema_version": 1,
            "presentation_id": presentation_id,
            "findings": collected,
            "source_submissions": submissions,
        },
    )
    write_yaml_atomic(review_root / "REVISION-ROUTING.yaml", routing)
    write_yaml_atomic(
        base / "source" / "MAINTENANCE-AUTHOR-RESPONSES.yaml",
        {
            "schema_version": 1,
            "presentation_id": presentation_id,
            "revision": maintenance["revision"],
            "responses": [
                {
                    "id": str(item["id"]),
                    "disposition": "[[DISPOSITION]]",
                    "evidence": "[[EVIDENCE]]",
                    "location": "[[LOCATION]]",
                    "remaining_uncertainty": "[[UNCERTAINTY_OR_NONE]]",
                }
                for item in collected
            ],
        },
    )
    maintenance["status"] = "author_revision"
    maintenance["review"].update(
        {
            "aggregate": relative_display(canonical, root),
            "findings": relative_display(review_root / "findings.yaml", root),
            "routing": relative_display(review_root / "REVISION-ROUTING.yaml", root),
            "finding_ids": sorted(ids),
            "completed_utc": utc_now(),
        }
    )
    state = load_state(root, slug)
    get_presentation(state, presentation_id)["maintenance"] = maintenance
    save_state(root, slug, state)
    append_log(
        root,
        slug,
        actor="maintenance-review-aggregation-job",
        kind="maintenance",
        presentation_id=presentation_id,
        message=f"Atomically aggregated full corrective review r{maintenance['revision']:04d} and returned it to the author.",
        data={"finding_count": len(ids)},
    )
    return maintenance["review"]


def _checklist_complete(path: Path) -> None:
    if not path.is_file() or text_placeholders(path):
        raise MPresError("MAINTENANCE-CHECKLIST.yaml is missing or incomplete.")
    value = read_yaml(path)
    steps = value.get("steps") if isinstance(value, dict) else None
    if not isinstance(steps, dict) or not steps or any(item is not True for item in steps.values()):
        raise MPresError("Every maintenance checklist step must be true.")
    if parse_utc(str(value.get("completed_utc") or "")) is None:
        raise MPresError("Maintenance checklist needs a valid completed_utc timestamp.")
    if len(str(value.get("author_declaration") or "").strip()) < 20:
        raise MPresError("Maintenance checklist needs a substantive author declaration.")


def _responses_cover_findings(base: Path) -> None:
    findings_value = read_yaml(base / "review" / "full" / "findings.yaml")
    findings = findings_value.get("findings") if isinstance(findings_value, dict) else None
    response_value = read_yaml(base / "source" / "MAINTENANCE-AUTHOR-RESPONSES.yaml")
    responses = response_value.get("responses") if isinstance(response_value, dict) else None
    if not isinstance(findings, list) or not isinstance(responses, list):
        raise MPresError("Maintenance findings or author responses are malformed.")
    finding_ids = {str(item.get("id")) for item in findings if isinstance(item, dict)}
    response_ids = {str(item.get("id")) for item in responses if isinstance(item, dict)}
    if finding_ids != response_ids:
        raise MPresError("Maintenance author responses must cover every finding ID exactly.")
    for item in responses:
        if not isinstance(item, dict) or text_placeholders(base / "source" / "MAINTENANCE-AUTHOR-RESPONSES.yaml"):
            raise MPresError("Maintenance author responses remain incomplete.")
        if len(str(item.get("evidence") or "").strip()) < 5:
            raise MPresError(f"Maintenance author response {item.get('id')} lacks evidence.")


@transactional_task_mutation
def complete_maintenance(root: Path, slug: str, presentation_id: str) -> dict[str, Any]:
    require_gate(root, slug)
    maintenance, base = active_maintenance(root, slug, presentation_id)
    mode = str(maintenance.get("mode"))
    allowed_statuses = {"open"} if mode == "targeted_patch" else {"author_revision"}
    if maintenance.get("status") not in allowed_statuses:
        raise MPresError(f"Maintenance completion is not allowed from {maintenance.get('status')!r} status.")
    _require_maintenance_assignment(root, base)
    _checklist_complete(base / "source" / "MAINTENANCE-CHECKLIST.yaml")
    retrospective = base / "source" / "MAINTENANCE-RETROSPECTIVE.md"
    if not retrospective.is_file() or text_placeholders(retrospective):
        raise MPresError("MAINTENANCE-RETROSPECTIVE.md is missing or incomplete.")
    if len(retrospective.read_text(encoding="utf-8").strip()) < 300:
        raise MPresError("MAINTENANCE-RETROSPECTIVE.md is too short.")
    if mode == "full_corrective_review":
        _responses_cover_findings(base)
    report = read_json(base / "build" / "render-report-maintenance.json")
    if report.get("success") is not True or report.get("pipeline") != RENDER_PIPELINE:
        raise MPresError("A successful maintenance render is required after completing the correction.")
    source_snapshot = base / "build" / "source-snapshot"
    ready = base / "release-ready"
    if ready.exists():
        make_tree_writable(ready)
        shutil.rmtree(ready)
    ready.mkdir(parents=True, exist_ok=True)
    copy_source_tree(source_snapshot, ready / "source", read_only=True)
    shutil.copy2(base / "build" / f"{presentation_id}.pdf", ready / f"{presentation_id}.pdf")
    for name in (
        "render-report-maintenance.json",
        "source-lint-maintenance.json",
        "asset-validation-maintenance.json",
        "math-source-inventory-maintenance.json",
        "math-renderer-probe-maintenance.json",
        "slide-density-audit-maintenance.json",
        "course-consistency-maintenance.json",
        "html-layout-inspection-maintenance.json",
        "pdf-inspection-maintenance.json",
    ):
        path = base / "build" / name
        if path.is_file():
            shutil.copy2(path, ready / name)
    maintenance["status"] = "release_ready"
    maintenance["ready_utc"] = utc_now()
    state = load_state(root, slug)
    get_presentation(state, presentation_id)["maintenance"] = maintenance
    save_state(root, slug, state)
    write_json_atomic(
        ready / "release-readiness.json",
        {
            "schema_version": 1,
            "presentation_id": presentation_id,
            "revision": maintenance["revision"],
            "mode": mode,
            "ready_utc": maintenance["ready_utc"],
            "post_revision_reviewer_verification": False,
            "finding_resolution_checked": False,
        },
    )
    append_log(
        root,
        slug,
        actor="author-coordinator",
        kind="maintenance",
        presentation_id=presentation_id,
        message=f"Completed corrective maintenance r{maintenance['revision']:04d}; ready for numbered publication.",
    )
    return maintenance


@transactional_task_mutation
def publish_maintenance(root: Path, slug: str, presentation_id: str) -> dict[str, Any]:
    require_gate(root, slug)
    maintenance, base = active_maintenance(root, slug, presentation_id)
    if maintenance.get("status") != "release_ready":
        raise MPresError("Maintenance revision is not release-ready.")
    revision = int(maintenance["revision"])
    task = task_path(root, slug)
    ready = base / "release-ready"
    pdf = ready / f"{presentation_id}.pdf"
    if not pdf.is_file() or not (ready / "source").is_dir():
        raise MPresError("Maintenance release-ready artifacts are missing.")
    destination = task / "deliverables" / presentation_id / "revisions" / f"r{revision:04d}"
    if destination.exists():
        raise MPresError(f"Published maintenance revision already exists: {destination}")
    destination.mkdir(parents=True, exist_ok=False)
    shutil.copy2(pdf, destination / pdf.name)
    copy_source_tree(ready / "source", destination / "source")
    for path in ready.iterdir():
        if path.name in {pdf.name, "source"}:
            continue
        if path.is_file():
            shutil.copy2(path, destination / path.name)
    release = {
        "schema_version": 1,
        "task_slug": slug,
        "presentation_id": presentation_id,
        "revision": revision,
        "mode": maintenance["mode"],
        "published_utc": utc_now(),
        "pdf": relative_display(destination / pdf.name, root),
        "source": relative_display(destination / "source", root),
        "historical_base_release_preserved": True,
    }
    write_json_atomic(destination / "release.json", release)
    write_json_atomic(
        task / "deliverables" / presentation_id / "CURRENT-REVISION.json",
        {
            "schema_version": 1,
            "presentation_id": presentation_id,
            "revision": revision,
            "pdf": release["pdf"],
            "source": release["source"],
            "release": relative_display(destination / "release.json", root),
            "updated_utc": release["published_utc"],
        },
    )
    state = load_state(root, slug)
    presentation = get_presentation(state, presentation_id)
    maintenance["status"] = "published"
    maintenance["published_utc"] = release["published_utc"]
    presentation.setdefault("maintenance_history", []).append(dict(maintenance))
    presentation["maintenance"] = None
    presentation.setdefault("artifacts", {})["current_revision"] = revision
    presentation["artifacts"]["current_pdf"] = release["pdf"]
    save_state(root, slug, state)
    append_log(
        root,
        slug,
        actor="maintenance-release-job",
        kind="maintenance",
        presentation_id=presentation_id,
        message=f"Published corrective revision r{revision:04d} without overwriting the historical release.",
        data={"pdf": release["pdf"]},
    )
    return release


def maintenance_status(root: Path, slug: str, presentation_id: str) -> dict[str, Any]:
    state = load_state(root, slug)
    presentation = get_presentation(state, presentation_id)
    return {
        "presentation_id": presentation_id,
        "active": presentation.get("maintenance"),
        "history": presentation.get("maintenance_history", []),
        "current_artifacts": presentation.get("artifacts", {}),
    }
