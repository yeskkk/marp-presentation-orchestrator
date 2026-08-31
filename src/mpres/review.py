from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from mpres.assignments import scaffold_assignment_contract
from mpres.logs import append_log
from mpres.production import assignment_path, check_assignment
from mpres.rendering import RENDER_PIPELINE, source_and_build_paths
from mpres.state import REVIEW_CHANNELS, get_presentation, load_state, save_state
from mpres.tasks import require_gate
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
) -> None:
    task = task_path(root, slug)
    assignment_template = (
        root / "templates" / "assignments" / "TASK-specialist-reviewer.template.md"
    ).read_text(encoding="utf-8")
    report_template = (
        root / "templates" / "review" / "review-report.template.md"
    ).read_text(encoding="utf-8")
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
        assignment_path_value.write_text(assignment, encoding="utf-8", newline="\n")
        scaffold_assignment_contract(
            root,
            assignment_path_value,
            assignment_id=f"{presentation_id}:{REVIEW_ROUND}:{channel}",
            role="specialist-reviewer",
            presentation_id=presentation_id,
            round_name=REVIEW_ROUND,
            channel=channel,
            requested_by="review-coordinator",
            need=(
                f"Planner must personally write the exact {channel} assignment for the sole "
                "full-deck review."
            ),
        )
        report = report_template.replace("[[CHANNEL]]", channel).replace(
            "[[PRESENTATION_ID]]", presentation_id
        ).replace("[[ROUND]]", REVIEW_ROUND)
        (channel_root / "report.md").write_text(report, encoding="utf-8", newline="\n")
        (channel_root / "findings.yaml").write_text(
            f"schema_version: 3\npresentation_id: {presentation_id}\nround: {REVIEW_ROUND}\n"
            f"channel: {channel}\nfindings: []\n",
            encoding="utf-8",
            newline="\n",
        )
    aggregate = (
        root / "templates" / "review" / "review-aggregate.template.md"
    ).read_text(encoding="utf-8")
    aggregate = aggregate.replace("[[PRESENTATION_ID]]", presentation_id).replace(
        "[[ROUND]]", REVIEW_ROUND
    )
    aggregate_path = _review_root(root, slug, presentation_id) / REVIEW_ROUND / "aggregate.md"
    aggregate_path.parent.mkdir(parents=True, exist_ok=True)
    aggregate_path.write_text(aggregate, encoding="utf-8", newline="\n")


def request_review(
    root: Path,
    slug: str,
    presentation_id: str,
    *,
    changed_areas: list[str] | None = None,
) -> dict[str, Any]:
    require_gate(root, slug)
    state = load_state(root, slug)
    if state.get("phase") != "working":
        raise MPresError(f"Cannot request review while task phase is {state.get('phase')!r}.")
    presentation = get_presentation(state, presentation_id)
    if presentation.get("status") != "authoring":
        raise MPresError("The sole full review may be requested only from authoring status.")
    for role in ("author-coordinator", "review-coordinator"):
        assignment = check_assignment(root, slug, role, presentation_id)
        if not assignment.get("ready"):
            raise MPresError(f"{role} assignment is incomplete or not planner-approved.")
    source, build = source_and_build_paths(root, slug, presentation_id, "author")
    report, evidence_paths = _validate_render(build, "author")
    self_check = source / "SELF-CHECK.md"
    if not self_check.is_file() or text_placeholders(self_check):
        raise MPresError("Author SELF-CHECK.md is missing or incomplete.")
    if len(self_check.read_text(encoding="utf-8").strip()) < 300:
        raise MPresError("Author SELF-CHECK.md is too short.")

    request_root = _request_root(root, slug, presentation_id)
    if request_root.exists():
        raise MPresError(f"The sole review request already exists: {request_root}")
    (request_root / "rendered").mkdir(parents=True, exist_ok=False)
    copy_source_tree(build / "source-snapshot", request_root / "source", read_only=True)
    shutil.copy2(self_check, request_root / "SELF-CHECK.md")
    for path in evidence_paths:
        shutil.copy2(path, request_root / "rendered" / path.name)
    make_tree_read_only(request_root / "rendered")
    request = {
        "schema_version": 3,
        "task_slug": slug,
        "presentation_id": presentation_id,
        "round": REVIEW_ROUND,
        "created_utc": utc_now(),
        "scope": "one complete frozen-deck review across five isolated channels",
        "changed_areas": changed_areas or [],
        "source_path": relative_display(request_root / "source", root),
        "pdf_path": relative_display(
            request_root / "rendered" / f"{presentation_id}.pdf", root
        ),
        "render_transaction_id": report.get("render_transaction_id"),
        "status": "pending",
        "post_revision_review": "forbidden-by-policy",
        "integrity_policy": "frozen snapshot; no hashes except TASK.md confirmation",
    }
    write_json_atomic(request_root / "request.json", request)
    make_tree_read_only(request_root / "source")
    _scaffold_specialist_assignments(root, slug, presentation_id, request_root)
    presentation["status"] = "review_requested"
    presentation["active_round"] = REVIEW_ROUND
    presentation["rounds"] = {
        REVIEW_ROUND: {
            "status": "requested",
            "request": relative_display(request_root / "request.json", root),
            "channels": {},
            "requested_utc": request["created_utc"],
        }
    }
    save_state(root, slug, state)
    append_log(
        root,
        slug,
        actor="author-coordinator",
        kind="review",
        presentation_id=presentation_id,
        round_name=REVIEW_ROUND,
        message="Submitted the sole full-deck review request.",
        data={"request": relative_display(request_root / "request.json", root)},
    )
    return request


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
    require_gate(root, slug)
    if round_name != REVIEW_ROUND or channel not in REVIEW_CHANNELS:
        raise MPresError("Only the full round and the five configured channels are valid.")
    state = load_state(root, slug)
    presentation = get_presentation(state, presentation_id)
    if presentation.get("status") not in {"review_requested", "reviewing"}:
        raise MPresError(f"Cannot submit a channel in {presentation.get('status')!r} status.")
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
    if len(report_path.read_text(encoding="utf-8").strip()) < 250:
        raise MPresError("Specialist report is too short to document scope and evidence.")
    submitted = _normalize_findings_file(findings_path)
    for item in submitted:
        if item["channel"] != channel or item["round_opened"] != REVIEW_ROUND:
            raise MPresError(f"Finding {item['id']} has the wrong channel or round.")

    registry = _load_findings(root, slug, presentation_id)
    existing_ids = {str(item.get("id")) for item in registry["findings"] if isinstance(item, dict)}
    for item in submitted:
        if str(item["id"]) in existing_ids:
            raise MPresError(f"Finding ID is already used: {item['id']}")
        registry["findings"].append(item)
        existing_ids.add(str(item["id"]))
    _save_findings(root, slug, presentation_id, registry)

    channel_root = (
        task_path(root, slug)
        / "workers"
        / "specialist-reviewers"
        / presentation_id
        / REVIEW_ROUND
        / channel
    )
    canonical_report = channel_root / "report.md"
    canonical_findings = channel_root / "findings.yaml"
    if report_path != canonical_report.resolve():
        shutil.copy2(report_path, canonical_report)
    if findings_path != canonical_findings.resolve():
        shutil.copy2(findings_path, canonical_findings)
    presentation["status"] = "reviewing"
    round_state = presentation["rounds"][REVIEW_ROUND]
    round_state["status"] = "reviewing"
    round_state["channels"][channel] = {
        "submitted_utc": utc_now(),
        "report": relative_display(canonical_report, root),
        "findings": relative_display(canonical_findings, root),
        "finding_count": len(submitted),
    }
    save_state(root, slug, state)
    append_log(
        root,
        slug,
        actor=f"specialist-reviewer:{channel}",
        kind="review",
        presentation_id=presentation_id,
        round_name=REVIEW_ROUND,
        channel=channel,
        message=f"Submitted the {channel} report for the sole full review.",
        data={"finding_count": len(submitted)},
    )
    return round_state["channels"][channel]


def aggregate_round(
    root: Path,
    slug: str,
    presentation_id: str,
    *,
    round_name: str,
    aggregate_path: Path,
) -> dict[str, Any]:
    require_gate(root, slug)
    if round_name != REVIEW_ROUND:
        raise MPresError("Only one full review round exists.")
    state = load_state(root, slug)
    presentation = get_presentation(state, presentation_id)
    if presentation.get("status") not in {"review_requested", "reviewing"}:
        raise MPresError(f"Cannot aggregate in {presentation.get('status')!r} status.")
    channels = presentation["rounds"][REVIEW_ROUND].get("channels", {})
    missing = [channel for channel in REVIEW_CHANNELS if channel not in channels]
    if missing:
        raise MPresError("Cannot aggregate before all channels submit: " + ", ".join(missing))
    aggregate_path = aggregate_path.resolve()
    if not aggregate_path.is_file() or text_placeholders(aggregate_path):
        raise MPresError("Aggregate report is missing or incomplete.")
    if len(aggregate_path.read_text(encoding="utf-8").strip()) < 350:
        raise MPresError("Aggregate report is too short.")
    canonical = _review_root(root, slug, presentation_id) / REVIEW_ROUND / "aggregate.md"
    if aggregate_path != canonical.resolve():
        shutil.copy2(aggregate_path, canonical)
    registry = _load_findings(root, slug, presentation_id)
    response_path = (
        task_path(root, slug)
        / "workers"
        / "author-coordinator"
        / "drafts"
        / presentation_id
        / "source"
        / "AUTHOR-RESPONSES.yaml"
    )
    write_yaml_atomic(
        response_path,
        {
            "schema_version": 3,
            "presentation_id": presentation_id,
            "responding_to_round": REVIEW_ROUND,
            "responses": [
                {
                    "id": str(item.get("id")),
                    "disposition": "[[DISPOSITION]]",
                    "evidence": "[[EVIDENCE]]",
                    "location": "[[LOCATION]]",
                    "remaining_uncertainty": "[[UNCERTAINTY_OR_NONE]]",
                }
                for item in registry["findings"]
                if isinstance(item, dict)
            ],
        },
    )
    checklist_path = response_path.parent / "AUTHOR-MODIFICATION-CHECKLIST.yaml"
    template = (
        root / "templates" / "structured" / "AUTHOR-MODIFICATION-CHECKLIST.template.yaml"
    ).read_text(encoding="utf-8").replace("[[PRESENTATION_ID]]", presentation_id)
    checklist_path.write_text(template, encoding="utf-8", newline="\n")
    decision = {
        "schema_version": 3,
        "presentation_id": presentation_id,
        "round": REVIEW_ROUND,
        "completed_utc": utc_now(),
        "required_channels": list(REVIEW_CHANNELS),
        "finding_ids": [str(item.get("id")) for item in registry["findings"] if isinstance(item, dict)],
        "aggregate_report": relative_display(canonical, root),
        "author_response_template": relative_display(response_path, root),
        "modification_checklist": relative_display(checklist_path, root),
        "next_status": "author_revision",
        "post_revision_review": "none",
    }
    write_json_atomic(canonical.parent / "decision.json", decision)
    round_state = presentation["rounds"][REVIEW_ROUND]
    round_state["status"] = "completed"
    round_state["completed_utc"] = decision["completed_utc"]
    round_state["aggregate"] = decision["aggregate_report"]
    presentation["status"] = "author_revision"
    presentation["active_round"] = None
    save_state(root, slug, state)
    append_log(
        root,
        slug,
        actor="review-coordinator",
        kind="review",
        presentation_id=presentation_id,
        round_name=REVIEW_ROUND,
        message=(
            f"Completed the sole full review across five channels with {len(decision['finding_ids'])} "
            "finding(s); handed all findings to the author without scheduling re-review."
        ),
    )
    return decision


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
        raise MPresError("Author responses are expected only during author_revision.")
    if not response_file.is_file() or text_placeholders(response_file):
        raise MPresError("Structured author response file is missing or incomplete.")
    data = read_yaml(response_file)
    responses = data.get("responses") if isinstance(data, dict) else None
    if not isinstance(responses, list) or data.get("responding_to_round") != REVIEW_ROUND:
        raise MPresError("Response YAML must contain the full-round responses list.")
    registry = _load_findings(root, slug, presentation_id)
    by_id = {str(item.get("id")): item for item in registry["findings"] if isinstance(item, dict)}
    response_ids = [str(item.get("id")) for item in responses if isinstance(item, dict)]
    if len(response_ids) != len(set(response_ids)):
        raise MPresError("Author response file contains duplicate finding IDs.")
    if set(response_ids) != set(by_id):
        missing = sorted(set(by_id) - set(response_ids))
        extra = sorted(set(response_ids) - set(by_id))
        raise MPresError(f"Author responses must cover every finding exactly; missing={missing}, extra={extra}.")
    for response in responses:
        finding_id = str(response["id"])
        disposition = str(response.get("disposition") or "")
        if disposition not in AUTHOR_DISPOSITIONS:
            raise MPresError(f"Author response {finding_id} has invalid disposition.")
        for field in ("evidence", "location"):
            if len(str(response.get(field) or "").strip()) < 5:
                raise MPresError(f"Author response {finding_id} lacks substantive {field}.")
        by_id[finding_id]["author_response"] = {
            "recorded_utc": utc_now(),
            "disposition": disposition,
            "evidence": response["evidence"],
            "location": response["location"],
            "remaining_uncertainty": response.get("remaining_uncertainty"),
        }
    _save_findings(root, slug, presentation_id, registry)
    canonical = (
        task_path(root, slug)
        / "workers"
        / "author-coordinator"
        / "drafts"
        / presentation_id
        / "source"
        / "AUTHOR-RESPONSES.yaml"
    )
    if response_file.resolve() != canonical.resolve():
        shutil.copy2(response_file, canonical)
    append_log(
        root,
        slug,
        actor="author-coordinator",
        kind="review",
        presentation_id=presentation_id,
        message=f"Recorded author responses for all {len(response_ids)} finding(s).",
    )
    return {"presentation_id": presentation_id, "responses_recorded": response_ids}


def complete_author_revision(
    root: Path,
    slug: str,
    presentation_id: str,
    *,
    checklist_file: Path,
) -> dict[str, Any]:
    """Accept the author's completed revision without reviewer re-verification.

    This gate checks workflow completion and successful mechanical rebuild only. It deliberately
    does not decide whether any finding is resolved.
    """

    require_gate(root, slug)
    state = load_state(root, slug)
    presentation = get_presentation(state, presentation_id)
    if presentation.get("status") != "author_revision":
        raise MPresError("Author revision may be completed only from author_revision status.")
    registry = _load_findings(root, slug, presentation_id)
    missing_responses = [
        str(item.get("id"))
        for item in registry["findings"]
        if isinstance(item, dict) and not isinstance(item.get("author_response"), dict)
    ]
    if missing_responses:
        raise MPresError("Every finding needs an author response before release: " + ", ".join(missing_responses))
    if not checklist_file.is_file() or text_placeholders(checklist_file):
        raise MPresError("Author modification checklist is missing or incomplete.")
    checklist = read_yaml(checklist_file)
    steps = checklist.get("steps") if isinstance(checklist, dict) else None
    required_steps = {
        "reread_all_findings",
        "responded_to_every_finding",
        "revised_source",
        "reran_source_lint",
        "reran_asset_validation",
        "reran_html_layout_inspection",
        "rebuilt_pdf",
        "reran_pdf_inspection",
        "completed_self_check",
    }
    if not isinstance(steps, dict) or any(steps.get(key) is not True for key in required_steps):
        raise MPresError("Every author modification checklist step must be true.")
    if len(str(checklist.get("author_declaration") or "").strip()) < 20:
        raise MPresError("Author declaration is missing or too short.")
    release_assignment = check_assignment(root, slug, "release-coordinator", presentation_id)
    if not release_assignment.get("ready"):
        raise MPresError("The planner-written release-coordinator assignment is incomplete or unapproved.")
    source, build = source_and_build_paths(root, slug, presentation_id, "author")
    canonical_checklist = source / "AUTHOR-MODIFICATION-CHECKLIST.yaml"
    if checklist_file.resolve() != canonical_checklist.resolve():
        raise MPresError(
            "Complete the canonical AUTHOR-MODIFICATION-CHECKLIST.yaml inside the author source."
        )
    completed_utc = parse_utc(str(checklist.get("completed_utc") or ""))
    if completed_utc is None:
        raise MPresError("Author modification checklist must record a valid completed_utc timestamp.")
    revision_note = source / "AUTHOR-REVISION.md"
    if not revision_note.is_file() or text_placeholders(revision_note):
        raise MPresError("AUTHOR-REVISION.md is missing or incomplete.")
    if len(revision_note.read_text(encoding="utf-8").strip()) < 300:
        raise MPresError("AUTHOR-REVISION.md is too short to document the completed revision workflow.")
    report, evidence_paths = _validate_render(build, "author")
    report_time = parse_utc(report.get("started_and_finished_utc"))
    latest_input_mtime = max(
        canonical.stat().st_mtime
        for canonical in (
            source / "AUTHOR-RESPONSES.yaml",
            checklist_file,
            source / "SELF-CHECK.md",
            source / "AUTHOR-REVISION.md",
        )
        if canonical.exists()
    )
    if report_time is None or report_time.timestamp() + 1 < latest_input_mtime:
        raise MPresError("The successful author render predates the response/checklist; rerender after revision.")

    task = task_path(root, slug)
    ready_root = task / "workers" / "release-coordinator" / "release-ready" / presentation_id
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
        "schema_version": 3,
        "task_slug": slug,
        "presentation_id": presentation_id,
        "ready_utc": utc_now(),
        "source": relative_display(ready_root / "source", root),
        "author_responses": relative_display(ready_root / "AUTHOR-RESPONSES.yaml", root),
        "modification_checklist": relative_display(
            ready_root / "AUTHOR-MODIFICATION-CHECKLIST.yaml", root
        ),
        "finding_count": len(registry["findings"]),
        "finding_resolution_checked": False,
        "post_revision_reviewer_verification": False,
        "status": "release_ready",
    }
    write_json_atomic(ready_root / "release-readiness.json", approval)
    presentation["status"] = "release_ready"
    presentation["author_revision_completed_utc"] = approval["ready_utc"]
    save_state(root, slug, state)
    append_log(
        root,
        slug,
        actor="author-coordinator",
        kind="handoff",
        presentation_id=presentation_id,
        message=(
            "Completed the author-owned revision and handed the frozen source directly to "
            "mechanical release without reviewer confirmation or resolved-status checks."
        ),
        data={"release_ready": relative_display(ready_root / "release-readiness.json", root)},
    )
    return approval


def return_to_author(
    root: Path, slug: str, presentation_id: str, *, reason: str
) -> dict[str, Any]:
    require_gate(root, slug)
    if not reason.strip():
        raise MPresError("Returning a release-ready source requires a reason.")
    state = load_state(root, slug)
    presentation = get_presentation(state, presentation_id)
    if presentation.get("status") != "release_ready":
        raise MPresError("Only a release-ready presentation can return to the author.")
    ready = task_path(root, slug) / "workers" / "release-coordinator" / "release-ready" / presentation_id
    archive = ready.parent / f"{presentation_id}-returned-{utc_now().replace(':', '')}"
    if ready.exists():
        make_tree_writable(ready)
        ready.rename(archive)
    presentation["status"] = "author_revision"
    save_state(root, slug, state)
    record = {"utc": utc_now(), "reason": reason.strip(), "archive": relative_display(archive, root)}
    append_log(
        root,
        slug,
        actor="release-coordinator",
        kind="warning",
        presentation_id=presentation_id,
        message="Returned release-ready source because a semantic source change became necessary.",
        data=record,
    )
    return record


def finalize_release(root: Path, slug: str, presentation_id: str) -> dict[str, Any]:
    require_gate(root, slug)
    state = load_state(root, slug)
    presentation = get_presentation(state, presentation_id)
    if presentation.get("status") != "release_ready":
        raise MPresError("Finalization requires release_ready status.")
    task = task_path(root, slug)
    ready = task / "workers" / "release-coordinator" / "release-ready" / presentation_id
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
    if deliverable.exists():
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
        "pdf": relative_display(deliverable / pdf.name, root),
        "source": relative_display(deliverable / "source", root),
        "render_pipeline": RENDER_PIPELINE,
        "post_revision_reviewer_verification": False,
        "finding_resolution_checked": False,
    }
    write_json_atomic(deliverable / "release.json", release)
    presentation["status"] = "finalized"
    presentation["active"] = False
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
    elif state.get("stop_mode") == "pilot" and not state.get("pilot_pause_completed") and sequence == 1:
        state["phase"] = "awaiting_user_continuation"
    else:
        state["phase"] = "working"
        policy = read_yaml(task / "EXECUTION-POLICY.yaml") or {}
        capacity = max(1, int(((policy.get("authoring") or {}).get("max_parallel_presentations", 2)) or 2))
        active = sum(
            1 for item in state.get("presentations", [])
            if item.get("active") and item.get("status") != "finalized"
        )
        for item in state.get("presentations", []):
            if active >= capacity:
                break
            if not item.get("active") and item.get("status") != "finalized":
                item["active"] = True
                active += 1
    save_state(root, slug, state)
    append_log(
        root,
        slug,
        actor="release-coordinator",
        kind="delivery",
        presentation_id=presentation_id,
        message="Published the Marp PDF and source after author-owned revision and mechanical release.",
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
        root / "templates" / "context" / "FULL-REVIEW-CONTEXT.template.md"
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
