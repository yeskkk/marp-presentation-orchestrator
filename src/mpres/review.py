from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path
from typing import Any

from mpres.assignments import ensure_assignment_taskbook, scaffold_assignment_contract
from mpres.control_jobs import (
    RELEASE_ACTOR,
    REVIEW_AGGREGATION_ACTOR,
    complete_release_job,
    complete_review_aggregation_job,
    mechanical_aggregate_markdown,
    prepare_release_job,
    prepare_review_aggregation_job,
    release_workspace,
    require_release_job,
    require_review_aggregation_job,
)
from mpres.logs import append_log
from mpres.milestones import record_milestone
from mpres.production import (
    assignment_path,
    check_assignment,
    prepare_revision_author_workspace,
)
from mpres.rendering import RENDER_PIPELINE, source_and_build_paths
from mpres.scheduling import refresh_active_presentation_window
from mpres.scaffolds import ensure_copy, ensure_json, ensure_text, ensure_tree, ensure_yaml
from mpres.revision_routing import build_revision_routing, write_revision_work_queues
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

REVIEW_ROUND = "full"
REQUIRED_FINDING_FIELDS = {
    "id",
    "channel",
    "round_opened",
    "location",
    "issue",
    "learner_impact",
    "acceptance_criteria",
    "verification_method",
}
AUTHOR_DISPOSITIONS = {"accepted", "partially_accepted", "declined"}


def _review_root(root: Path, slug: str, presentation_id: str) -> Path:
    return task_path(root, slug) / "reviews" / presentation_id


def _request_root(root: Path, slug: str, presentation_id: str) -> Path:
    return _review_root(root, slug, presentation_id) / REVIEW_ROUND / "request"


def _findings_path(root: Path, slug: str, presentation_id: str) -> Path:
    return _review_root(root, slug, presentation_id) / "findings.yaml"


def _load_findings(root: Path, slug: str, presentation_id: str) -> dict[str, Any]:
    path = _findings_path(root, slug, presentation_id)
    value = read_yaml(path)
    if not isinstance(value, dict) or not isinstance(value.get("findings"), list):
        raise MPresError(f"Findings registry must contain a findings list: {path}")
    return value


def _save_findings(root: Path, slug: str, presentation_id: str, value: dict[str, Any]) -> None:
    write_yaml_atomic(_findings_path(root, slug, presentation_id), value)


def _validate_render(build: Path, stage: str) -> tuple[dict[str, Any], list[Path]]:
    report_path = build / f"render-report-{stage}.json"
    report = read_json(report_path)
    if report.get("pipeline") != RENDER_PIPELINE or report.get("success") is not True:
        raise MPresError("A successful Marp PDF render is required.")
    mechanical_reports = [
        build / f"source-lint-{stage}.json",
        build / f"asset-validation-{stage}.json",
        build / f"math-source-inventory-{stage}.json",
        build / f"math-renderer-probe-{stage}.json",
        build / f"slide-density-audit-{stage}.json",
        build / f"course-consistency-{stage}.json",
        build / f"html-layout-inspection-{stage}.json",
        build / f"pdf-inspection-{stage}.json",
    ]
    for path in mechanical_reports:
        if not path.is_file() or read_json(path).get("success") is not True:
            raise MPresError(
                "Author mechanical self-check must pass before workflow advance: " + str(path)
            )
    snapshot = build / "source-snapshot"
    if not snapshot.is_dir():
        raise MPresError("Frozen render source snapshot is missing; rerender first.")
    pdf = build / f"{report.get('presentation_id')}.pdf"
    if not pdf.is_file():
        raise MPresError("Rendered PDF is missing.")
    # Mechanical reports are author/release gates. They are deliberately not copied into the
    # specialist review bundle: reviewers assess content, language, pedagogy, audience fit, and
    # non-mechanical presentation design rather than rerunning overflow checks.
    return report, [pdf]


def _scaffold_specialist_assignments(
    root: Path, slug: str, presentation_id: str, request_root: Path
) -> dict[str, Any]:
    """Create only missing reviewer files and preserve every existing submission."""

    task = task_path(root, slug)
    assignment_template = (
        root / "compat" / "legacy" / "templates" / "assignments" / "TASK-specialist-reviewer.template.md"
    ).read_text(encoding="utf-8")
    report_template = (
        root / "compat" / "legacy" / "templates" / "review" / "review-report.template.md"
    ).read_text(encoding="utf-8")
    created: list[str] = []
    preserved: list[str] = []
    for channel in REVIEW_CHANNELS:
        channel_root = (
            task
            / "workers"
            / "specialist-reviewers"
            / presentation_id
            / REVIEW_ROUND
            / channel
        )
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
        assignment = assignment_template
        for old, new in values.items():
            assignment = assignment.replace(old, new)
        assignment_path_value = channel_root / "TASK-SPECIALIST-REVIEWER.md"
        taskbook = ensure_assignment_taskbook(assignment_path_value, assignment)
        created.extend(taskbook["created"])
        preserved.extend(taskbook["preserved"])
        contract = scaffold_assignment_contract(
            root,
            assignment_path_value,
            assignment_id=f"{presentation_id}:{REVIEW_ROUND}:{channel}",
            role="specialist-reviewer",
            presentation_id=presentation_id,
            round_name=REVIEW_ROUND,
            channel=channel,
            requested_by="review-aggregation-job",
            need=(
                f"A planner must own the exact {channel} assignment for the sole full-deck review; "
                "the reviewer must read the complete frozen deck."
            ),
        )
        created.extend(contract["created"])
        preserved.extend(contract["preserved"])
        report = report_template.replace("[[CHANNEL]]", channel).replace(
            "[[PRESENTATION_ID]]", presentation_id
        ).replace("[[ROUND]]", REVIEW_ROUND)
        result = ensure_text(channel_root / "report.md", report)
        created.extend(result.created)
        preserved.extend(result.preserved)
        result = ensure_yaml(
            channel_root / "findings.yaml",
            {
                "schema_version": 3,
                "presentation_id": presentation_id,
                "round": REVIEW_ROUND,
                "channel": channel,
                "findings": [],
            },
        )
        created.extend(result.created)
        preserved.extend(result.preserved)
    return {"created": created, "preserved": preserved, "changed": bool(created)}



@transactional_task_mutation
def request_review(
    root: Path,
    slug: str,
    presentation_id: str,
    *,
    changed_areas: list[str] | None = None,
) -> dict[str, Any]:
    """Freeze one complete deck and idempotently materialize its review workspace."""

    require_gate(root, slug)
    state = load_state(root, slug)
    if state.get("phase") != "working":
        raise MPresError(f"Cannot request review while task phase is {state.get('phase')!r}.")
    presentation = get_presentation(state, presentation_id)
    request_root = _request_root(root, slug, presentation_id)
    request_path = request_root / "request.json"
    if presentation.get("status") in {"review_requested", "reviewing"}:
        existing = read_json(request_path) if request_path.is_file() else None
        if not isinstance(existing, dict):
            raise MPresError(
                "Presentation state says review is active, but its canonical request is missing or malformed."
            )
        expected = {
            "task_slug": slug,
            "presentation_id": presentation_id,
            "round": REVIEW_ROUND,
        }
        mismatches = [key for key, value in expected.items() if existing.get(key) != value]
        if changed_areas is not None and existing.get("changed_areas") != changed_areas:
            mismatches.append("changed_areas")
        if mismatches:
            raise MPresError(
                "Existing review request has different semantics and will not be overwritten: "
                + ", ".join(mismatches)
            )
        frozen_source = request_root / "source"
        rendered = request_root / "rendered"
        if not frozen_source.is_dir() or not rendered.is_dir():
            raise MPresError(
                "Active review freeze is incomplete; reconstructing a committed frozen deck is forbidden."
            )
        job = prepare_review_aggregation_job(root, slug, presentation_id)
        scaffold = _scaffold_specialist_assignments(
            root, slug, presentation_id, request_root
        )
        return {
            **existing,
            "already_requested": True,
            "review_job": relative_display(job, root),
            "scaffold_created": scaffold["created"],
            "scaffold_preserved": scaffold["preserved"],
        }
    if presentation.get("status") != "authoring":
        raise MPresError("The sole full review may be requested only from authoring status.")
    author_assignment = check_assignment(root, slug, "author-coordinator", presentation_id)
    if not author_assignment.get("ready"):
        raise MPresError("author-coordinator assignment is incomplete or not planner-approved.")
    source, build = source_and_build_paths(root, slug, presentation_id, "author")
    report, evidence_paths = _validate_render(build, "author")
    self_check = source / "SELF-CHECK.md"
    if not self_check.is_file() or text_placeholders(self_check):
        raise MPresError("Author SELF-CHECK.md is missing or incomplete.")
    if len(self_check.read_text(encoding="utf-8").strip()) < 300:
        raise MPresError("Author SELF-CHECK.md is too short.")

    request_root.mkdir(parents=True, exist_ok=True)
    rendered = request_root / "rendered"
    rendered.mkdir(parents=True, exist_ok=True)
    frozen_source = request_root / "source"
    if frozen_source.exists():
        make_tree_writable(frozen_source)
        ensure_tree(build / "source-snapshot", frozen_source)
    else:
        copy_source_tree(build / "source-snapshot", frozen_source, read_only=False)
    ensure_copy(self_check, request_root / "SELF-CHECK.md")
    for path in evidence_paths:
        ensure_copy(path, rendered / path.name)

    existing_request = read_json(request_path) if request_path.is_file() else None
    if existing_request is not None:
        expected_identity = {
            "task_slug": slug,
            "presentation_id": presentation_id,
            "round": REVIEW_ROUND,
        }
        mismatches = [
            key for key, value in expected_identity.items() if existing_request.get(key) != value
        ]
        if mismatches:
            raise MPresError(
                f"Existing review freeze belongs to a different request at {request_path}: "
                + ", ".join(mismatches)
            )
        if changed_areas is not None and existing_request.get("changed_areas") != changed_areas:
            raise MPresError(
                "Existing review request has different changed_areas and will not be overwritten."
            )
        frozen_utc = str(existing_request.get("created_utc") or utc_now())
        request = existing_request
    else:
        frozen_utc = utc_now()
        request = {
            "schema_version": 4,
            "task_slug": slug,
            "presentation_id": presentation_id,
            "round": REVIEW_ROUND,
            "created_utc": frozen_utc,
            "scope": "complete frozen deck; every one of five reviewers reads the entire deck",
            "changed_areas": changed_areas or [],
            "source_path": relative_display(frozen_source, root),
            "pdf_path": relative_display(rendered / f"{presentation_id}.pdf", root),
            "render_transaction_id": report.get("render_transaction_id"),
            "status": "pending_planner_approval_of_review_assignments",
            "post_revision_review": "forbidden-by-policy",
            "integrity_policy": "frozen snapshot; no hashes except TASK.md confirmation",
        }
        ensure_json(request_path, request)
    make_tree_read_only(frozen_source)
    make_tree_read_only(rendered)

    review_root = _review_root(root, slug, presentation_id)
    review_plan = review_root / "REVIEW-PLAN.yaml"
    plan_text = (
        root / "compat" / "legacy" / "templates" / "structured" / "REVIEW-PLAN.template.yaml"
    ).read_text(encoding="utf-8")
    for old, new in {
        "[[PRESENTATION_ID]]": presentation_id,
        "[[FROZEN_UTC]]": frozen_utc,
        "[[FROZEN_SOURCE]]": relative_display(frozen_source, root),
        "[[FROZEN_PDF]]": relative_display(rendered / f"{presentation_id}.pdf", root),
    }.items():
        plan_text = plan_text.replace(old, new)
    ensure_text(review_plan, plan_text)

    presentation["status"] = "review_requested"
    presentation["active_round"] = REVIEW_ROUND
    presentation["rounds"] = {
        REVIEW_ROUND: {
            "status": "requested",
            "request": relative_display(request_path, root),
            "review_plan": relative_display(review_plan, root),
            "channels": {},
            "requested_utc": request["created_utc"],
        }
    }
    active_window = refresh_active_presentation_window(root, slug, state)
    review_job = prepare_review_aggregation_job(root, slug, presentation_id)
    scaffold_report = _scaffold_specialist_assignments(root, slug, presentation_id, request_root)
    append_log(
        root,
        slug,
        actor=REVIEW_AGGREGATION_ACTOR,
        kind="progress",
        presentation_id=presentation_id,
        round_name=REVIEW_ROUND,
        message="Registered the runtime-free review-aggregation job and began waiting for five reviewer receipts.",
        data={
            "job": relative_display(review_job, root),
            "scaffold_created": scaffold_report["created"],
        },
    )
    record_milestone(
        root,
        slug,
        "deck_frozen",
        presentation_id=presentation_id,
        data={"review_plan": relative_display(review_plan, root)},
    )
    append_log(
        root,
        slug,
        actor="author-coordinator",
        kind="review",
        presentation_id=presentation_id,
        round_name=REVIEW_ROUND,
        message=(
            "Froze the complete deck, created five just-in-time specialist assignments, "
            "and registered a mechanical review-aggregation job."
        ),
        data={
            "request": relative_display(request_path, root),
            "review_plan": relative_display(review_plan, root),
            "active_presentations": active_window["active_presentations"],
            "activated_next_authoring": active_window["activated"],
        },
    )
    return {**request, "already_requested": False}


def _normalize_findings_file(path: Path) -> list[dict[str, Any]]:
    value = read_yaml(path)
    findings = value if isinstance(value, list) else value.get("findings") if isinstance(value, dict) else None
    if not isinstance(findings, list):
        raise MPresError(f"Structured findings must be a list in {path}.")
    normalized: list[dict[str, Any]] = []
    for item in findings:
        if not isinstance(item, dict):
            raise MPresError(f"Every finding must be a mapping in {path}.")
        missing = REQUIRED_FINDING_FIELDS - set(item)
        if missing:
            raise MPresError(f"Finding {item.get('id')!r} is missing fields: {sorted(missing)}")
        if not isinstance(item.get("location"), dict):
            raise MPresError(f"Finding {item.get('id')!r} location must be a mapping.")
        for field in REQUIRED_FINDING_FIELDS - {"location"}:
            if not str(item.get(field, "")).strip():
                raise MPresError(f"Finding {item.get('id')!r} has an empty {field}.")
        forbidden = {"review_status", "review_rationale", "resolved", "closed_utc", "last_reviewed_round"}
        present_forbidden = sorted(forbidden & set(item))
        if present_forbidden:
            raise MPresError(
                f"Finding {item.get('id')!r} contains obsolete resolution field(s): "
                + ", ".join(present_forbidden)
            )
        clean = {key: item[key] for key in item if key != "author_response"}
        clean["author_response"] = None
        normalized.append(clean)
    ids = [str(item["id"]) for item in normalized]
    if len(ids) != len(set(ids)):
        raise MPresError("Structured findings contain duplicate IDs.")
    return normalized


def _stable_finding_fields(item: dict[str, Any]) -> dict[str, Any]:
    return {
        key: item.get(key)
        for key in (
            "id",
            "channel",
            "round_opened",
            "issue",
            "learner_impact",
            "acceptance_criteria",
            "verification_method",
        )
    }


@transactional_task_mutation
def submit_channel_review(
    root: Path,
    slug: str,
    presentation_id: str,
    *,
    round_name: str,
    channel: str,
    report_path: Path,
    findings_path: Path,
) -> dict[str, Any]:
    """Submit or narrowly correct one channel handoff before aggregation.

    A resubmission may correct location, evidence_path, or reviewer_note, but it may not add/remove
    finding IDs or change the substantive finding fields. The shared findings registry is untouched
    until all five current handoffs validate and aggregate atomically.
    """

    require_gate(root, slug)
    if round_name != REVIEW_ROUND or channel not in REVIEW_CHANNELS:
        raise MPresError("Only the full round and the five configured channels are valid.")
    state = load_state(root, slug)
    presentation = get_presentation(state, presentation_id)
    if presentation.get("status") not in {"review_requested", "reviewing"}:
        raise MPresError(f"Cannot submit a channel in {presentation.get('status')!r} status.")
    round_state = presentation["rounds"][REVIEW_ROUND]
    if round_state.get("status") == "completed":
        raise MPresError("The review has already been aggregated; channel resubmission is closed.")
    assignment = check_assignment(
        root,
        slug,
        "specialist-reviewer",
        presentation_id,
        round_name=REVIEW_ROUND,
        channel=channel,
    )
    if not assignment.get("ready"):
        raise MPresError("The specialist assignment is incomplete or not planner-approved.")
    report_path = report_path.resolve()
    findings_path = findings_path.resolve()
    if not report_path.is_file() or text_placeholders(report_path):
        raise MPresError("Specialist report is missing or incomplete.")
    report_text = report_path.read_text(encoding="utf-8")
    if len(report_text.strip()) < 250:
        raise MPresError("Specialist report is too short to document scope and evidence.")
    submitted = _normalize_findings_file(findings_path)
    for item in submitted:
        if item["channel"] != channel or item["round_opened"] != REVIEW_ROUND:
            raise MPresError(f"Finding {item['id']} has the wrong channel or round.")

    channel_root = (
        task_path(root, slug)
        / "workers"
        / "specialist-reviewers"
        / presentation_id
        / REVIEW_ROUND
        / channel
    )
    channel_state = round_state.setdefault("channels", {}).get(channel)
    previous: list[dict[str, Any]] | None = None
    previous_attempt: int | None = None
    if isinstance(channel_state, dict) and channel_state.get("submission"):
        previous_attempt = int(channel_state.get("attempt") or 1)
        previous_path = root / str(channel_state["submission"]) / "findings.yaml"
        previous = _normalize_findings_file(previous_path)
        previous_by_id = {str(item["id"]): item for item in previous}
        current_by_id = {str(item["id"]): item for item in submitted}
        if set(previous_by_id) != set(current_by_id):
            raise MPresError(
                "A channel resubmission may not add or remove finding IDs after first submission."
            )
        for finding_id in sorted(previous_by_id):
            if _stable_finding_fields(previous_by_id[finding_id]) != _stable_finding_fields(
                current_by_id[finding_id]
            ):
                raise MPresError(
                    f"Resubmission of {finding_id} changes substantive finding fields. Only "
                    "location, evidence_path, and reviewer_note may be corrected."
                )
            allowed = {
                *REQUIRED_FINDING_FIELDS,
                "author_response",
                "evidence_path",
                "reviewer_note",
            }
            unexpected = set(current_by_id[finding_id]) - allowed
            if unexpected:
                raise MPresError(
                    f"Resubmission of {finding_id} contains unsupported mutable field(s): "
                    + ", ".join(sorted(unexpected))
                )
    attempt = (previous_attempt or 0) + 1
    submission_root = channel_root / "submissions" / f"attempt-{attempt:04d}"
    if submission_root.exists():
        raise MPresError(f"Review submission attempt already exists: {submission_root}")
    submission_root.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="mpres-review-submit-", dir=submission_root.parent) as raw:
        staged = Path(raw)
        (staged / "report.md").write_text(report_text, encoding="utf-8", newline="\n")
        write_yaml_atomic(
            staged / "findings.yaml",
            {
                "schema_version": 4,
                "presentation_id": presentation_id,
                "round": REVIEW_ROUND,
                "channel": channel,
                "findings": submitted,
            },
        )
        write_json_atomic(
            staged / "receipt.json",
            {
                "schema_version": 1,
                "presentation_id": presentation_id,
                "round": REVIEW_ROUND,
                "channel": channel,
                "attempt": attempt,
                "supersedes_attempt": previous_attempt,
                "submitted_utc": utc_now(),
                "finding_ids": [str(item["id"]) for item in submitted],
                "mutable_fields": ["location", "evidence_path", "reviewer_note"],
            },
        )
        os.replace(staged, submission_root)
    canonical_report = channel_root / "report.md"
    canonical_findings = channel_root / "findings.yaml"
    shutil.copy2(submission_root / "report.md", canonical_report)
    shutil.copy2(submission_root / "findings.yaml", canonical_findings)
    presentation["status"] = "reviewing"
    round_state["status"] = "reviewing"
    round_state["channels"][channel] = {
        "submitted_utc": utc_now(),
        "attempt": attempt,
        "submission": relative_display(submission_root, root),
        "report": relative_display(canonical_report, root),
        "findings": relative_display(canonical_findings, root),
        "finding_count": len(submitted),
    }
    refresh_active_presentation_window(root, slug, state)
    append_log(
        root,
        slug,
        actor=f"specialist-reviewer:{channel}",
        kind="review",
        presentation_id=presentation_id,
        round_name=REVIEW_ROUND,
        channel=channel,
        message=(
            f"Submitted {channel} review attempt {attempt}. The shared registry remains unchanged "
            "until all five handoffs aggregate atomically."
        ),
        data={"finding_count": len(submitted), "attempt": attempt},
    )
    return round_state["channels"][channel]


@transactional_task_mutation
def aggregate_round(
    root: Path,
    slug: str,
    presentation_id: str,
    *,
    round_name: str,
    aggregate_path: Path | None = None,
) -> dict[str, Any]:
    require_gate(root, slug)
    if round_name != REVIEW_ROUND:
        raise MPresError("Only one full review round exists.")
    state = load_state(root, slug)
    presentation = get_presentation(state, presentation_id)
    if presentation.get("status") not in {"review_requested", "reviewing"}:
        raise MPresError(f"Cannot aggregate in {presentation.get('status')!r} status.")
    require_review_aggregation_job(root, slug, presentation_id)
    round_state = presentation["rounds"][REVIEW_ROUND]
    channels = round_state.get("channels", {})
    missing = [channel for channel in REVIEW_CHANNELS if channel not in channels]
    if missing:
        raise MPresError("Cannot aggregate before all channels submit: " + ", ".join(missing))
    collected: list[dict[str, Any]] = []
    source_submissions: dict[str, str] = {}
    ids: set[str] = set()
    for channel in REVIEW_CHANNELS:
        channel_state = channels[channel]
        submission_root = root / str(channel_state.get("submission") or "")
        report = submission_root / "report.md"
        findings = submission_root / "findings.yaml"
        receipt = submission_root / "receipt.json"
        if not report.is_file() or len(report.read_text(encoding="utf-8").strip()) < 250:
            raise MPresError(f"Current {channel} report is missing or incomplete.")
        if not receipt.is_file():
            raise MPresError(f"Current {channel} submission receipt is missing.")
        rows = _normalize_findings_file(findings)
        for item in rows:
            finding_id = str(item["id"])
            if finding_id in ids:
                raise MPresError(f"Finding ID is duplicated across channels: {finding_id}")
            if item["channel"] != channel or item["round_opened"] != REVIEW_ROUND:
                raise MPresError(f"Finding {finding_id} has the wrong channel or round.")
            ids.add(finding_id)
            collected.append(item)
        source_submissions[channel] = relative_display(submission_root, root)

    request = read_json(_request_root(root, slug, presentation_id) / "request.json")
    request_source = root / str(request["source_path"])
    review_plan = _review_root(root, slug, presentation_id) / "REVIEW-PLAN.yaml"
    routing = build_revision_routing(root, slug, presentation_id, findings=collected, request_source=request_source)

    aggregate_text = mechanical_aggregate_markdown(
        presentation_id,
        source_submissions=source_submissions,
        findings=collected,
    )
    canonical = _review_root(root, slug, presentation_id) / REVIEW_ROUND / "aggregate.md"
    registry_value = {
        "schema_version": 5,
        "presentation_id": presentation_id,
        "findings": collected,
        "source_submissions": source_submissions,
    }
    canonical.write_text(aggregate_text, encoding="utf-8", newline="\n")
    _save_findings(root, slug, presentation_id, registry_value)

    _, source = prepare_revision_author_workspace(
        root,
        slug,
        presentation_id,
        frozen_source=request_source,
        finding_registry=_findings_path(root, slug, presentation_id),
        review_plan=review_plan,
    )
    routing_result = write_revision_work_queues(root, slug, presentation_id, routing)
    response_path = source / "AUTHOR-RESPONSES.yaml"
    write_yaml_atomic(
        response_path,
        {
            "schema_version": 5,
            "presentation_id": presentation_id,
            "responding_to_round": REVIEW_ROUND,
            "responding_role": "deck-revision-author",
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
    checklist_path = source / "AUTHOR-MODIFICATION-CHECKLIST.yaml"
    template = (root / "compat" / "legacy" / "templates" / "structured" / "AUTHOR-MODIFICATION-CHECKLIST.template.yaml").read_text(encoding="utf-8").replace("[[PRESENTATION_ID]]", presentation_id)
    checklist_path.write_text(template, encoding="utf-8", newline="\n")
    decision = {
        "schema_version": 5,
        "presentation_id": presentation_id,
        "round": REVIEW_ROUND,
        "completed_utc": utc_now(),
        "required_channels": list(REVIEW_CHANNELS),
        "each_reviewer_read_entire_deck": True,
        "finding_ids": sorted(ids),
        "source_submissions": source_submissions,
        "aggregate_report": relative_display(canonical, root),
        "revision_routing": routing_result["routing"],
        "revision_queue": routing_result["revision_queue"],
        "revision_role": "deck-revision-author",
        "author_response_template": relative_display(response_path, root),
        "modification_checklist": relative_display(checklist_path, root),
        "next_status": "author_revision",
        "post_revision_review": "none",
        "original_lesson_authors_reopened": False,
    }
    write_json_atomic(canonical.parent / "decision.json", decision)
    job_receipt = complete_review_aggregation_job(
        root,
        slug,
        presentation_id,
        aggregate_report=canonical,
        findings_registry=_findings_path(root, slug, presentation_id),
        decision=canonical.parent / "decision.json",
        finding_count=len(ids),
    )
    decision["aggregation_job_receipt"] = relative_display(job_receipt, root)
    write_json_atomic(canonical.parent / "decision.json", decision)
    round_state["status"] = "completed"
    round_state["completed_utc"] = decision["completed_utc"]
    round_state["aggregate"] = decision["aggregate_report"]
    presentation["status"] = "author_revision"
    presentation["active_round"] = None
    refresh_active_presentation_window(root, slug, state)
    record_milestone(root, slug, "review_aggregated", presentation_id=presentation_id, data={"finding_count": len(ids)})
    record_milestone(root, slug, "revision_handoff", presentation_id=presentation_id, data={"role": "deck-revision-author"})
    append_log(
        root,
        slug,
        actor=REVIEW_AGGREGATION_ACTOR,
        kind="review",
        presentation_id=presentation_id,
        round_name=REVIEW_ROUND,
        message=(
            f"Mechanically collected five full-deck channel handoffs with {len(ids)} finding(s) "
            "and handed the frozen deck to one deck-revision-author; no coordinator model ran."
        ),
        data={
            "routing": routing_result["routing"],
            "revision_queue": routing_result["revision_queue"],
            "job_receipt": relative_display(job_receipt, root),
        },
    )
    return decision

@transactional_task_mutation
def record_author_responses(
    root: Path,
    slug: str,
    presentation_id: str,
    *,
    response_file: Path,
) -> dict[str, Any]:
    require_gate(root, slug)
    state = load_state(root, slug)
    presentation = get_presentation(state, presentation_id)
    if presentation.get("status") != "author_revision":
        raise MPresError("Deck-revision-author responses are expected only during author_revision.")
    revision_assignment = check_assignment(root, slug, "deck-revision-author", presentation_id)
    if not revision_assignment.get("ready"):
        raise MPresError("deck-revision-author assignment is incomplete or not planner-approved.")
    if not response_file.is_file() or text_placeholders(response_file):
        raise MPresError("Structured revision-author response file is missing or incomplete.")
    data = read_yaml(response_file)
    responses = data.get("responses") if isinstance(data, dict) else None
    if not isinstance(responses, list) or data.get("responding_to_round") != REVIEW_ROUND:
        raise MPresError("Response YAML must contain the full-round responses list.")
    registry = _load_findings(root, slug, presentation_id)
    by_id = {str(item.get("id")): item for item in registry["findings"] if isinstance(item, dict)}
    response_ids = [str(item.get("id")) for item in responses if isinstance(item, dict)]
    if len(response_ids) != len(set(response_ids)):
        raise MPresError("Revision-author response file contains duplicate finding IDs.")
    if set(response_ids) != set(by_id):
        missing = sorted(set(by_id) - set(response_ids))
        extra = sorted(set(response_ids) - set(by_id))
        raise MPresError(f"Responses must cover every finding exactly; missing={missing}, extra={extra}.")
    for response in responses:
        finding_id = str(response["id"])
        disposition = str(response.get("disposition") or "")
        if disposition not in AUTHOR_DISPOSITIONS:
            raise MPresError(f"Response {finding_id} has invalid disposition.")
        for field in ("evidence", "location"):
            if len(str(response.get(field) or "").strip()) < 5:
                raise MPresError(f"Response {finding_id} lacks substantive {field}.")
        by_id[finding_id]["author_response"] = {
            "recorded_utc": utc_now(),
            "responding_role": "deck-revision-author",
            "disposition": disposition,
            "evidence": response["evidence"],
            "location": response["location"],
            "remaining_uncertainty": response.get("remaining_uncertainty"),
        }
    _save_findings(root, slug, presentation_id, registry)
    canonical = task_path(root, slug) / "workers" / "deck-revision-author" / "drafts" / presentation_id / "source" / "AUTHOR-RESPONSES.yaml"
    if response_file.resolve() != canonical.resolve():
        shutil.copy2(response_file, canonical)
    append_log(root, slug, actor="deck-revision-author", kind="review", presentation_id=presentation_id, message=f"Recorded deck revision responses for all {len(response_ids)} finding(s).")
    return {"presentation_id": presentation_id, "responses_recorded": response_ids, "role": "deck-revision-author"}

@transactional_task_mutation
def complete_author_revision(
    root: Path,
    slug: str,
    presentation_id: str,
    *,
    checklist_file: Path,
) -> dict[str, Any]:
    """Accept the deck revision author's completed work without reviewer re-verification."""

    require_gate(root, slug)
    state = load_state(root, slug)
    presentation = get_presentation(state, presentation_id)
    if presentation.get("status") != "author_revision":
        raise MPresError("Deck revision may be completed only from author_revision status.")
    revision_assignment = check_assignment(root, slug, "deck-revision-author", presentation_id)
    if not revision_assignment.get("ready"):
        raise MPresError("deck-revision-author assignment is incomplete or not planner-approved.")
    registry = _load_findings(root, slug, presentation_id)
    missing_responses = [str(item.get("id")) for item in registry["findings"] if isinstance(item, dict) and not isinstance(item.get("author_response"), dict)]
    if missing_responses:
        raise MPresError("Every finding needs a deck-revision-author response before release: " + ", ".join(missing_responses))
    if not checklist_file.is_file() or text_placeholders(checklist_file):
        raise MPresError("Deck revision modification checklist is missing or incomplete.")
    checklist = read_yaml(checklist_file)
    steps = checklist.get("steps") if isinstance(checklist, dict) else None
    required_steps = {
        "reread_all_findings", "responded_to_every_finding", "revised_source",
        "reran_source_lint", "reran_asset_validation", "reran_html_layout_inspection",
        "rebuilt_pdf", "reran_pdf_inspection", "completed_self_check",
    }
    if not isinstance(steps, dict) or any(steps.get(key) is not True for key in required_steps):
        raise MPresError("Every deck revision modification checklist step must be true.")
    if len(str(checklist.get("author_declaration") or "").strip()) < 20:
        raise MPresError("Deck revision author declaration is missing or too short.")
    source, build = source_and_build_paths(root, slug, presentation_id, "author")
    canonical_checklist = source / "AUTHOR-MODIFICATION-CHECKLIST.yaml"
    if checklist_file.resolve() != canonical_checklist.resolve():
        raise MPresError("Complete the canonical AUTHOR-MODIFICATION-CHECKLIST.yaml inside the deck revision source.")
    completed_utc = parse_utc(str(checklist.get("completed_utc") or ""))
    if completed_utc is None:
        raise MPresError("Modification checklist must record a valid completed_utc timestamp.")
    revision_note = source / "AUTHOR-REVISION.md"
    if not revision_note.is_file() or text_placeholders(revision_note):
        raise MPresError("AUTHOR-REVISION.md is missing or incomplete.")
    if len(revision_note.read_text(encoding="utf-8").strip()) < 300:
        raise MPresError("AUTHOR-REVISION.md is too short to document the completed revision workflow.")
    report, evidence_paths = _validate_render(build, "author")
    report_time = parse_utc(report.get("started_and_finished_utc"))
    latest_input_mtime = max(path.stat().st_mtime for path in (source / "AUTHOR-RESPONSES.yaml", checklist_file, source / "SELF-CHECK.md", source / "AUTHOR-REVISION.md") if path.exists())
    if report_time is None or report_time.timestamp() + 1 < latest_input_mtime:
        raise MPresError("The successful revision render predates the response/checklist; rerender after revision.")

    task = task_path(root, slug)
    ready_root = release_workspace(root, slug, presentation_id)
    if ready_root.exists():
        make_tree_writable(ready_root)
        shutil.rmtree(ready_root)
    ready_root.mkdir(parents=True, exist_ok=True)
    copy_source_tree(build / "source-snapshot", ready_root / "source", read_only=True)
    shutil.copy2(source / "AUTHOR-RESPONSES.yaml", ready_root / "AUTHOR-RESPONSES.yaml")
    shutil.copy2(checklist_file, ready_root / "AUTHOR-MODIFICATION-CHECKLIST.yaml")
    shutil.copy2(revision_note, ready_root / "AUTHOR-REVISION.md")
    shutil.copy2(_findings_path(root, slug, presentation_id), ready_root / "findings.yaml")
    aggregate = _review_root(root, slug, presentation_id) / REVIEW_ROUND / "aggregate.md"
    if aggregate.is_file():
        shutil.copy2(aggregate, ready_root / "REVIEW-AGGREGATE.md")
    for path in evidence_paths:
        shutil.copy2(path, ready_root / path.name)
    approval = {
        "schema_version": 4,
        "task_slug": slug,
        "presentation_id": presentation_id,
        "ready_utc": utc_now(),
        "source": relative_display(ready_root / "source", root),
        "revision_role": "deck-revision-author",
        "author_responses": relative_display(ready_root / "AUTHOR-RESPONSES.yaml", root),
        "modification_checklist": relative_display(ready_root / "AUTHOR-MODIFICATION-CHECKLIST.yaml", root),
        "finding_count": len(registry["findings"]),
        "finding_resolution_checked": False,
        "post_revision_reviewer_verification": False,
        "status": "release_ready",
    }
    write_json_atomic(ready_root / "release-readiness.json", approval)
    presentation["status"] = "release_ready"
    presentation["author_revision_completed_utc"] = approval["ready_utc"]
    refresh_active_presentation_window(root, slug, state)
    release_job = prepare_release_job(root, slug, presentation_id)
    append_log(
        root,
        slug,
        actor=RELEASE_ACTOR,
        kind="progress",
        presentation_id=presentation_id,
        message="Registered the runtime-free release job from the deck revision author's validated handoff.",
        data={"job": relative_display(release_job, root)},
    )
    record_milestone(root, slug, "release_ready", presentation_id=presentation_id, data={"revision_role": "deck-revision-author"})
    append_log(
        root, slug, actor="deck-revision-author", kind="handoff", presentation_id=presentation_id,
        message="Completed the deck-wide revision and handed the frozen source directly to mechanical release without reviewer recheck.",
        data={"release_ready": relative_display(ready_root / "release-readiness.json", root)},
    )
    return approval

@transactional_task_mutation
def return_to_author(
    root: Path, slug: str, presentation_id: str, *, reason: str
) -> dict[str, Any]:
    require_gate(root, slug)
    if not reason.strip():
        raise MPresError("Returning a release-ready source requires a reason.")
    state = load_state(root, slug)
    presentation = get_presentation(state, presentation_id)
    if presentation.get("status") != "release_ready":
        raise MPresError("Only a release-ready presentation can return to the deck revision author.")
    ready = release_workspace(root, slug, presentation_id)
    archive = ready.parent / f"{presentation_id}-returned-{utc_now().replace(':', '')}"
    if ready.exists():
        make_tree_writable(ready)
        ready.rename(archive)
    presentation["status"] = "author_revision"
    refresh_active_presentation_window(root, slug, state)
    record = {"utc": utc_now(), "reason": reason.strip(), "archive": relative_display(archive, root)}
    append_log(
        root,
        slug,
        actor=RELEASE_ACTOR,
        kind="warning",
        presentation_id=presentation_id,
        message="Returned release-ready source to the deck revision author because a semantic source change became necessary.",
        data=record,
    )
    return record


@transactional_task_mutation
def finalize_release(root: Path, slug: str, presentation_id: str) -> dict[str, Any]:
    require_gate(root, slug)
    state = load_state(root, slug)
    presentation = get_presentation(state, presentation_id)
    if presentation.get("status") != "release_ready":
        raise MPresError("Finalization requires release_ready status.")
    task = task_path(root, slug)
    require_release_job(root, slug, presentation_id)
    ready = release_workspace(root, slug, presentation_id)
    report = read_json(ready / "build" / "render-report-release.json")
    if report.get("success") is not True or report.get("pipeline") != RENDER_PIPELINE:
        raise MPresError("A successful release-stage Marp render is required.")
    pdf_inspection = read_json(ready / "build" / "pdf-inspection-release.json")
    if pdf_inspection.get("success") is not True:
        raise MPresError("Release PDF inspection is missing or unsuccessful.")
    pdf = ready / "build" / f"{presentation_id}.pdf"
    if not pdf.is_file():
        raise MPresError("Release PDF is missing.")
    deliverable = task / "deliverables" / presentation_id
    maintenance_cycle = presentation.get("maintenance_cycle")
    revision = 1
    if isinstance(maintenance_cycle, dict):
        revision = int(maintenance_cycle.get("revision") or 1)
        cycle_root = root / str(maintenance_cycle.get("root") or "")
        retrospective = cycle_root / "MAINTENANCE-RETROSPECTIVE.md"
        if not retrospective.is_file():
            template = (
                root / "compat" / "legacy" / "templates" / "structured" / "MAINTENANCE-RETROSPECTIVE.template.md"
            ).read_text(encoding="utf-8")
            for old_value, new_value in {
                "[[PRESENTATION_ID]]": presentation_id,
                "[[REVISION_NUMBER]]": str(revision),
            }.items():
                template = template.replace(old_value, new_value)
            retrospective.write_text(template, encoding="utf-8", newline="\n")
        if text_placeholders(retrospective) or len(retrospective.read_text(encoding="utf-8").strip()) < 250:
            raise MPresError("Maintenance retrospective is missing or incomplete.")
    if deliverable.exists():
        previous_release_path = deliverable / "release.json"
        previous_revision = 1
        if previous_release_path.is_file():
            previous_revision = int(read_json(previous_release_path).get("revision") or 1)
        history = task / "deliverable-history" / presentation_id / f"r{previous_revision:04d}"
        if history.exists():
            raise MPresError(f"Deliverable history already exists: {history}")
        history.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(deliverable, history)
        make_tree_writable(deliverable)
        shutil.rmtree(deliverable)
    deliverable.mkdir(parents=True, exist_ok=True)
    shutil.copy2(pdf, deliverable / pdf.name)
    copy_source_tree(ready / "source", deliverable / "source")
    for name in (
        "release-readiness.json",
        "AUTHOR-MODIFICATION-CHECKLIST.yaml",
        "AUTHOR-REVISION.md",
        "AUTHOR-RESPONSES.yaml",
        "REVIEW-AGGREGATE.md",
        "findings.yaml",
    ):
        path = ready / name
        if path.is_file():
            shutil.copy2(path, deliverable / name)
    shutil.copy2(ready / "build" / "render-report-release.json", deliverable / "render-report.json")
    shutil.copy2(ready / "build" / "source-lint-release.json", deliverable / "source-lint.json")
    shutil.copy2(ready / "build" / "asset-validation-release.json", deliverable / "asset-validation.json")
    for source_name, destination_name in (
        ("math-source-inventory-release.json", "math-source-inventory.json"),
        ("math-renderer-probe-release.json", "math-renderer-probe.json"),
        ("slide-density-audit-release.json", "slide-density-audit.json"),
        ("course-consistency-release.json", "course-consistency.json"),
    ):
        source_report = ready / "build" / source_name
        if source_report.is_file():
            shutil.copy2(source_report, deliverable / destination_name)
    shutil.copy2(
        ready / "build" / "html-layout-inspection-release.json",
        deliverable / "html-layout-inspection.json",
    )
    shutil.copy2(ready / "build" / "pdf-inspection-release.json", deliverable / "pdf-inspection.json")
    sequence = int(state.get("last_delivery_sequence", 0)) + 1
    release = {
        "schema_version": 3,
        "task_slug": slug,
        "presentation_id": presentation_id,
        "title": presentation.get("title"),
        "finalized_utc": utc_now(),
        "delivery_sequence": sequence,
        "revision": revision,
        "maintenance_mode": (maintenance_cycle.get("mode") if isinstance(maintenance_cycle, dict) else None),
        "pdf": relative_display(deliverable / pdf.name, root),
        "source": relative_display(deliverable / "source", root),
        "render_pipeline": RENDER_PIPELINE,
        "post_revision_reviewer_verification": False,
        "finding_resolution_checked": False,
    }
    write_json_atomic(deliverable / "release.json", release)
    job_receipt = complete_release_job(
        root,
        slug,
        presentation_id,
        release_record=deliverable / "release.json",
        deliverable=deliverable,
    )
    release["release_job_receipt"] = relative_display(job_receipt, root)
    write_json_atomic(deliverable / "release.json", release)
    presentation["status"] = "finalized"
    presentation["active"] = False
    if isinstance(maintenance_cycle, dict):
        maintenance_cycle["status"] = "finalized"
        maintenance_cycle["finalized_utc"] = release["finalized_utc"]
        maintenance_cycle["release_revision"] = revision
    presentation["finalized_utc"] = release["finalized_utc"]
    presentation["delivery_sequence"] = sequence
    presentation["artifacts"] = {
        "pdf": release["pdf"],
        "source": release["source"],
        "release": relative_display(deliverable / "release.json", root),
    }
    state["last_delivery_sequence"] = sequence
    remaining = [item for item in state.get("presentations", []) if item.get("status") != "finalized"]
    if not remaining:
        state["phase"] = "complete"
    elif state.get("stop_mode") == "each":
        state["phase"] = "awaiting_user_continuation"
        for item in remaining:
            item["active"] = False
        state["critical_path_presentation"] = str(remaining[0].get("id"))
    elif state.get("stop_mode") == "pilot" and not state.get("pilot_pause_completed") and sequence == 1:
        state["phase"] = "awaiting_user_continuation"
        for item in remaining:
            item["active"] = False
        state["critical_path_presentation"] = str(remaining[0].get("id"))
    else:
        state["phase"] = "working"
        from mpres.scheduling import rebalance_active_presentations

        rebalance_active_presentations(root, slug, state, allow_next=True)
    save_state(root, slug, state)
    if state.get("phase") == "working":
        from mpres.production import materialize_active_author_coordinators

        materialize_active_author_coordinators(root, slug, state=state)
    from mpres.scheduling import sync_work_plan

    sync_work_plan(root, slug, state=state)
    append_log(
        root,
        slug,
        actor=RELEASE_ACTOR,
        kind="delivery",
        presentation_id=presentation_id,
        message="Published the Marp PDF and source after deck-revision-author work and mechanical release.",
        data={"pdf": release["pdf"], "next_phase": state["phase"]},
    )
    return release


def build_context_bundle(
    root: Path,
    slug: str,
    presentation_id: str,
    *,
    round_name: str,
    channel: str,
) -> dict[str, Any]:
    if round_name != REVIEW_ROUND or channel not in REVIEW_CHANNELS:
        raise MPresError("Context bundles require the full round and a valid channel.")
    task = task_path(root, slug)
    request = _request_root(root, slug, presentation_id)
    if not (request / "request.json").is_file():
        raise MPresError("Review request does not exist.")
    bundle = task / "review-cache" / presentation_id / REVIEW_ROUND / channel
    if bundle.exists():
        shutil.rmtree(bundle)
    bundle.mkdir(parents=True, exist_ok=True)
    context = (
        root / "compat" / "legacy" / "templates" / "context" / "FULL-REVIEW-CONTEXT.template.md"
    ).read_text(encoding="utf-8")
    context = context.replace("[[PRESENTATION_ID]]", presentation_id).replace(
        "[[ROUND]]", REVIEW_ROUND
    ).replace("[[CHANNEL]]", channel)
    (bundle / "CONTEXT.md").write_text(context, encoding="utf-8", newline="\n")
    paths = [
        task / "TASK.md",
        task / "EXECUTION-POLICY.yaml",
        task / "REVIEW-PROFILE.yaml",
        task / "REVIEW-PROTOCOL.md",
        task / "MARP-AUTHORING-STANDARD.md",
        task / "REFERENCE-ACCESS-POLICY.yaml",
        assignment_path(
            root,
            slug,
            "specialist-reviewer",
            presentation_id,
            round_name=REVIEW_ROUND,
            channel=channel,
        ),
        request / "request.json",
    ]
    manifest = {
        "schema_version": 3,
        "created_utc": utc_now(),
        "presentation_id": presentation_id,
        "round": REVIEW_ROUND,
        "channel": channel,
        "files": [relative_display(path, root) for path in paths if path.exists()],
        "request_source": relative_display(request / "source", root),
        "request_pdf": relative_display(request / "rendered" / f"{presentation_id}.pdf", root),
        "isolation": "Other channel findings and future author revisions are intentionally absent.",
        "reference_access": "downloads/text only; original PDFs are forbidden",
        "integrity_policy": "no hashes; consume the frozen request directory",
    }
    write_json_atomic(bundle / "bundle.json", manifest)
    return {**manifest, "bundle_path": relative_display(bundle, root)}


def review_status(root: Path, slug: str, presentation_id: str | None = None) -> dict[str, Any]:
    state = load_state(root, slug)
    presentations = state.get("presentations", [])
    if presentation_id:
        presentations = [get_presentation(state, presentation_id)]
    return {"task_slug": slug, "phase": state.get("phase"), "presentations": presentations}
