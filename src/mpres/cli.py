from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from mpres.assets import run_python_asset, validate_assets
from mpres.audit import audit_task
from mpres.checkpoints import checkpoint_status, save_checkpoint
from mpres.doctor import doctor_report
from mpres.geogebra import validate_task_geogebra
from mpres.logs import append_log
from mpres.marp_source import lint_task_source
from mpres.pdf_inspection import inspect_task_pdf
from mpres.production import ROLES, activate_presentations, assemble_units, check_assignment, initialize_production
from mpres.references import ingest_reference
from mpres.rendering import render_presentation, source_and_build_paths
from mpres.review import (
    aggregate_round,
    approve_release_closure,
    build_context_bundle,
    finalize_release,
    record_author_responses,
    request_review,
    review_status,
    revoke_release_approval,
    submit_channel_review,
)
from mpres.state import REVIEW_CHANNELS, REVIEW_ROUNDS
from mpres.supervision import supervise_once, watch_supervision
from mpres.tasks import confirm_task, continue_task, create_task, gate_status, list_tasks, present_task, restore_confirmed_task, task_status
from mpres.tokens import import_session, save_token_snapshot, token_report
from mpres.util import MPresError, find_repo_root, read_yaml


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
    print(f"Marp PDF probe: {'PASS' if probe.get('ok') else 'FAIL' if probe.get('ok') is False else 'SKIPPED'}")
    if report["warnings"]:
        print("\nWarnings:")
        for warning in report["warnings"]:
            print(f"  - {warning}")
    print("\nResult:", "READY" if report["ok"] else "BLOCKED")
    if report["blockers"]:
        print("Blockers:", ", ".join(report["blockers"]))


def _coordinates(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--role", choices=sorted(ROLES), required=True)
    parser.add_argument("--presentation", required=True)
    parser.add_argument("--unit")
    parser.add_argument("--round", choices=REVIEW_ROUNDS)
    parser.add_argument("--channel", choices=REVIEW_CHANNELS)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="mpres", description="Parallel Marp-to-PDF presentation orchestration with three mandatory review rounds.")
    parser.add_argument("--root", type=Path)
    commands = parser.add_subparsers(dest="command", required=True)

    doctor = commands.add_parser("doctor")
    doctor.add_argument("--json", action="store_true")
    doctor.add_argument("--strict", action="store_true")
    doctor.add_argument("--skip-pdf-probe", action="store_true")

    task = commands.add_parser("task")
    task_sub = task.add_subparsers(dest="task_command", required=True)
    init = task_sub.add_parser("init")
    init.add_argument("--title", required=True); init.add_argument("--slug")
    init.add_argument("--kind", choices=["course", "report"], required=True)
    init.add_argument("--stop-mode", choices=["pilot", "each", "all"], required=True)
    init.add_argument("--sessions", type=int); init.add_argument("--minutes", type=int)
    task_sub.add_parser("list").add_argument("--json", action="store_true")
    for name in ("present", "confirm", "gate", "status", "continue", "restore-confirmed"):
        sub = task_sub.add_parser(name); sub.add_argument("slug")

    production = commands.add_parser("production")
    production_sub = production.add_subparsers(dest="production_command", required=True)
    pinit = production_sub.add_parser("init"); pinit.add_argument("slug")
    pinit.add_argument("--presentation", action="append", required=True)
    pinit.add_argument("--unit", action="append", required=True)
    activate = production_sub.add_parser("activate"); activate.add_argument("slug")
    activate.add_argument("--presentation", action="append", required=True)

    author = commands.add_parser("author")
    author_sub = author.add_subparsers(dest="author_command", required=True)
    assemble = author_sub.add_parser("assemble"); assemble.add_argument("slug"); assemble.add_argument("--presentation", required=True)

    role = commands.add_parser("role")
    role_sub = role.add_subparsers(dest="role_command", required=True)
    assignment = role_sub.add_parser("assignment-check"); assignment.add_argument("slug"); _coordinates(assignment)
    heartbeat = role_sub.add_parser("heartbeat"); heartbeat.add_argument("slug"); heartbeat.add_argument("--actor", required=True)
    heartbeat.add_argument("--presentation"); heartbeat.add_argument("--unit"); heartbeat.add_argument("--round"); heartbeat.add_argument("--channel")
    heartbeat.add_argument("--status", required=True); heartbeat.add_argument("--message", required=True)

    checkpoint = commands.add_parser("checkpoint")
    cp_sub = checkpoint.add_subparsers(dest="checkpoint_command", required=True)
    cps = cp_sub.add_parser("save"); cps.add_argument("slug"); cps.add_argument("--role", choices=["author-coordinator", "lesson-author", "review-coordinator", "release-coordinator"], required=True)
    cps.add_argument("--presentation", required=True); cps.add_argument("--unit")
    cps.add_argument("--completed", action="append", default=[]); cps.add_argument("--decision", action="append", default=[]); cps.add_argument("--open-issue", action="append", default=[])
    cps.add_argument("--next-action", required=True); cps.add_argument("--durable-path", action="append", default=[]); cps.add_argument("--last-successful-build")
    cpg = cp_sub.add_parser("status"); cpg.add_argument("slug"); cpg.add_argument("--role", choices=["author-coordinator", "lesson-author", "review-coordinator", "release-coordinator"], required=True); cpg.add_argument("--presentation", required=True); cpg.add_argument("--unit")

    log = commands.add_parser("log")
    log_sub = log.add_subparsers(dest="log_command", required=True)
    add = log_sub.add_parser("add"); add.add_argument("slug"); add.add_argument("--actor", required=True)
    add.add_argument("--kind", choices=["decision", "progress", "check", "warning", "error", "restart", "review", "render", "handoff", "delivery", "checkpoint"], required=True)
    add.add_argument("--presentation"); add.add_argument("--unit"); add.add_argument("--round"); add.add_argument("--channel"); add.add_argument("--message", required=True); add.add_argument("--data-json")

    ref = commands.add_parser("reference"); ref_sub = ref.add_subparsers(dest="reference_command", required=True)
    ingest = ref_sub.add_parser("ingest"); ingest.add_argument("slug"); ingest.add_argument("source"); ingest.add_argument("--name"); ingest.add_argument("--ocr", choices=["auto", "always", "never"], default="auto"); ingest.add_argument("--max-pages", type=int, default=250)

    source = commands.add_parser("source"); source_sub = source.add_subparsers(dest="source_command", required=True)
    lint = source_sub.add_parser("lint"); lint.add_argument("slug"); lint.add_argument("--presentation", required=True); lint.add_argument("--stage", choices=["author", "release"], default="author")

    assets = commands.add_parser("assets"); assets_sub = assets.add_subparsers(dest="assets_command", required=True)
    aval = assets_sub.add_parser("validate"); aval.add_argument("slug"); aval.add_argument("--presentation", required=True); aval.add_argument("--stage", choices=["author", "release"], default="author")
    agen = assets_sub.add_parser("generate"); agen.add_argument("slug"); agen.add_argument("--presentation", required=True); agen.add_argument("--asset", required=True); agen.add_argument("--stage", choices=["author"], default="author"); agen.add_argument("--timeout", type=int, default=600)

    geogebra = commands.add_parser("geogebra"); geogebra_sub = geogebra.add_subparsers(dest="geogebra_command", required=True)
    gvalidate = geogebra_sub.add_parser("validate"); gvalidate.add_argument("slug"); gvalidate.add_argument("--presentation", required=True); gvalidate.add_argument("--stage", choices=["author", "release"], default="author")

    render = commands.add_parser("render"); render.add_argument("slug"); render.add_argument("--presentation", required=True); render.add_argument("--stage", choices=["author", "release"], required=True); render.add_argument("--source", type=Path); render.add_argument("--timeout", type=int, default=1800)
    inspect = commands.add_parser("inspect"); inspect_sub = inspect.add_subparsers(dest="inspect_command", required=True)
    ipdf = inspect_sub.add_parser("pdf"); ipdf.add_argument("slug"); ipdf.add_argument("--presentation", required=True); ipdf.add_argument("--stage", choices=["author", "release"], required=True)

    review = commands.add_parser("review"); review_sub = review.add_subparsers(dest="review_command", required=True)
    rr = review_sub.add_parser("request"); rr.add_argument("slug"); rr.add_argument("--presentation", required=True); rr.add_argument("--changed-area", action="append", default=[])
    rs = review_sub.add_parser("submit-channel"); rs.add_argument("slug"); rs.add_argument("--presentation", required=True); rs.add_argument("--round", choices=REVIEW_ROUNDS, required=True); rs.add_argument("--channel", choices=REVIEW_CHANNELS, required=True); rs.add_argument("--report", type=Path, required=True); rs.add_argument("--findings", type=Path, required=True)
    ra = review_sub.add_parser("aggregate"); ra.add_argument("slug"); ra.add_argument("--presentation", required=True); ra.add_argument("--round", choices=REVIEW_ROUNDS, required=True); ra.add_argument("--report", type=Path, required=True)
    resp = review_sub.add_parser("respond"); resp.add_argument("slug"); resp.add_argument("--presentation", required=True); resp.add_argument("--file", type=Path, required=True)
    approve = review_sub.add_parser("approve-release"); approve.add_argument("slug"); approve.add_argument("--presentation", required=True); approve.add_argument("--closures", type=Path, required=True); approve.add_argument("--report", type=Path, required=True)
    revoke = review_sub.add_parser("revoke-release"); revoke.add_argument("slug"); revoke.add_argument("--presentation", required=True); revoke.add_argument("--reason", required=True)
    final = review_sub.add_parser("finalize"); final.add_argument("slug"); final.add_argument("--presentation", required=True)
    bundle = review_sub.add_parser("bundle"); bundle.add_argument("slug"); bundle.add_argument("--presentation", required=True); bundle.add_argument("--round", choices=REVIEW_ROUNDS, required=True); bundle.add_argument("--channel", choices=REVIEW_CHANNELS, required=True)
    status = review_sub.add_parser("status"); status.add_argument("slug"); status.add_argument("--presentation")

    supervise = commands.add_parser("supervise"); supervise.add_argument("slug"); supervise.add_argument("--scope", choices=["planner", "author", "review"], default="planner"); supervise.add_argument("--presentation"); supervise.add_argument("--record", action="store_true"); supervise.add_argument("--watch", action="store_true"); supervise.add_argument("--interval", type=int); supervise.add_argument("--iterations", type=int)

    token = commands.add_parser("token"); token_sub = token.add_subparsers(dest="token_command", required=True)
    ti = token_sub.add_parser("import-session"); ti.add_argument("slug"); ti.add_argument("source", type=Path); ti.add_argument("--presentation"); ti.add_argument("--role", required=True); ti.add_argument("--unit"); ti.add_argument("--round"); ti.add_argument("--channel"); ti.add_argument("--thread-id")
    for name in ("snapshot", "report"):
        sub = token_sub.add_parser(name); sub.add_argument("slug"); sub.add_argument("--group-by", choices=["presentation_id", "role", "unit_id", "round", "channel", "model", "thread_id"], default="presentation_id")

    audit = commands.add_parser("audit"); audit.add_argument("slug")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        root = args.root.expanduser().resolve() if args.root else find_repo_root()
        if args.command == "doctor":
            result = doctor_report(root, run_pdf_probe=not args.skip_pdf_probe); _json(result) if args.json else _doctor_human(result); return 1 if args.strict and not result["ok"] else 0
        if args.command == "task":
            if args.task_command == "init":
                slug, path = create_task(root=root, title=args.title, slug=args.slug, kind=args.kind, stop_mode=args.stop_mode, sessions=args.sessions, minutes=args.minutes); result = {"task_slug": slug, "task_path": str(path), "task_md": str(path / "TASK.md")}
            elif args.task_command == "list": result = list_tasks(root)
            elif args.task_command == "present": result = present_task(root, args.slug)
            elif args.task_command == "confirm": result = confirm_task(root, args.slug)
            elif args.task_command == "gate":
                ok, message, state = gate_status(root, args.slug); result = {"ok": ok, "message": message, "phase": state.get("phase")}; _json(result); return 0 if ok else 1
            elif args.task_command == "status": result = task_status(root, args.slug)
            elif args.task_command == "continue": result = continue_task(root, args.slug)
            else: result = restore_confirmed_task(root, args.slug)
            _json(result); return 0
        if args.command == "production":
            result = initialize_production(root, args.slug, args.presentation, args.unit) if args.production_command == "init" else activate_presentations(root, args.slug, args.presentation); _json(result); return 0
        if args.command == "author": _json(assemble_units(root, args.slug, args.presentation)); return 0
        if args.command == "role":
            if args.role_command == "assignment-check":
                result = check_assignment(root, args.slug, args.role, args.presentation, unit_id=args.unit, round_name=args.round, channel=args.channel); _json(result); return 0 if result.get("ready") else 1
            data = append_log(root, args.slug, actor=args.actor, kind="progress", presentation_id=args.presentation, unit_id=args.unit, round_name=args.round, channel=args.channel, message=args.message, data={"status": args.status}); _json(data); return 0
        if args.command == "checkpoint":
            result = save_checkpoint(root, args.slug, args.role, args.presentation, unit_id=args.unit, completed=args.completed, decisions=args.decision, open_issues=args.open_issue, next_action=args.next_action, durable_paths=args.durable_path, last_successful_build=args.last_successful_build) if args.checkpoint_command == "save" else checkpoint_status(root, args.slug, args.role, args.presentation, unit_id=args.unit); _json(result); return 0
        if args.command == "log":
            data = json.loads(args.data_json) if args.data_json else None
            if data is not None and not isinstance(data, dict): raise MPresError("--data-json must decode to an object.")
            _json(append_log(root, args.slug, actor=args.actor, kind=args.kind, presentation_id=args.presentation, unit_id=args.unit, round_name=args.round, channel=args.channel, message=args.message, data=data)); return 0
        if args.command == "reference": _json(ingest_reference(root, args.slug, args.source, name=args.name, ocr_mode=args.ocr, max_pages=args.max_pages)); return 0
        if args.command == "source":
            result = lint_task_source(root, args.slug, args.presentation, stage=args.stage); _json(result); return 0 if result.get("success") else 1
        if args.command == "assets":
            source_root, _ = source_and_build_paths(root, args.slug, args.presentation, args.stage)
            result = validate_assets(root, args.slug, args.presentation, source_root=source_root, stage=args.stage) if args.assets_command == "validate" else run_python_asset(root, args.slug, args.presentation, source_root=source_root, asset_id=args.asset, timeout=args.timeout); _json(result); return 0 if result.get("success", True) else 1
        if args.command == "geogebra":
            result = validate_task_geogebra(root, args.slug, args.presentation, stage=args.stage); _json(result); return 0 if result.get("success") else 1
        if args.command == "render": _json(render_presentation(root, args.slug, args.presentation, stage=args.stage, source_override=args.source, timeout=args.timeout)); return 0
        if args.command == "inspect":
            result = inspect_task_pdf(root, args.slug, args.presentation, stage=args.stage); _json(result); return 0 if result.get("success") else 1
        if args.command == "review":
            if args.review_command == "request": result = request_review(root, args.slug, args.presentation, changed_areas=args.changed_area)
            elif args.review_command == "submit-channel": result = submit_channel_review(root, args.slug, args.presentation, round_name=args.round, channel=args.channel, report_path=args.report, findings_path=args.findings)
            elif args.review_command == "aggregate": result = aggregate_round(root, args.slug, args.presentation, round_name=args.round, aggregate_path=args.report)
            elif args.review_command == "respond": result = record_author_responses(root, args.slug, args.presentation, response_file=args.file)
            elif args.review_command == "approve-release": result = approve_release_closure(root, args.slug, args.presentation, closure_file=args.closures, closure_report=args.report)
            elif args.review_command == "revoke-release": result = revoke_release_approval(root, args.slug, args.presentation, reason=args.reason)
            elif args.review_command == "finalize": result = finalize_release(root, args.slug, args.presentation)
            elif args.review_command == "bundle": result = build_context_bundle(root, args.slug, args.presentation, round_name=args.round, channel=args.channel)
            else: result = review_status(root, args.slug, args.presentation)
            _json(result); return 0
        if args.command == "supervise":
            if args.watch: watch_supervision(root, args.slug, scope=args.scope, presentation_id=args.presentation, interval=args.interval, iterations=args.iterations); return 0
            result = supervise_once(root, args.slug, scope=args.scope, presentation_id=args.presentation, record=args.record); _json(result); return 1 if result.get("requires_attention") else 0
        if args.command == "token":
            if args.token_command == "import-session": result = import_session(root, args.slug, args.source, presentation_id=args.presentation, role=args.role, unit_id=args.unit, round_name=args.round, channel=args.channel, thread_id=args.thread_id)
            elif args.token_command == "snapshot": result = save_token_snapshot(root, args.slug, group_by=args.group_by)
            else: result = token_report(root, args.slug, group_by=args.group_by)
            _json(result); return 0
        if args.command == "audit":
            result = audit_task(root, args.slug); _json(result); return 0 if result.get("ok") else 1
        return 2
    except (MPresError, ValueError, OSError, json.JSONDecodeError) as exc:
        print(f"mpres: {exc}", file=sys.stderr); return 2


if __name__ == "__main__":
    raise SystemExit(main())
