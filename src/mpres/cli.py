from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from mpres.assets import run_python_asset, validate_assets
from mpres.assignments import (
    approve_assignment,
    assignment_contract_status,
    revoke_assignment,
)
from mpres.audit import audit_task
from mpres.checkpoints import checkpoint_status, save_checkpoint
from mpres.doctor import doctor_report
from mpres.geogebra import validate_task_geogebra
from mpres.html_layout import inspect_task_html_layout
from mpres.logs import append_log
from mpres.marp_source import lint_task_source
from mpres.pdf_inspection import inspect_task_pdf
from mpres.policy import confirm_policy_change, policy_audit, propose_policy_change
from mpres.production import (
    ROLES,
    activate_presentations,
    assemble_units,
    check_assignment,
    initialize_production,
)
from mpres.references import ingest_reference
from mpres.rendering import render_presentation, source_and_build_paths
from mpres.review import (
    aggregate_round,
    build_context_bundle,
    complete_author_revision,
    finalize_release,
    record_author_responses,
    request_review,
    return_to_author,
    review_status,
    submit_channel_review,
)
from mpres.stages import (
    accept_stage,
    activate_stage,
    reopen_stage,
    stage_status,
    submit_stage,
)
from mpres.state import REVIEW_CHANNELS, REVIEW_ROUNDS
from mpres.supervision import supervise_once, watch_supervision
from mpres.tasks import (
    confirm_task,
    continue_task,
    create_task,
    gate_status,
    list_tasks,
    present_task,
    restore_confirmed_task,
    task_status,
)
from mpres.threads import (
    assign_thread,
    list_threads,
    register_thread,
    release_thread,
    validate_handoff,
)
from mpres.tokens import (
    collect_tokens,
    collector_status,
    import_session,
    initialize_collector,
    save_token_snapshot,
    token_report,
)
from mpres.util import MPresError, find_repo_root


def _json(value: Any) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True))


def _doctor_human(report: dict[str, Any]) -> None:
    print(f"Project root: {report['root']}")
    print(f"Platform: {report['platform']}")
    print(f"Python: {report['python']['version']} ({report['python']['executable']})")
    print("\nExternal tools:")
    for name, item in report["binaries"].items():
        mark = "OK" if item.get("found") else "MISSING"
        version = f" — {item['version']}" if item.get("version") else ""
        print(f"  [{mark:7}] {name}: {item.get('path') or '-'}{version}")
    marp = report["marp"]
    print(f"\nMarp CLI: {'OK' if marp.get('found') else 'MISSING'} — {marp.get('version') or '-'}")
    probe = report["pdf_probe"]
    probe_label = "PASS" if probe.get("ok") else "FAIL" if probe.get("ok") is False else "SKIPPED"
    print(f"Marp PDF probe: {probe_label}")
    browser = report.get("html_layout_browser", {})
    browser_label = "PASS" if browser.get("available") else "FAIL"
    print(
        "Temporary HTML layout browser: "
        f"{browser_label} — {browser.get('executable') or '-'}"
    )
    if report["warnings"]:
        print("\nWarnings:")
        for warning in report["warnings"]:
            print(f"  - {warning}")
    print("\nResult:", "READY" if report["ok"] else "BLOCKED")
    if report["blockers"]:
        print("Blockers:", ", ".join(report["blockers"]))


def _assignment_coordinates(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--role", choices=sorted(ROLES), required=True)
    parser.add_argument("--presentation", required=True)
    parser.add_argument("--unit")
    parser.add_argument("--round", choices=REVIEW_ROUNDS)
    parser.add_argument("--channel", choices=REVIEW_CHANNELS)


def _checkpoint_coordinates(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--role",
        choices=[
            "author-coordinator",
            "lesson-author",
            "review-coordinator",
            "release-coordinator",
        ],
        required=True,
    )
    parser.add_argument("--presentation", required=True)
    parser.add_argument("--unit")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="mpres",
        description=(
            "Parallel Marp-to-PDF presentation orchestration with staged authors, one "
            "five-channel full-deck review, and author-owned post-review revision."
        ),
    )
    parser.add_argument("--root", type=Path)
    commands = parser.add_subparsers(dest="command", required=True)

    doctor = commands.add_parser("doctor")
    doctor.add_argument("--json", action="store_true")
    doctor.add_argument("--strict", action="store_true")
    doctor.add_argument("--skip-pdf-probe", action="store_true")

    task = commands.add_parser("task")
    task_sub = task.add_subparsers(dest="task_command", required=True)
    init = task_sub.add_parser("init")
    init.add_argument("--title", required=True)
    init.add_argument("--slug")
    init.add_argument("--kind", choices=["course", "report"], required=True)
    init.add_argument("--stop-mode", choices=["pilot", "each", "all"], required=True)
    init.add_argument("--sessions", type=int)
    init.add_argument("--minutes", type=int)
    task_sub.add_parser("list").add_argument("--json", action="store_true")
    for name in ("present", "confirm", "gate", "status", "continue", "restore-confirmed"):
        sub = task_sub.add_parser(name)
        sub.add_argument("slug")

    policy = commands.add_parser("policy")
    policy_sub = policy.add_subparsers(dest="policy_command", required=True)
    paudit = policy_sub.add_parser("audit")
    paudit.add_argument("slug")
    ppropose = policy_sub.add_parser("propose")
    ppropose.add_argument("slug")
    ppropose.add_argument("--id", required=True)
    ppropose.add_argument("--field", action="append", required=True)
    ppropose.add_argument("--reason", required=True)
    pconfirm = policy_sub.add_parser("confirm")
    pconfirm.add_argument("slug")
    pconfirm.add_argument("--id", required=True)

    assignment = commands.add_parser("assignment")
    assignment_sub = assignment.add_subparsers(dest="assignment_command", required=True)
    for name in ("status", "approve", "revoke"):
        sub = assignment_sub.add_parser(name)
        sub.add_argument("slug")
        sub.add_argument("path", type=Path)
        if name == "approve":
            sub.add_argument("--notes")
        if name == "revoke":
            sub.add_argument("--reason", required=True)

    production = commands.add_parser("production")
    production_sub = production.add_subparsers(dest="production_command", required=True)
    pinit = production_sub.add_parser("init")
    pinit.add_argument("slug")
    pinit.add_argument("--presentation", action="append", required=True)
    pinit.add_argument("--unit", action="append", required=True)
    activate = production_sub.add_parser("activate")
    activate.add_argument("slug")
    activate.add_argument("--presentation", action="append", required=True)

    author = commands.add_parser("author")
    author_sub = author.add_subparsers(dest="author_command", required=True)
    assemble = author_sub.add_parser("assemble")
    assemble.add_argument("slug")
    assemble.add_argument("--presentation", required=True)

    stage = commands.add_parser("stage")
    stage_sub = stage.add_subparsers(dest="stage_command", required=True)
    for name in ("status", "activate", "submit", "accept", "reopen"):
        sub = stage_sub.add_parser(name)
        sub.add_argument("slug")
        sub.add_argument("--presentation", required=True)
        sub.add_argument("--unit", required=True)
        if name != "status":
            sub.add_argument("--stage", required=True)
        if name == "reopen":
            sub.add_argument("--reason", required=True)

    role = commands.add_parser("role")
    role_sub = role.add_subparsers(dest="role_command", required=True)
    assignment_check = role_sub.add_parser("assignment-check")
    assignment_check.add_argument("slug")
    _assignment_coordinates(assignment_check)
    heartbeat = role_sub.add_parser("heartbeat")
    heartbeat.add_argument("slug")
    heartbeat.add_argument("--actor", required=True)
    heartbeat.add_argument("--presentation")
    heartbeat.add_argument("--unit")
    heartbeat.add_argument("--round")
    heartbeat.add_argument("--channel")
    heartbeat.add_argument("--status", required=True)
    heartbeat.add_argument("--message", required=True)

    checkpoint = commands.add_parser("checkpoint")
    checkpoint_sub = checkpoint.add_subparsers(dest="checkpoint_command", required=True)
    cps = checkpoint_sub.add_parser("save")
    cps.add_argument("slug")
    _checkpoint_coordinates(cps)
    cps.add_argument("--completed", action="append", default=[])
    cps.add_argument("--decision", action="append", default=[])
    cps.add_argument("--open-issue", action="append", default=[])
    cps.add_argument("--next-action", required=True)
    cps.add_argument("--durable-path", action="append", default=[])
    cps.add_argument("--last-successful-build")
    cpg = checkpoint_sub.add_parser("status")
    cpg.add_argument("slug")
    _checkpoint_coordinates(cpg)

    thread = commands.add_parser("thread")
    thread_sub = thread.add_subparsers(dest="thread_command", required=True)
    thread_list = thread_sub.add_parser("list")
    thread_list.add_argument("slug")
    thread_register = thread_sub.add_parser("register")
    thread_register.add_argument("slug")
    thread_register.add_argument("--handle", required=True)
    thread_register.add_argument("--runtime-name", required=True)
    thread_register.add_argument("--role", required=True)
    thread_assign = thread_sub.add_parser("assign")
    thread_assign.add_argument("slug")
    thread_assign.add_argument("--handle", required=True)
    thread_assign.add_argument("--assignment-id", required=True)
    thread_assign.add_argument("--role", required=True)
    thread_assign.add_argument("--presentation", required=True)
    thread_assign.add_argument("--unit")
    thread_assign.add_argument("--round")
    thread_assign.add_argument("--channel")
    thread_handoff = thread_sub.add_parser("handoff")
    thread_handoff.add_argument("slug")
    thread_handoff.add_argument("--handle", required=True)
    thread_handoff.add_argument("--durable-path", action="append", default=[])
    thread_handoff.add_argument("--summary", required=True)
    thread_release = thread_sub.add_parser("release")
    thread_release.add_argument("slug")
    thread_release.add_argument("--handle", required=True)
    thread_release.add_argument("--runtime-operation", required=True)
    thread_release.add_argument("--capacity-released", action="store_true")
    thread_release.add_argument("--notes")

    log = commands.add_parser("log")
    log_sub = log.add_subparsers(dest="log_command", required=True)
    add = log_sub.add_parser("add")
    add.add_argument("slug")
    add.add_argument("--actor", required=True)
    add.add_argument(
        "--kind",
        choices=[
            "decision",
            "progress",
            "check",
            "warning",
            "error",
            "restart",
            "review",
            "render",
            "handoff",
            "delivery",
            "checkpoint",
        ],
        required=True,
    )
    add.add_argument("--presentation")
    add.add_argument("--unit")
    add.add_argument("--round")
    add.add_argument("--channel")
    add.add_argument("--message", required=True)
    add.add_argument("--data-json")

    reference = commands.add_parser("reference")
    reference_sub = reference.add_subparsers(dest="reference_command", required=True)
    ingest = reference_sub.add_parser("ingest")
    ingest.add_argument("slug")
    ingest.add_argument("source")
    ingest.add_argument("--name")
    ingest.add_argument("--ocr", choices=["auto", "always", "never"], default="auto")
    ingest.add_argument("--max-pages", type=int, default=250)

    source = commands.add_parser("source")
    source_sub = source.add_subparsers(dest="source_command", required=True)
    lint = source_sub.add_parser("lint")
    lint.add_argument("slug")
    lint.add_argument("--presentation", required=True)
    lint.add_argument("--stage", choices=["author", "release"], default="author")

    assets = commands.add_parser("assets")
    assets_sub = assets.add_subparsers(dest="assets_command", required=True)
    aval = assets_sub.add_parser("validate")
    aval.add_argument("slug")
    aval.add_argument("--presentation", required=True)
    aval.add_argument("--stage", choices=["author", "release"], default="author")
    agen = assets_sub.add_parser("generate")
    agen.add_argument("slug")
    agen.add_argument("--presentation", required=True)
    agen.add_argument("--asset", required=True)
    agen.add_argument("--timeout", type=int, default=600)

    geogebra = commands.add_parser("geogebra")
    geogebra_sub = geogebra.add_subparsers(dest="geogebra_command", required=True)
    gvalidate = geogebra_sub.add_parser("validate")
    gvalidate.add_argument("slug")
    gvalidate.add_argument("--presentation", required=True)
    gvalidate.add_argument("--stage", choices=["author", "release"], default="author")

    render = commands.add_parser("render")
    render.add_argument("slug")
    render.add_argument("--presentation", required=True)
    render.add_argument("--stage", choices=["author", "release"], required=True)
    render.add_argument("--source", type=Path)
    render.add_argument("--timeout", type=int, default=1800)

    inspect_parser = commands.add_parser("inspect")
    inspect_sub = inspect_parser.add_subparsers(dest="inspect_command", required=True)
    ipdf = inspect_sub.add_parser("pdf")
    ipdf.add_argument("slug")
    ipdf.add_argument("--presentation", required=True)
    ipdf.add_argument("--stage", choices=["author", "release"], required=True)
    ihtml = inspect_sub.add_parser("html-layout")
    ihtml.add_argument("slug")
    ihtml.add_argument("--presentation", required=True)
    ihtml.add_argument("--stage", choices=["author", "release"], required=True)
    ihtml.add_argument("--timeout", type=int, default=1800)

    review = commands.add_parser("review")
    review_sub = review.add_subparsers(dest="review_command", required=True)
    rr = review_sub.add_parser("request")
    rr.add_argument("slug")
    rr.add_argument("--presentation", required=True)
    rr.add_argument("--changed-area", action="append", default=[])
    rs = review_sub.add_parser("submit-channel")
    rs.add_argument("slug")
    rs.add_argument("--presentation", required=True)
    rs.add_argument("--round", choices=REVIEW_ROUNDS, default="full")
    rs.add_argument("--channel", choices=REVIEW_CHANNELS, required=True)
    rs.add_argument("--report", type=Path, required=True)
    rs.add_argument("--findings", type=Path, required=True)
    ra = review_sub.add_parser("aggregate")
    ra.add_argument("slug")
    ra.add_argument("--presentation", required=True)
    ra.add_argument("--round", choices=REVIEW_ROUNDS, default="full")
    ra.add_argument("--report", type=Path, required=True)
    respond = review_sub.add_parser("respond")
    respond.add_argument("slug")
    respond.add_argument("--presentation", required=True)
    respond.add_argument("--file", type=Path, required=True)
    complete = review_sub.add_parser("complete-revision")
    complete.add_argument("slug")
    complete.add_argument("--presentation", required=True)
    complete.add_argument("--checklist", type=Path, required=True)
    back = review_sub.add_parser("return-to-author")
    back.add_argument("slug")
    back.add_argument("--presentation", required=True)
    back.add_argument("--reason", required=True)
    finalize = review_sub.add_parser("finalize")
    finalize.add_argument("slug")
    finalize.add_argument("--presentation", required=True)
    bundle = review_sub.add_parser("bundle")
    bundle.add_argument("slug")
    bundle.add_argument("--presentation", required=True)
    bundle.add_argument("--round", choices=REVIEW_ROUNDS, default="full")
    bundle.add_argument("--channel", choices=REVIEW_CHANNELS, required=True)
    status = review_sub.add_parser("status")
    status.add_argument("slug")
    status.add_argument("--presentation")

    supervise = commands.add_parser("supervise")
    supervise.add_argument("slug")
    supervise.add_argument("--scope", choices=["planner", "author", "review"], default="planner")
    supervise.add_argument("--presentation")
    supervise.add_argument("--record", action="store_true")
    supervise.add_argument("--watch", action="store_true")
    supervise.add_argument("--interval", type=int)
    supervise.add_argument("--iterations", type=int)

    token = commands.add_parser("token")
    token_sub = token.add_subparsers(dest="token_command", required=True)
    token_import = token_sub.add_parser("import-session")
    token_import.add_argument("slug")
    token_import.add_argument("source", type=Path)
    token_import.add_argument("--presentation")
    token_import.add_argument("--role", required=True)
    token_import.add_argument("--unit")
    token_import.add_argument("--round")
    token_import.add_argument("--channel")
    token_import.add_argument("--thread-id")
    collector_init = token_sub.add_parser("collector-init")
    collector_init.add_argument("slug")
    collector_init.add_argument("--sessions-root", type=Path, required=True)
    collector_init.add_argument("--root-thread-id", required=True)
    collector_init.add_argument("--task-started-at")
    collector_init.add_argument("--session-date-floor")
    token_sub.add_parser("collector-collect").add_argument("slug")
    token_sub.add_parser("collector-status").add_argument("slug")
    for name in ("snapshot", "report"):
        sub = token_sub.add_parser(name)
        sub.add_argument("slug")
        sub.add_argument(
            "--group-by",
            choices=[
                "presentation_id",
                "role",
                "unit_id",
                "round",
                "channel",
                "model",
                "thread_id",
            ],
            default="presentation_id",
        )

    audit = commands.add_parser("audit")
    audit.add_argument("slug")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        root = args.root.expanduser().resolve() if args.root else find_repo_root()

        if args.command == "doctor":
            result = doctor_report(root, run_pdf_probe=not args.skip_pdf_probe)
            _json(result) if args.json else _doctor_human(result)
            return 1 if args.strict and not result["ok"] else 0

        if args.command == "task":
            if args.task_command == "init":
                slug, path = create_task(
                    root=root,
                    title=args.title,
                    slug=args.slug,
                    kind=args.kind,
                    stop_mode=args.stop_mode,
                    sessions=args.sessions,
                    minutes=args.minutes,
                )
                _json({"task_slug": slug, "task_path": str(path)})
            elif args.task_command == "list":
                _json(list_tasks(root))
            elif args.task_command == "present":
                _json(present_task(root, args.slug))
            elif args.task_command == "confirm":
                _json(confirm_task(root, args.slug))
            elif args.task_command == "gate":
                ok, message, state = gate_status(root, args.slug)
                _json({"ok": ok, "message": message, "phase": state.get("phase")})
                return 0 if ok else 1
            elif args.task_command == "status":
                _json(task_status(root, args.slug))
            elif args.task_command == "continue":
                _json(continue_task(root, args.slug))
            else:
                _json(restore_confirmed_task(root, args.slug))
            return 0

        if args.command == "policy":
            if args.policy_command == "audit":
                result = policy_audit(root, args.slug)
                _json(result)
                return 0 if result.get("ok") else 1
            if args.policy_command == "confirm":
                _json(confirm_policy_change(root, args.slug, request_id=args.id))
                return 0
            _json(
                propose_policy_change(
                    root,
                    args.slug,
                    request_id=args.id,
                    fields=args.field,
                    reason=args.reason,
                )
            )
            return 0

        if args.command == "assignment":
            path = args.path.expanduser().resolve()
            if args.assignment_command == "status":
                _json(assignment_contract_status(path))
            elif args.assignment_command == "approve":
                _json(approve_assignment(root, args.slug, path, notes=args.notes))
            else:
                _json(revoke_assignment(root, args.slug, path, reason=args.reason))
            return 0

        if args.command == "production":
            if args.production_command == "init":
                _json(initialize_production(root, args.slug, args.presentation, args.unit))
            else:
                _json(activate_presentations(root, args.slug, args.presentation))
            return 0

        if args.command == "author":
            _json(assemble_units(root, args.slug, args.presentation))
            return 0

        if args.command == "stage":
            if args.stage_command == "status":
                result = stage_status(root, args.slug, args.presentation, args.unit)
            elif args.stage_command == "activate":
                result = activate_stage(
                    root, args.slug, args.presentation, args.unit, args.stage
                )
            elif args.stage_command == "submit":
                result = submit_stage(
                    root, args.slug, args.presentation, args.unit, args.stage
                )
            elif args.stage_command == "accept":
                result = accept_stage(
                    root, args.slug, args.presentation, args.unit, args.stage
                )
            else:
                result = reopen_stage(
                    root,
                    args.slug,
                    args.presentation,
                    args.unit,
                    args.stage,
                    reason=args.reason,
                )
            _json(result)
            return 0

        if args.command == "role":
            if args.role_command == "assignment-check":
                result = check_assignment(
                    root,
                    args.slug,
                    args.role,
                    args.presentation,
                    unit_id=args.unit,
                    round_name=args.round,
                    channel=args.channel,
                )
                _json(result)
                return 0 if result.get("ready") else 1
            data = append_log(
                root,
                args.slug,
                actor=args.actor,
                kind="progress",
                presentation_id=args.presentation,
                unit_id=args.unit,
                round_name=args.round,
                channel=args.channel,
                message=args.message,
                data={"status": args.status},
            )
            _json(data)
            return 0

        if args.command == "checkpoint":
            if args.checkpoint_command == "save":
                result = save_checkpoint(
                    root,
                    args.slug,
                    args.role,
                    args.presentation,
                    unit_id=args.unit,
                    completed=args.completed,
                    decisions=args.decision,
                    open_issues=args.open_issue,
                    next_action=args.next_action,
                    durable_paths=args.durable_path,
                    last_successful_build=args.last_successful_build,
                )
            else:
                result = checkpoint_status(
                    root,
                    args.slug,
                    args.role,
                    args.presentation,
                    unit_id=args.unit,
                )
            _json(result)
            return 0

        if args.command == "thread":
            if args.thread_command == "list":
                result = list_threads(root, args.slug)
            elif args.thread_command == "register":
                result = register_thread(
                    root,
                    args.slug,
                    handle_id=args.handle,
                    runtime_name=args.runtime_name,
                    role=args.role,
                )
            elif args.thread_command == "assign":
                result = assign_thread(
                    root,
                    args.slug,
                    handle_id=args.handle,
                    assignment_id=args.assignment_id,
                    role=args.role,
                    presentation_id=args.presentation,
                    unit_id=args.unit,
                    round_name=args.round,
                    channel=args.channel,
                )
            elif args.thread_command == "handoff":
                result = validate_handoff(
                    root,
                    args.slug,
                    handle_id=args.handle,
                    durable_paths=args.durable_path,
                    summary=args.summary,
                )
            else:
                result = release_thread(
                    root,
                    args.slug,
                    handle_id=args.handle,
                    runtime_operation=args.runtime_operation,
                    capacity_released=args.capacity_released,
                    notes=args.notes,
                )
            _json(result)
            return 0

        if args.command == "log":
            extra = json.loads(args.data_json) if args.data_json else None
            if extra is not None and not isinstance(extra, dict):
                raise MPresError("--data-json must decode to an object.")
            _json(
                append_log(
                    root,
                    args.slug,
                    actor=args.actor,
                    kind=args.kind,
                    presentation_id=args.presentation,
                    unit_id=args.unit,
                    round_name=args.round,
                    channel=args.channel,
                    message=args.message,
                    data=extra,
                )
            )
            return 0

        if args.command == "reference":
            _json(
                ingest_reference(
                    root,
                    args.slug,
                    args.source,
                    name=args.name,
                    ocr_mode=args.ocr,
                    max_pages=args.max_pages,
                )
            )
            return 0

        if args.command == "source":
            result = lint_task_source(
                root, args.slug, args.presentation, stage=args.stage
            )
            _json(result)
            return 0 if result.get("success") else 1

        if args.command == "assets":
            source_root, _ = source_and_build_paths(
                root, args.slug, args.presentation, args.stage
            )
            if args.assets_command == "validate":
                result = validate_assets(
                    root,
                    args.slug,
                    args.presentation,
                    source_root=source_root,
                    stage=args.stage,
                )
            else:
                result = run_python_asset(
                    root,
                    args.slug,
                    args.presentation,
                    source_root=source_root,
                    asset_id=args.asset,
                    timeout=args.timeout,
                )
            _json(result)
            return 0 if result.get("success") else 1

        if args.command == "geogebra":
            result = validate_task_geogebra(
                root, args.slug, args.presentation, stage=args.stage
            )
            _json(result)
            return 0 if result.get("success") else 1

        if args.command == "render":
            _json(
                render_presentation(
                    root,
                    args.slug,
                    args.presentation,
                    stage=args.stage,
                    source_override=args.source,
                    timeout=args.timeout,
                )
            )
            return 0

        if args.command == "inspect":
            if args.inspect_command == "html-layout":
                result = inspect_task_html_layout(
                    root,
                    args.slug,
                    args.presentation,
                    stage=args.stage,
                    timeout=args.timeout,
                )
            else:
                result = inspect_task_pdf(
                    root, args.slug, args.presentation, stage=args.stage
                )
            _json(result)
            return 0 if result.get("success") else 1

        if args.command == "review":
            if args.review_command == "request":
                result = request_review(
                    root,
                    args.slug,
                    args.presentation,
                    changed_areas=args.changed_area,
                )
            elif args.review_command == "submit-channel":
                result = submit_channel_review(
                    root,
                    args.slug,
                    args.presentation,
                    round_name=args.round,
                    channel=args.channel,
                    report_path=args.report,
                    findings_path=args.findings,
                )
            elif args.review_command == "aggregate":
                result = aggregate_round(
                    root,
                    args.slug,
                    args.presentation,
                    round_name=args.round,
                    aggregate_path=args.report,
                )
            elif args.review_command == "respond":
                result = record_author_responses(
                    root,
                    args.slug,
                    args.presentation,
                    response_file=args.file,
                )
            elif args.review_command == "complete-revision":
                result = complete_author_revision(
                    root,
                    args.slug,
                    args.presentation,
                    checklist_file=args.checklist,
                )
            elif args.review_command == "return-to-author":
                result = return_to_author(
                    root, args.slug, args.presentation, reason=args.reason
                )
            elif args.review_command == "finalize":
                result = finalize_release(root, args.slug, args.presentation)
            elif args.review_command == "bundle":
                result = build_context_bundle(
                    root,
                    args.slug,
                    args.presentation,
                    round_name=args.round,
                    channel=args.channel,
                )
            else:
                result = review_status(root, args.slug, args.presentation)
            _json(result)
            return 0

        if args.command == "supervise":
            if args.watch:
                watch_supervision(
                    root,
                    args.slug,
                    scope=args.scope,
                    presentation_id=args.presentation,
                    interval=args.interval,
                    iterations=args.iterations,
                )
                return 0
            result = supervise_once(
                root,
                args.slug,
                scope=args.scope,
                presentation_id=args.presentation,
                record=args.record,
            )
            _json(result)
            return 1 if result.get("requires_attention") else 0

        if args.command == "token":
            if args.token_command == "import-session":
                result = import_session(
                    root,
                    args.slug,
                    args.source,
                    presentation_id=args.presentation,
                    role=args.role,
                    unit_id=args.unit,
                    round_name=args.round,
                    channel=args.channel,
                    thread_id=args.thread_id,
                )
            elif args.token_command == "collector-init":
                result = initialize_collector(
                    root,
                    args.slug,
                    sessions_root=args.sessions_root,
                    root_thread_id=args.root_thread_id,
                    task_started_at=args.task_started_at,
                    session_date_floor=args.session_date_floor,
                )
            elif args.token_command == "collector-collect":
                result = collect_tokens(root, args.slug)
            elif args.token_command == "collector-status":
                result = collector_status(root, args.slug)
            elif args.token_command == "snapshot":
                result = save_token_snapshot(root, args.slug, group_by=args.group_by)
            else:
                result = token_report(root, args.slug, group_by=args.group_by)
            _json(result)
            return 0

        if args.command == "audit":
            result = audit_task(root, args.slug)
            _json(result)
            return 0 if result.get("ok") else 1

        return 2
    except (MPresError, ValueError, OSError, json.JSONDecodeError) as exc:
        print(f"mpres: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
