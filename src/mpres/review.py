from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from mpres.logs import append_log
from mpres.production import assignment_path, check_assignment
from mpres.rendering import RENDER_PIPELINE, source_and_build_paths
from mpres.state import REVIEW_CHANNELS, REVIEW_ROUNDS, get_presentation, load_state, save_state
from mpres.tasks import require_gate
from mpres.util import (
    MPresError,
    copy_source_tree,
    make_tree_read_only,
    make_tree_writable,
    read_json,
    read_yaml,
    relative_display,
    task_path,
    text_placeholders,
    utc_now,
    write_json_atomic,
    write_yaml_atomic,
)

ROUND_STATUS = {
    "initial": ("initial_review_requested", "initial_reviewing", "initial_changes"),
    "incremental": (
        "incremental_review_requested",
        "incremental_reviewing",
        "incremental_changes",
    ),
    "final": ("final_review_requested", "final_reviewing", "terminal_revision"),
}
EXPECTED_ROUND_BY_STATUS = {
    "authoring": "initial",
    "initial_changes": "incremental",
    "incremental_changes": "final",
    "terminal_revision": "terminal",
}
RESPONSE_ROUND_FOR_REQUEST = {
    "incremental": "initial",
    "final": "incremental",
    "terminal": "final",
}
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


def _review_root(root: Path, slug: str, presentation_id: str) -> Path:
    return task_path(root, slug) / "reviews" / presentation_id


def _request_root(root: Path, slug: str, presentation_id: str, round_name: str) -> Path:
    return _review_root(root, slug, presentation_id) / round_name / "request"


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


def _round_scope(round_name: str) -> str:
    return {
        "initial": "Full-deck independent review; new findings are allowed.",
        "incremental": (
            "Review prior findings, named changed areas, and regressions only. "
            "New finding IDs must be explicitly marked kind: regression."
        ),
        "final": "Full-deck independent review; new findings are allowed.",
    }[round_name]


def _validate_render_for_request(build: Path, stage: str) -> tuple[dict[str, Any], Path, Path, Path]:
    report_path = build / f"render-report-{stage}.json"
    report = read_json(report_path)
    if report.get("pipeline") != RENDER_PIPELINE or report.get("success") is not True:
        raise MPresError("A successful Marp PDF render report is required before review.")
    lint_path = build / f"source-lint-{stage}.json"
    asset_path = build / f"asset-validation-{stage}.json"
    pdf_path = build / f"pdf-inspection-{stage}.json"
    for path, label in (
        (lint_path, "source lint"),
        (asset_path, "asset validation"),
        (pdf_path, "PDF inspection"),
    ):
        if not path.is_file() or read_json(path).get("success") is not True:
            raise MPresError(f"Successful {label} is required before review.")
    snapshot = build / "source-snapshot"
    if not snapshot.is_dir():
        raise MPresError("Frozen render source snapshot is missing; rerender before review.")
    pdf = build / f"{report.get('presentation_id')}.pdf"
    if not pdf.is_file():
        raise MPresError("Rendered PDF is missing.")
    return report, report_path, pdf_path, asset_path


def _create_specialist_assignments(
    root: Path,
    slug: str,
    presentation_id: str,
    round_name: str,
    request_root: Path,
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
            / round_name
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
            "[[ROUND]]": round_name,
            "[[CHANNEL]]": channel,
            "[[REQUEST_PATH]]": relative_display(request_root, root),
            "[[TASK_MD_PATH]]": relative_display(task / "TASK.md", root),
            "[[REVIEW_PROTOCOL_PATH]]": relative_display(task / "REVIEW-PROTOCOL.md", root),
            "[[CHANNEL_GUIDANCE_PATH]]": relative_display(guidance, root),
            "[[ROUND_SCOPE]]": _round_scope(round_name),
            "[[REPORT_PATH]]": relative_display(channel_root / "report.md", root),
            "[[FINDINGS_PATH]]": relative_display(channel_root / "findings.yaml", root),
            "[[PRIOR_FINDINGS_CONTEXT]]": (
                "Read the shared findings registry and structured author response in the request."
                if round_name != "initial"
                else "There are no prior findings in the initial round."
            ),
            "[[AUDIENCE_CONTEXT]]": (
                "Apply the exact audience profile in TASK.md; prior exposure is not mastery."
            ),
            "[[PRESENTATION_SCOPE]]": (
                "Review this frozen Marp source and PDF only, within the assigned channel and round."
            ),
        }
        assignment = assignment_template
        for old, new in values.items():
            assignment = assignment.replace(old, new)
        (channel_root / "TASK-SPECIALIST-REVIEWER.md").write_text(
            assignment, encoding="utf-8", newline="\n"
        )
        report = report_template
        for old, new in {
            "[[CHANNEL]]": channel,
            "[[PRESENTATION_ID]]": presentation_id,
            "[[ROUND]]": round_name,
        }.items():
            report = report.replace(old, new)
        (channel_root / "report.md").write_text(report, encoding="utf-8", newline="\n")
        (channel_root / "findings.yaml").write_text(
            f"schema_version: 1\npresentation_id: {presentation_id}\nround: {round_name}\n"
            f"channel: {channel}\nfindings: []\n",
            encoding="utf-8",
            newline="\n",
        )
    aggregate = (
        root / "templates" / "review" / "review-aggregate.template.md"
    ).read_text(encoding="utf-8")
    aggregate = aggregate.replace("[[PRESENTATION_ID]]", presentation_id).replace(
        "[[ROUND]]", round_name
    )
    aggregate_path = _review_root(root, slug, presentation_id) / round_name / "aggregate.md"
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
    round_name = EXPECTED_ROUND_BY_STATUS.get(str(presentation.get("status")))
    if not round_name:
        raise MPresError(
            f"Presentation status {presentation.get('status')!r} cannot submit a review request."
        )
    for role in ("author-coordinator", "review-coordinator"):
        assignment = check_assignment(root, slug, role, presentation_id)
        if not assignment.get("ready"):
            raise MPresError(f"{role} assignment is incomplete: {assignment.get('placeholders', [])[:8]}")
    source, build = source_and_build_paths(root, slug, presentation_id, "author")
    report, render_report_path, pdf_inspection_path, asset_path = _validate_render_for_request(
        build, "author"
    )
    self_check = source / "SELF-CHECK.md"
    if not self_check.is_file() or text_placeholders(self_check):
        raise MPresError("Author SELF-CHECK.md is missing or incomplete.")
    if len(self_check.read_text(encoding="utf-8").strip()) < 300:
        raise MPresError("Author SELF-CHECK.md is too short.")
    if round_name != "initial":
        responding_to = RESPONSE_ROUND_FOR_REQUEST[round_name]
        response = source / f"AUTHOR-RESPONSES-{responding_to}.yaml"
        if not response.is_file() or text_placeholders(response):
            raise MPresError(f"{response.name} is required and must be complete.")
        registry = _load_findings(root, slug, presentation_id)
        missing = [
            str(item.get("id"))
            for item in registry["findings"]
            if isinstance(item, dict)
            and item.get("review_status") != "resolved"
            and not item.get("author_response")
        ]
        if missing:
            raise MPresError(
                "Structured author responses have not been recorded for: " + ", ".join(missing)
            )

    request_root = _request_root(root, slug, presentation_id, round_name)
    if request_root.exists():
        raise MPresError(f"The {round_name} request already exists: {request_root}")
    (request_root / "rendered").mkdir(parents=True, exist_ok=False)
    copy_source_tree(build / "source-snapshot", request_root / "source", read_only=True)
    shutil.copy2(self_check, request_root / "SELF-CHECK.md")
    for path in (
        render_report_path,
        build / "source-lint-author.json",
        asset_path,
        pdf_inspection_path,
    ):
        shutil.copy2(path, request_root / "rendered" / path.name)
    pdf = build / f"{presentation_id}.pdf"
    shutil.copy2(pdf, request_root / "rendered" / pdf.name)
    make_tree_read_only(request_root / "rendered")
    request = {
        "schema_version": 1,
        "task_slug": slug,
        "presentation_id": presentation_id,
        "round": round_name,
        "created_utc": utc_now(),
        "scope": "terminal closure only" if round_name == "terminal" else _round_scope(round_name),
        "changed_areas": changed_areas or [],
        "source_path": relative_display(request_root / "source", root),
        "self_check_path": relative_display(request_root / "SELF-CHECK.md", root),
        "render_report_path": relative_display(
            request_root / "rendered" / render_report_path.name, root
        ),
        "source_lint_path": relative_display(
            request_root / "rendered" / "source-lint-author.json", root
        ),
        "asset_validation_path": relative_display(
            request_root / "rendered" / asset_path.name, root
        ),
        "pdf_inspection_path": relative_display(
            request_root / "rendered" / pdf_inspection_path.name, root
        ),
        "pdf_path": relative_display(request_root / "rendered" / pdf.name, root),
        "render_transaction_id": report.get("render_transaction_id"),
        "status": "pending",
        "integrity_policy": "frozen snapshot; no hashes except TASK.md confirmation",
    }
    write_json_atomic(request_root / "request.json", request)
    if round_name == "terminal":
        presentation["status"] = "release_closure_requested"
        presentation["active_round"] = "terminal"
        release_work = (
            task_path(root, slug)
            / "workers"
            / "release-coordinator"
            / "closure"
            / presentation_id
        )
        release_work.mkdir(parents=True, exist_ok=True)
        registry = _load_findings(root, slug, presentation_id)
        unresolved_ids = [
            str(item.get("id"))
            for item in registry["findings"]
            if isinstance(item, dict) and item.get("review_status") != "resolved"
        ]
        write_yaml_atomic(
            release_work / "closures.yaml",
            {
                "schema_version": 1,
                "presentation_id": presentation_id,
                "closures": [
                    {"id": finding_id, "status": "resolved", "evidence": "[[CLOSURE_EVIDENCE]]"}
                    for finding_id in unresolved_ids
                ],
            },
        )
        closure = (
            root / "templates" / "context" / "TERMINAL-CLOSURE-CONTEXT.template.md"
        ).read_text(encoding="utf-8").replace("[[PRESENTATION_ID]]", presentation_id)
        (release_work / "CLOSURE.md").write_text(closure, encoding="utf-8", newline="\n")
        message = "Submitted the terminal release-closure request after final-round revision."
    else:
        _create_specialist_assignments(root, slug, presentation_id, round_name, request_root)
        presentation["status"] = ROUND_STATUS[round_name][0]
        presentation["active_round"] = round_name
        presentation.setdefault("rounds", {})[round_name] = {
            "status": "requested",
            "request": relative_display(request_root / "request.json", root),
            "channels": {},
            "requested_utc": request["created_utc"],
        }
        message = f"Submitted the mandatory {round_name} review request."
    save_state(root, slug, state)
    append_log(
        root,
        slug,
        actor="author-coordinator",
        kind="review",
        presentation_id=presentation_id,
        round_name=round_name,
        message=message,
        data={"request": relative_display(request_root / "request.json", root)},
    )
    return request


def _normalize_findings_file(path: Path) -> list[dict[str, Any]]:
    value = read_yaml(path)
    findings = value if isinstance(value, list) else value.get("findings") if isinstance(value, dict) else None
    if not isinstance(findings, list):
        raise MPresError(f"Structured findings must be a list in {path}.")
    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in findings:
        if not isinstance(raw, dict):
            raise MPresError("Every finding must be a mapping.")
        missing = REQUIRED_FINDING_FIELDS - set(raw)
        if missing:
            raise MPresError(f"Finding {raw.get('id')!r} is missing: {sorted(missing)}")
        finding_id = str(raw.get("id", "")).strip()
        if not finding_id or finding_id in seen:
            raise MPresError(f"Finding ID is empty or duplicated: {finding_id!r}")
        seen.add(finding_id)
        if not isinstance(raw.get("location"), dict):
            raise MPresError(f"Finding {finding_id} location must be a mapping.")
        item = dict(raw)
        item["id"] = finding_id
        item.setdefault("kind", "ordinary")
        item.setdefault("review_status", "open")
        item.setdefault("review_rationale", None)
        item.setdefault("author_response", None)
        item.setdefault("planner_ruling", None)
        normalized.append(item)
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
    if round_name not in REVIEW_ROUNDS or channel not in REVIEW_CHANNELS:
        raise MPresError("Invalid round or review channel.")
    state = load_state(root, slug)
    presentation = get_presentation(state, presentation_id)
    requested, reviewing, _ = ROUND_STATUS[round_name]
    if presentation.get("status") not in {requested, reviewing}:
        raise MPresError(f"Cannot submit {round_name}/{channel} in this status.")
    assignment = check_assignment(
        root,
        slug,
        "specialist-reviewer",
        presentation_id,
        round_name=round_name,
        channel=channel,
    )
    if not assignment.get("ready"):
        raise MPresError("Specialist reviewer assignment is incomplete.")
    report_path = report_path.resolve()
    findings_path = findings_path.resolve()
    if not report_path.is_file() or text_placeholders(report_path):
        raise MPresError("Specialist report is missing or incomplete.")
    if len(report_path.read_text(encoding="utf-8").strip()) < 250:
        raise MPresError("Specialist report is too short to document scope and evidence.")
    submitted = _normalize_findings_file(findings_path)
    for item in submitted:
        if item["channel"] != channel:
            raise MPresError(f"Finding {item['id']} belongs to {item['channel']}, not {channel}.")
        if round_name == "incremental" and item["round_opened"] == "incremental" and item.get("kind") != "regression":
            raise MPresError(
                f"New incremental finding {item['id']} must be marked kind: regression."
            )
    registry = _load_findings(root, slug, presentation_id)
    by_id = {str(item.get("id")): item for item in registry["findings"] if isinstance(item, dict)}
    if round_name in {"incremental", "final"}:
        required_existing = {
            finding_id
            for finding_id, item in by_id.items()
            if item.get("channel") == channel and item.get("review_status") != "resolved"
        }
        omitted = sorted(required_existing - {item["id"] for item in submitted})
        if omitted:
            raise MPresError(
                f"The {round_name}/{channel} report omitted unresolved findings: " + ", ".join(omitted)
            )
    for item in submitted:
        existing = by_id.get(item["id"])
        if existing:
            if existing.get("channel") != channel:
                raise MPresError(f"Finding ID {item['id']} is owned by another channel.")
            for field in ("issue", "learner_impact", "acceptance_criteria", "verification_method"):
                if str(item.get(field)).strip() != str(existing.get(field)).strip():
                    raise MPresError(f"Finding {item['id']} attempted to change stable field {field}.")
            existing["review_status"] = item.get("review_status", existing.get("review_status", "open"))
            existing["review_rationale"] = item.get("review_rationale")
            existing["last_reviewed_round"] = round_name
        else:
            if item.get("round_opened") != round_name:
                raise MPresError(f"New finding {item['id']} must use round_opened: {round_name}.")
            item["last_reviewed_round"] = round_name
            registry["findings"].append(item)
            by_id[item["id"]] = item
    _save_findings(root, slug, presentation_id, registry)
    channel_root = (
        task_path(root, slug)
        / "workers"
        / "specialist-reviewers"
        / presentation_id
        / round_name
        / channel
    )
    canonical_report = channel_root / "report.md"
    canonical_findings = channel_root / "findings.yaml"
    if report_path != canonical_report.resolve():
        shutil.copy2(report_path, canonical_report)
    if findings_path != canonical_findings.resolve():
        shutil.copy2(findings_path, canonical_findings)
    presentation["status"] = reviewing
    round_state = presentation.setdefault("rounds", {}).setdefault(round_name, {})
    round_state["status"] = "reviewing"
    round_state.setdefault("channels", {})[channel] = {
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
        round_name=round_name,
        channel=channel,
        message=f"Submitted {channel} report for the {round_name} round.",
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
    if round_name not in REVIEW_ROUNDS:
        raise MPresError("Invalid review round.")
    state = load_state(root, slug)
    presentation = get_presentation(state, presentation_id)
    requested, reviewing, next_status = ROUND_STATUS[round_name]
    if presentation.get("status") not in {requested, reviewing}:
        raise MPresError(f"Cannot aggregate {round_name} in this status.")
    round_state = presentation.setdefault("rounds", {}).setdefault(round_name, {})
    channels = round_state.get("channels", {})
    missing = [channel for channel in REVIEW_CHANNELS if channel not in channels]
    if missing:
        raise MPresError("All five channels are required before aggregation: " + ", ".join(missing))
    aggregate_path = aggregate_path.resolve()
    if not aggregate_path.is_file() or text_placeholders(aggregate_path):
        raise MPresError("Aggregate report is missing or incomplete.")
    if len(aggregate_path.read_text(encoding="utf-8").strip()) < 350:
        raise MPresError("Aggregate report is too short.")
    canonical = _review_root(root, slug, presentation_id) / round_name / "aggregate.md"
    if aggregate_path != canonical.resolve():
        shutil.copy2(aggregate_path, canonical)
    registry = _load_findings(root, slug, presentation_id)
    unresolved = [
        item
        for item in registry["findings"]
        if isinstance(item, dict) and item.get("review_status") != "resolved"
    ]
    author_source, _ = source_and_build_paths(root, slug, presentation_id, "author")
    response_path = author_source / f"AUTHOR-RESPONSES-{round_name}.yaml"
    write_yaml_atomic(
        response_path,
        {
            "schema_version": 1,
            "presentation_id": presentation_id,
            "responding_to_round": round_name,
            "responses": [
                {
                    "id": str(item.get("id")),
                    "disposition": "[[DISPOSITION]]",
                    "evidence": "[[EVIDENCE]]",
                    "location": "[[LOCATION]]",
                    "remaining_uncertainty": "[[UNCERTAINTY_OR_NONE]]",
                }
                for item in unresolved
            ],
        },
    )
    decision = {
        "schema_version": 1,
        "presentation_id": presentation_id,
        "round": round_name,
        "completed_utc": utc_now(),
        "required_channels": list(REVIEW_CHANNELS),
        "unresolved_findings": [str(item.get("id")) for item in unresolved],
        "aggregate_report": relative_display(canonical, root),
        "author_response_template": relative_display(response_path, root),
        "next_status": next_status,
    }
    write_json_atomic(canonical.parent / "decision.json", decision)
    round_state["status"] = "completed"
    round_state["completed_utc"] = decision["completed_utc"]
    round_state["aggregate"] = decision["aggregate_report"]
    presentation["status"] = next_status
    presentation["active_round"] = None
    save_state(root, slug, state)
    append_log(
        root,
        slug,
        actor="review-coordinator",
        kind="review",
        presentation_id=presentation_id,
        round_name=round_name,
        message=(
            f"Completed the mandatory {round_name} round; "
            f"{len(unresolved)} finding(s) remain unresolved."
        ),
        data={"next_status": next_status, "unresolved": decision["unresolved_findings"]},
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
    expected = {
        "initial_changes": "initial",
        "incremental_changes": "incremental",
        "terminal_revision": "final",
    }.get(str(presentation.get("status")))
    if expected is None:
        raise MPresError("Author responses are not expected in the current status.")
    if not response_file.is_file() or text_placeholders(response_file):
        raise MPresError("Structured author response file is missing or incomplete.")
    value = read_yaml(response_file)
    responses = value.get("responses") if isinstance(value, dict) else None
    if not isinstance(responses, list) or value.get("responding_to_round") != expected:
        raise MPresError(f"Response YAML must address round {expected}.")
    registry = _load_findings(root, slug, presentation_id)
    by_id = {str(item.get("id")): item for item in registry["findings"] if isinstance(item, dict)}
    required_ids = {
        finding_id
        for finding_id, item in by_id.items()
        if item.get("review_status") != "resolved"
    }
    response_ids = [str(item.get("id")) for item in responses if isinstance(item, dict)]
    if len(response_ids) != len(set(response_ids)):
        raise MPresError("Author response file contains duplicate IDs.")
    missing = sorted(required_ids - set(response_ids))
    if missing:
        raise MPresError("Author response omits unresolved findings: " + ", ".join(missing))
    updated: list[str] = []
    for response in responses:
        if not isinstance(response, dict):
            raise MPresError("Every author response must be a mapping.")
        finding_id = str(response.get("id", ""))
        finding = by_id.get(finding_id)
        if finding is None:
            raise MPresError(f"Author response refers to unknown finding: {finding_id}")
        for field in ("disposition", "evidence", "location"):
            if not str(response.get(field, "")).strip():
                raise MPresError(f"Author response {finding_id} lacks {field}.")
        finding["author_response"] = {
            "recorded_utc": utc_now(),
            "disposition": response["disposition"],
            "evidence": response["evidence"],
            "location": response["location"],
            "remaining_uncertainty": response.get("remaining_uncertainty"),
        }
        if finding.get("review_status") == "open":
            finding["review_status"] = "addressed"
        updated.append(finding_id)
    _save_findings(root, slug, presentation_id, registry)
    append_log(
        root,
        slug,
        actor="author-coordinator",
        kind="review",
        presentation_id=presentation_id,
        round_name=expected,
        message=f"Recorded structured responses for {len(updated)} finding(s).",
        data={"finding_ids": updated},
    )
    return {"presentation_id": presentation_id, "updated": updated}


def approve_release_closure(
    root: Path,
    slug: str,
    presentation_id: str,
    *,
    closure_file: Path,
    closure_report: Path,
) -> dict[str, Any]:
    require_gate(root, slug)
    state = load_state(root, slug)
    presentation = get_presentation(state, presentation_id)
    if presentation.get("status") != "release_closure_requested":
        raise MPresError("Release closure requires release_closure_requested status.")
    if not closure_file.is_file() or text_placeholders(closure_file):
        raise MPresError("Closure YAML is missing or incomplete.")
    value = read_yaml(closure_file)
    closures = value.get("closures") if isinstance(value, dict) else None
    if not isinstance(closures, list):
        raise MPresError("Closure YAML must contain a closures list.")
    registry = _load_findings(root, slug, presentation_id)
    by_id = {str(item.get("id")): item for item in registry["findings"] if isinstance(item, dict)}
    closure_ids = [str(item.get("id")) for item in closures if isinstance(item, dict)]
    unresolved_ids = {
        finding_id
        for finding_id, item in by_id.items()
        if item.get("review_status") != "resolved"
    }
    if set(closure_ids) != unresolved_ids:
        missing = sorted(unresolved_ids - set(closure_ids))
        unknown = sorted(set(closure_ids) - unresolved_ids)
        raise MPresError(
            "Release closure IDs must exactly match unresolved findings. "
            f"Missing={missing}; unexpected={unknown}."
        )
    for closure in closures:
        finding_id = str(closure.get("id"))
        finding = by_id[finding_id]
        if str(closure.get("status")) != "resolved" or not str(closure.get("evidence", "")).strip():
            raise MPresError(f"Closure {finding_id} must declare resolved with evidence.")
        if not finding.get("author_response"):
            raise MPresError(f"Finding {finding_id} has no author response.")
        finding["review_status"] = "resolved"
        finding["review_rationale"] = str(closure["evidence"])
        finding["closed_utc"] = utc_now()
    if not closure_report.is_file() or text_placeholders(closure_report):
        raise MPresError("Closure report is missing or incomplete.")
    if len(closure_report.read_text(encoding="utf-8").strip()) < 250:
        raise MPresError("Closure report is too short.")
    _save_findings(root, slug, presentation_id, registry)
    request_root = _request_root(root, slug, presentation_id, "terminal")
    request = read_json(request_root / "request.json")
    approved_root = (
        task_path(root, slug)
        / "workers"
        / "release-coordinator"
        / "approved"
        / presentation_id
    )
    if approved_root.exists():
        make_tree_writable(approved_root)
    approved_root.mkdir(parents=True, exist_ok=True)
    copy_source_tree(root / request["source_path"], approved_root / "source", read_only=True)
    shutil.copy2(closure_report, approved_root / "CLOSURE.md")
    shutil.copy2(closure_file, approved_root / "closures.yaml")
    approval = {
        "schema_version": 1,
        "task_slug": slug,
        "presentation_id": presentation_id,
        "approved_utc": utc_now(),
        "source": relative_display(approved_root / "source", root),
        "closure_report": relative_display(approved_root / "CLOSURE.md", root),
        "terminal_request": relative_display(request_root / "request.json", root),
        "status": "release_approved",
        "integrity_policy": "frozen snapshot; no hashes except TASK.md confirmation",
    }
    write_json_atomic(approved_root / "approval.json", approval)
    presentation["status"] = "release_approved"
    presentation["active_round"] = None
    save_state(root, slug, state)
    append_log(
        root,
        slug,
        actor="release-coordinator",
        kind="review",
        presentation_id=presentation_id,
        round_name="terminal",
        message="Closed all final findings and approved the frozen Marp source for release.",
    )
    return approval


def revoke_release_approval(
    root: Path, slug: str, presentation_id: str, *, reason: str
) -> dict[str, Any]:
    require_gate(root, slug)
    state = load_state(root, slug)
    presentation = get_presentation(state, presentation_id)
    if presentation.get("status") != "release_approved":
        raise MPresError("Only release-approved presentations can be revoked.")
    approved = (
        task_path(root, slug)
        / "workers"
        / "release-coordinator"
        / "approved"
        / presentation_id
    )
    archive = approved.parent / f"{presentation_id}-revoked-{utc_now().replace(':', '')}"
    if approved.exists():
        make_tree_writable(approved)
        approved.rename(archive)
    presentation["status"] = "terminal_revision"
    save_state(root, slug, state)
    record = {"utc": utc_now(), "reason": reason, "archive": relative_display(archive, root)}
    append_log(
        root,
        slug,
        actor="release-coordinator",
        kind="warning",
        presentation_id=presentation_id,
        message="Revoked release approval because a semantic source change became necessary.",
        data=record,
    )
    return record


def finalize_release(root: Path, slug: str, presentation_id: str) -> dict[str, Any]:
    require_gate(root, slug)
    state = load_state(root, slug)
    presentation = get_presentation(state, presentation_id)
    if presentation.get("status") != "release_approved":
        raise MPresError("Finalization requires release_approved status.")
    task = task_path(root, slug)
    approved = task / "workers" / "release-coordinator" / "approved" / presentation_id
    report = read_json(approved / "build" / "render-report-release.json")
    if report.get("success") is not True or report.get("pipeline") != RENDER_PIPELINE:
        raise MPresError("A successful release-stage Marp render is required.")
    pdf_inspection = read_json(approved / "build" / "pdf-inspection-release.json")
    if pdf_inspection.get("success") is not True:
        raise MPresError("Release PDF inspection is missing or unsuccessful.")
    pdf = approved / "build" / f"{presentation_id}.pdf"
    if not pdf.is_file():
        raise MPresError("Approved PDF is missing.")
    deliverable = task / "deliverables" / presentation_id
    if deliverable.exists():
        make_tree_writable(deliverable)
        shutil.rmtree(deliverable)
    deliverable.mkdir(parents=True, exist_ok=True)
    shutil.copy2(pdf, deliverable / pdf.name)
    copy_source_tree(approved / "source", deliverable / "source")
    for name in ("approval.json", "CLOSURE.md", "closures.yaml"):
        path = approved / name
        if path.is_file():
            shutil.copy2(path, deliverable / name)
    shutil.copy2(approved / "build" / "render-report-release.json", deliverable / "render-report.json")
    shutil.copy2(approved / "build" / "pdf-inspection-release.json", deliverable / "pdf-inspection.json")
    registry = _findings_path(root, slug, presentation_id)
    if registry.is_file():
        shutil.copy2(registry, deliverable / "findings.yaml")
    sequence = int(state.get("last_delivery_sequence", 0)) + 1
    release = {
        "schema_version": 1,
        "task_slug": slug,
        "presentation_id": presentation_id,
        "title": presentation.get("title"),
        "finalized_utc": utc_now(),
        "delivery_sequence": sequence,
        "pdf": relative_display(deliverable / pdf.name, root),
        "source": relative_display(deliverable / "source", root),
        "closure": relative_display(deliverable / "CLOSURE.md", root),
        "render_pipeline": RENDER_PIPELINE,
        "integrity_policy": "no hashes except TASK.md confirmation",
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
        if state.get("stop_mode") == "all" or (
            state.get("stop_mode") == "pilot" and state.get("pilot_pause_completed")
        ):
            policy = read_yaml(task / "EXECUTION-POLICY.yaml") or {}
            authoring = policy.get("authoring", {}) if isinstance(policy, dict) else {}
            capacity = max(1, int(authoring.get("max_parallel_presentations", 2) or 2))
            active = sum(
                1
                for item in state.get("presentations", [])
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
        message="Published the reviewed Marp PDF and source deliverables.",
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
    if round_name not in REVIEW_ROUNDS or channel not in REVIEW_CHANNELS:
        raise MPresError("Context bundles require a valid specialist round and channel.")
    task = task_path(root, slug)
    request = _request_root(root, slug, presentation_id, round_name)
    if not (request / "request.json").is_file():
        raise MPresError("Review request does not exist.")
    bundle = task / "review-cache" / presentation_id / round_name / channel
    if bundle.exists():
        shutil.rmtree(bundle)
    bundle.mkdir(parents=True, exist_ok=True)
    context_name = (
        "INCREMENTAL-REVIEW-CONTEXT.template.md"
        if round_name == "incremental"
        else "FULL-REVIEW-CONTEXT.template.md"
    )
    context = (root / "templates" / "context" / context_name).read_text(encoding="utf-8")
    for old, new in {
        "[[PRESENTATION_ID]]": presentation_id,
        "[[ROUND]]": round_name,
        "[[CHANNEL]]": channel,
    }.items():
        context = context.replace(old, new)
    (bundle / "CONTEXT.md").write_text(context, encoding="utf-8", newline="\n")
    paths = [
        task / "TASK.md",
        task / "EXECUTION-POLICY.yaml",
        task / "REVIEW-PROFILE.yaml",
        task / "REVIEW-PROTOCOL.md",
        task / "MARP-AUTHORING-STANDARD.md",
        assignment_path(
            root,
            slug,
            "specialist-reviewer",
            presentation_id,
            round_name=round_name,
            channel=channel,
        ),
        request / "request.json",
        _findings_path(root, slug, presentation_id),
    ]
    manifest = {
        "schema_version": 1,
        "created_utc": utc_now(),
        "presentation_id": presentation_id,
        "round": round_name,
        "channel": channel,
        "files": [relative_display(path, root) for path in paths if path.exists()],
        "request_source": relative_display(request / "source", root),
        "request_pdf": relative_display(request / "rendered" / f"{presentation_id}.pdf", root),
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
