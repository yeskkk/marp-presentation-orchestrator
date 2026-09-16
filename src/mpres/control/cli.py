from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

from mpres.util import MPresError, find_repo_root, safe_id
from .migration import import_legacy
from .service import Service


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog='mpres',description='One task database; semantic AI jobs; mechanical workflow control.')
    parser.add_argument('--root',type=Path)
    sub = parser.add_subparsers(dest='command',required=True)
    storage=sub.add_parser('storage').add_subparsers(dest='operation',required=True)
    for action in ('inspect','migrate','prune','compact'):
        op=storage.add_parser(action);op.add_argument('slug')
        if action in {'migrate','compact'}:op.add_argument('--by',required=True)
        if action=='prune':
            choice=op.add_mutually_exclusive_group(required=True)
            choice.add_argument('--dry-run',action='store_true');choice.add_argument('--apply',metavar='PLAN_ID')
            op.add_argument('--by');op.add_argument('--success-days',type=int);op.add_argument('--failure-days',type=int);op.add_argument('--policy',type=Path)
            op.add_argument('--backup-dir',type=Path)
    op=storage.add_parser('checkpoint');op.add_argument('slug')
    choice=op.add_mutually_exclusive_group(required=True)
    choice.add_argument('--dry-run',action='store_true');choice.add_argument('--apply',metavar='PLAN_ID');choice.add_argument('--resume',metavar='CHECKPOINT_ID');choice.add_argument('--status',action='store_true')
    op.add_argument('--by');op.add_argument('--allow-missing-pdf',action='store_true',help='Archive validation only; does not claim PDF delivery ready')
    op=storage.add_parser('policy');op.add_argument('slug');op.add_argument('--by',required=True)
    choice=op.add_mutually_exclusive_group(required=True);choice.add_argument('--current-only',action='store_true');choice.add_argument('--manual-only',action='store_true')
    op=storage.add_parser('evidence');op.add_argument('slug');op.add_argument('--wire-id',type=int,required=True)
    reports=sub.add_parser('report').add_subparsers(dest='operation',required=True)
    op=reports.add_parser('usage');op.add_argument('slug');op.add_argument('--presentation',action='append');op.add_argument('--format',choices=['json','md','csv'],default='json');op.add_argument('--output',type=Path)
    supervision=sub.add_parser('supervision').add_subparsers(dest='operation',required=True)
    for action in ('pending','ack','wait-start','wait-end'):
        op=supervision.add_parser(action);op.add_argument('slug')
        if action!='pending':op.add_argument('--by',required=True)
        if action=='ack':op.add_argument('handoff_id');op.add_argument('--note',required=True)
        if action=='wait-start':op.add_argument('--reason',required=True);op.add_argument('--note',required=True);op.add_argument('--presentation')
        if action=='wait-end':op.add_argument('wait_id')
    source = sub.add_parser('source').add_subparsers(dest='operation',required=True)
    source_check=source.add_parser('check');source_check.add_argument('directory',type=Path)
    for action in ('quote','lines'):
        op=source.add_parser(action);op.add_argument('directory',type=Path);op.add_argument('--slide-id',required=True)
        if action=='quote':op.add_argument('--start-line',type=int,required=True);op.add_argument('--end-line',type=int,required=True)
    exercise=sub.add_parser('exercise').add_subparsers(dest='operation',required=True)
    for action in ('candidates','check','isolate'):
        cmd=exercise.add_parser(action);cmd.add_argument('directory',type=Path)
        if action=='isolate':cmd.add_argument('--slide-id',required=True)
    resource=sub.add_parser('resource').add_subparsers(dest='operation',required=True)
    op=resource.add_parser('preflight');op.add_argument('slug');op.add_argument('--presentation')
    figure = sub.add_parser('figure').add_subparsers(dest='operation',required=True)
    fb=figure.add_parser('build');fb.add_argument('spec',type=Path)
    fc=figure.add_parser('check');fc.add_argument('directory',type=Path)
    task = sub.add_parser('task').add_subparsers(dest='operation',required=True)
    init = task.add_parser('init'); init.add_argument('slug'); init.add_argument('--title',required=True)
    op=task.add_parser('open');op.add_argument('slug');op.add_argument('--by',default='program:task-open')
    for action in ('present','confirm','status','metrics','jobs','materialize'):
        cmd = task.add_parser(action); cmd.add_argument('slug')
        if action=='confirm': cmd.add_argument('--by',required=True)
    backup = task.add_parser('backup-db'); backup.add_argument('slug'); backup.add_argument('destination',type=Path)
    imp = task.add_parser('import-legacy'); imp.add_argument('old_task',type=Path); imp.add_argument('--slug',required=True)
    for action in ('policy-pause','policy-resume'):
        op=task.add_parser(action);op.add_argument('slug');op.add_argument('--by',required=True)
        if action=='policy-pause':op.add_argument('--note',required=True)
    op=task.add_parser('policy-show');op.add_argument('slug')
    op=task.add_parser('policy-present');op.add_argument('slug');op.add_argument('--handle-limit',type=int);op.add_argument('--context-budget-bytes',type=int)
    op=task.add_parser('policy-confirm');op.add_argument('slug');op.add_argument('--presentation-id',type=int,required=True);op.add_argument('--by',required=True)
    plan=sub.add_parser('plan').add_subparsers(dest='operation',required=True)
    op=plan.add_parser('show');op.add_argument('slug')
    op=plan.add_parser('present');op.add_argument('slug');op.add_argument('--proposal',type=Path,required=True)
    for action in ('confirm','cancel'):
        op=plan.add_parser(action);op.add_argument('slug');op.add_argument('plan_change_id');op.add_argument('--by',required=True)
    op=plan.add_parser('split-published-present');op.add_argument('slug');op.add_argument('--proposal',type=Path,required=True)
    for action in ('split-published-confirm','split-published-run'):
        op=plan.add_parser(action);op.add_argument('slug');op.add_argument('plan_change_id');op.add_argument('--by',required=True)
    bridge=sub.add_parser('bridge').add_subparsers(dest='operation',required=True)
    for action in ('index','status','run','reconcile'):
        op=bridge.add_parser(action);op.add_argument('slug')
        if action in {'index','status'}:
            op.add_argument('--journal',type=Path);op.add_argument('--index',type=Path)
        else:
            op.add_argument('--codex',default='codex')
            if action=='run':op.add_argument('--cycles',type=int,default=100)
            else:op.add_argument('request_id')
    batch=sub.add_parser('batch').add_subparsers(dest='operation',required=True)
    op=batch.add_parser('present');op.add_argument('slug');op.add_argument('--presentation',action='append',required=True)
    op=batch.add_parser('confirm');op.add_argument('slug');op.add_argument('batch_id');op.add_argument('--by',required=True)
    op=batch.add_parser('status');op.add_argument('slug')
    session = sub.add_parser('session').add_subparsers(dest='operation',required=True)
    register = session.add_parser('register'); register.add_argument('slug'); register.add_argument('--handle',required=True)
    register.add_argument('--family',choices=['planner','author','reviewer'],required=True)
    register.add_argument('--model',required=True); register.add_argument('--effort',choices=['low','medium','high','max'],required=True)
    register.add_argument('--receipt',required=True)
    job = sub.add_parser('job').add_subparsers(dest='operation',required=True)
    show=job.add_parser('show'); show.add_argument('slug'); show.add_argument('job_id')
    bind=job.add_parser('bind'); bind.add_argument('slug'); bind.add_argument('job_id'); bind.add_argument('--handle',required=True)
    for action in ('started','submit','uncertain','usage'):
        cmd=job.add_parser(action);cmd.add_argument('slug');cmd.add_argument('attempt_id')
        if action=='started':cmd.add_argument('--receipt',required=True)
        elif action=='submit':
            cmd.add_argument('--result',type=Path,required=True);cmd.add_argument('--source',type=Path)
        elif action=='uncertain':cmd.add_argument('--reason',required=True)
        else:cmd.add_argument('--call-id',required=True);cmd.add_argument('--counters',type=Path,required=True)
    runner=sub.add_parser('runner').add_subparsers(dest='operation',required=True)
    for action in ('capacity','tick','outstanding','host','attach','accept','run'):
        cmd=runner.add_parser(action);cmd.add_argument('slug')
        if action=='host':cmd.add_argument('--report',required=True)
        elif action=='attach':
            cmd.add_argument('--slot',type=int,required=True);cmd.add_argument('--handle',required=True)
            cmd.add_argument('--model',required=True);cmd.add_argument('--effort',required=True);cmd.add_argument('--receipt',required=True)
        elif action=='accept':
            cmd.add_argument('--request',required=True);cmd.add_argument('--response',required=True)
        elif action=='run':
            cmd.add_argument('--cycles',type=int,default=100);cmd.add_argument('--interval',type=float,default=1)
    artifact=sub.add_parser('artifact').add_subparsers(dest='operation',required=True)
    inspect=artifact.add_parser('inspect'); inspect.add_argument('slug'); inspect.add_argument('artifact_id')
    inspect.add_argument('--level',choices=['source','full'],default='source'); inspect.add_argument('--retry',action='store_true')
    gates=artifact.add_parser('gates'); gates.add_argument('slug'); gates.add_argument('artifact_id')
    interrupt=artifact.add_parser('interrupt-gate'); interrupt.add_argument('slug'); interrupt.add_argument('gate_id')
    interrupt.add_argument('--reason',required=True)
    for name in ('replay','resume-input'):
        cmd=runner.add_parser(name);cmd.add_argument('slug')
        cmd.add_argument('identity')
    workflow=sub.add_parser('workflow').add_subparsers(dest='operation',required=True)
    for name in ('advance','status','materialize','bundle','continue','retry-checks','retry-publish','recover-assembly','edit-after-amendment','resume-author-revision'):
        cmd=workflow.add_parser(name);cmd.add_argument('slug')
        if name=='continue':cmd.add_argument('--by',required=True);cmd.add_argument('--note',required=True)
        if name in {'edit-after-amendment','resume-author-revision'}:cmd.add_argument('--presentation',required=True);cmd.add_argument('--by',required=True);cmd.add_argument('--note',required=True)
        if name in {'retry-checks','retry-publish'}:cmd.add_argument('--presentation',required=True);cmd.add_argument('--note',required=True)
        if name=='recover-assembly':cmd.add_argument('--job-id',required=True);cmd.add_argument('--note',required=True)
    feedback=sub.add_parser('feedback').add_subparsers(dest='operation',required=True)
    ls=feedback.add_parser('list');ls.add_argument('slug');ls.add_argument('--history',action='store_true')
    rec=feedback.add_parser('record');rec.add_argument('slug');rec.add_argument('--rule',required=True);rec.add_argument('--by',required=True)
    inherit=feedback.add_parser('inherit');inherit.add_argument('slug');inherit.add_argument('--from-task',type=Path,required=True);inherit.add_argument('--by',required=True)
    for op in ('briefing','acknowledge'):
        cmd=job.add_parser(op);cmd.add_argument('slug');cmd.add_argument('attempt_id')
        if op=='acknowledge':cmd.add_argument('--readback',required=True);cmd.add_argument('--receipt',required=True)
    repair=sub.add_parser('repair').add_subparsers(dest='operation',required=True)
    op=repair.add_parser('open');op.add_argument('slug');op.add_argument('--report',required=True);op.add_argument('--presentation',action='append',required=True);op.add_argument('--by',required=True);op.add_argument('--mode',choices=['edit-first','review-first'],default='edit-first');op.add_argument('--allow-slide-changes',action='store_true');op.add_argument('--focus',choices=['reported-issues','student-expression'],default='reported-issues')
    op=repair.add_parser('status');op.add_argument('slug')
    for action in ('present','confirm','amend','cancel','materialize','bundle'):
        op=repair.add_parser(action);op.add_argument('slug');op.add_argument('case_id')
        if action in {'confirm','amend','cancel'}:op.add_argument('--by',required=True)
        if action=='confirm':op.add_argument('--version',type=int,required=True)
        if action=='amend':op.add_argument('--proposal',required=True)
        if action=='cancel':op.add_argument('--note',required=True)
    toolchain=sub.add_parser('toolchain').add_subparsers(dest='operation',required=True)
    doctor=toolchain.add_parser('doctor');doctor.add_argument('--timeout',type=int,default=120)
    return parser


def json_input(value):
    return json.loads(sys.stdin.read() if value=='-' else Path(value).read_text())


def main(argv: list[str] | None = None) -> int:
    parser=build_parser();args=parser.parse_args(argv)
    try:
        root=args.root.resolve() if args.root else find_repo_root()
        if args.command=='source' and args.operation in {'quote','lines'}:
            from .source_evidence import quote, lines
            result=quote(args.directory.resolve(),args.slide_id,args.start_line,args.end_line) if args.operation=='quote' else lines(args.directory.resolve(),args.slide_id)
        elif args.command=='task' and args.operation=='open':
            from .compatibility import open_task
            safe_id(args.slug,label='task slug');result=open_task(root/'tasks'/args.slug,actor=args.by)
        elif args.command=='source':
            from mpres.source_policy import inspect_source
            result=inspect_source(args.directory.resolve())
        elif args.command=='exercise':
            from .exercises import candidates, read_manifest, isolated_question
            source=args.directory.resolve()
            if args.operation=='candidates':result={'candidate_slide_ids':candidates(source),'not_exhaustive':True,'semantic_sufficiency':'not_proven_by_program'}
            elif args.operation=='isolate':result=isolated_question(source,args.slide_id)
            else:
                manifest=read_manifest(source,required=True)
                result={'success':True,'exercise_count':len(manifest['exercises']),'semantic_sufficiency':'not_proven_by_program'}
        elif args.command=='report':
            safe_id(args.slug,label='task slug');task=root/'tasks'/args.slug
            from .cost_report import report,render
            value=report(task,args.presentation);text=render(value,args.format)
            if args.output:
                if args.output.exists():raise MPresError('Refusing to overwrite an existing report; choose a new output path')
                args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(text,encoding='utf-8')
                result={'report_file':str(args.output),'calls':value['calls_observed'],'read_only_task':True,'model_calls':0}
            elif args.format=='json':result=value
            else:print(text,end='');return 0
        elif args.command=='storage':
            safe_id(args.slug,label='task slug');task=root/'tasks'/args.slug
            from . import storage
            if args.operation=='checkpoint':
                from . import checkpoints
                if args.dry_run:result=checkpoints.plan(task,allow_missing_pdf=args.allow_missing_pdf)
                elif args.status:result=checkpoints.status(task)
                elif args.resume:result=checkpoints.resume(task,args.resume,by=args.by)
                else:result=checkpoints.apply(task,args.apply,by=args.by,allow_missing_pdf=args.allow_missing_pdf)
            elif args.operation=='policy':
                from .checkpoints import policy
                result=policy(task,args.current_only,by=args.by)
            elif args.operation=='evidence':
                from .wire_checkpoint import evidence
                result=evidence(task/'.mpres/codex-bridge.sqlite3',args.wire_id)
            elif args.operation=='inspect':
                from .checkpoints import directory_usage
                result={**storage.inspect(task),'task_directory':directory_usage(task)}
            elif args.operation=='migrate':
                from contextlib import closing
                from .store import Store
                store=Store(task);store.migration_actor=args.by
                with closing(store.connect()) as conn:
                    result={'schema_version':conn.execute('PRAGMA user_version').fetchone()[0],'migration_audit':[dict(r) for r in conn.execute('SELECT * FROM migration_audit ORDER BY id')],'model_calls':0}
            elif args.operation=='compact':result=storage.compact(task,by=args.by)
            else:
                policy=storage.retention_policy(args.policy)
                options={'success_days':args.success_days if args.success_days is not None else policy['success_days'],'failure_days':args.failure_days if args.failure_days is not None else policy['resolved_failure_days']}
                result=storage.plan(task,**options) if args.dry_run else storage.apply(task,args.apply,by=args.by,backup_dir=args.backup_dir,**options)
        elif args.command=='figure':
            from mpres.geometry import build, inspect_figures
            result=build(args.spec.resolve()) if args.operation=='build' else inspect_figures(args.directory.resolve())
        elif args.command=='toolchain':
            from mpres.toolchain import smoke_toolchain
            result=smoke_toolchain(root,timeout=args.timeout)
        elif args.command=='task' and args.operation=='init':
            result={'task':str(Service.create(root,args.slug,args.title).task)}
        elif args.command=='task' and args.operation=='import-legacy':
            result=import_legacy(root,args.old_task,args.slug)
        else:
            safe_id(args.slug,label='task slug')
            service=Service(root/'tasks'/args.slug)
            if args.command=='supervision':
                from . import supervision
                if args.operation=='pending':result=supervision.pending(service)
                elif args.operation=='ack':result=supervision.acknowledge(service,args.handoff_id,by=args.by,note=args.note)
                elif args.operation=='wait-start':result=supervision.wait_start(service,reason=args.reason,by=args.by,note=args.note,presentation=args.presentation)
                else:result=supervision.wait_end(service,args.wait_id,by=args.by)
            elif args.command=='resource':
                from .preflight import require_job_inputs
                with service.store.transaction() as conn:cfg=service.confirmed(conn)
                decks=json.loads(cfg['settings_json'])['presentations']
                selected=[d for d in decks if not args.presentation or d['id']==args.presentation]
                if not selected:raise MPresError('Unknown presentation for preflight')
                result={'model_calls':0,'presentations':{d['id']:require_job_inputs(service,{'presentation':d['id'],'config_id':cfg['id']}) for d in selected}}
            elif args.command=='plan':
                from .planning import Planning
                planning=Planning(service.task)
                if args.operation.startswith('split-published-'):
                    from .published_split import PublishedSplit
                    split=PublishedSplit(service.task)
                    if args.operation=='split-published-present':result=split.present(json.loads(args.proposal.read_text(encoding='utf-8')))
                    elif args.operation=='split-published-confirm':result=split.confirm(args.plan_change_id,args.by)
                    else:result=split.run(args.plan_change_id,args.by)
                elif args.operation=='present':result=planning.present(json.loads(args.proposal.read_text(encoding='utf-8')))
                elif args.operation=='confirm':result=planning.confirm(args.plan_change_id,args.by)
                elif args.operation=='cancel':result=planning.cancel(args.plan_change_id,args.by)
                else:result=planning.show()
            elif args.command=='bridge':
                if args.operation in {'index','status'}:
                    from .codex_index import WireIndex
                    index=WireIndex(args.journal or service.task/'.mpres'/'codex-bridge.sqlite3',args.index)
                    result={**index.sync(),**index.summary()}
                else:
                    from .codex_bridge import CodexBridge
                    with CodexBridge(service.task,executable=args.codex) as bridge:
                        result=bridge.drive(args.cycles) if args.operation=='run' else bridge.reconcile(args.request_id)
                    if getattr(bridge,'maintenance_result',None):result['automatic_maintenance']=bridge.maintenance_result
            elif args.command=='batch':
                from .batches import Batches
                batches=Batches(service.task)
                if args.operation=='present':result=batches.present(args.presentation)
                elif args.operation=='confirm':result=batches.confirm(args.batch_id,args.by)
                else:result=batches.status()
            elif args.command=='task' and args.operation.startswith('policy-'):
                from .policy import Policy
                policy=Policy(service.task)
                if args.operation=='policy-pause':result=policy.pause(args.by,args.note)
                elif args.operation=='policy-resume':result=policy.resume(args.by)
                elif args.operation=='policy-show':result=policy.show()
                elif args.operation=='policy-present':result=policy.present(handle_limit=args.handle_limit,context_budget_bytes=args.context_budget_bytes)
                else:result=policy.confirm(args.presentation_id,args.by)
            elif args.command=='repair':
                from .repairs import Repairs, RepairDelivery
                repair=Repairs(service.task)
                if args.operation=='open':result=repair.open(args.report,args.presentation,args.by,mode=args.mode,allow_slide_changes=args.allow_slide_changes,focus=args.focus)
                elif args.operation=='status':result=repair.status()
                elif args.operation=='present':result=repair.present(args.case_id)
                elif args.operation=='confirm':result=repair.confirm(args.case_id,args.version,args.by)
                elif args.operation=='amend':result=repair.amend(args.case_id,json_input(args.proposal),args.by)
                elif args.operation=='cancel':result=repair.cancel(args.case_id,args.by,args.note)
                else:
                    if repair.case(args.case_id)['state']!='completed':raise MPresError('All selected repair targets must be delivered before materializing the repair view')
                    result=RepairDelivery(service.task,args.case_id).bundle()
            elif args.command=='feedback':
                from .feedback import Feedback
                feedback=Feedback(service.task)
                if args.operation=='list':result=feedback.list(args.history)
                elif args.operation=='record':result=feedback.record(json_input(args.rule),args.by)
                else:
                    prior=Feedback(args.from_task)
                    result=[feedback.record({k:v for k,v in r.items() if k!='version'},args.by) for r in prior.list()]
            elif args.command=='workflow':
                from .workflow import Workflow
                workflow=Workflow(service.task)
                if args.operation in {'materialize','bundle'}:
                    from .delivery import Delivery
                    result=Delivery(service.task).bundle()
                elif args.operation=='continue':result=workflow.continue_delivery(args.by,args.note)
                elif args.operation=='edit-after-amendment':result=workflow.edit_after_amendment(args.presentation,args.by,args.note)
                elif args.operation=='resume-author-revision':result=workflow.resume_author_revision(args.presentation,args.by,args.note)
                elif args.operation=='retry-checks':result=workflow.retry_checks(args.presentation,args.note)
                elif args.operation=='retry-publish':result=workflow.retry_publish(args.presentation,args.note)
                elif args.operation=='recover-assembly':result=workflow.recover_assembly(args.job_id,args.note)
                else:result=getattr(workflow,args.operation)()
            elif args.command=='artifact':
                from .quality import Quality
                quality=Quality(service.task)
                if args.operation=='inspect':result=quality.inspect(args.artifact_id,args.level,retry=args.retry)
                elif args.operation=='interrupt-gate':
                    quality.interrupt(args.gate_id,args.reason);result={'interrupted':args.gate_id}
                else:result=service.store.rows('SELECT * FROM gate_runs WHERE artifact_id=? ORDER BY level,sequence',(args.artifact_id,))
            elif args.command=='runner':
                from .runner import Runner
                runner=Runner(service.task)
                if args.operation=='host':result=runner.observe_host(json_input(args.report))
                elif args.operation=='attach':result=runner.attach(args.slot,args.handle,args.model,args.effort,args.receipt)
                elif args.operation=='accept':result=runner.accept(json_input(args.request),json_input(args.response))
                elif args.operation=='replay':result=runner.replay(args.identity)
                elif args.operation=='resume-input':result=runner.resume_input(args.identity)
                elif args.operation=='run':result=runner.run(args.cycles,args.interval)
                else:result=getattr(runner,args.operation)()
            elif args.command=='task':
                if args.operation=='confirm':result=service.confirm(args.by)
                elif args.operation=='backup-db':
                    service.store.backup(args.destination);result={'database_backup':str(args.destination),'includes_artifacts':False}
                else:result=getattr(service,args.operation)()
            elif args.command=='session':
                result=service.register_session(args.handle,args.family,args.model,args.effort,args.receipt)
            elif args.operation=='briefing':
                from .feedback import Feedback
                result=Feedback(service.task).briefing(args.attempt_id)
            elif args.operation=='acknowledge':
                from .feedback import Feedback
                result=Feedback(service.task).acknowledge(args.attempt_id,json_input(args.readback),args.receipt)
            elif args.operation=='show':result=service.job(args.job_id)
            elif args.operation=='bind':result=service.bind(args.job_id,args.handle)
            elif args.operation=='started':result=service.started(args.attempt_id,args.receipt)
            elif args.operation=='uncertain':result=service.uncertain(args.attempt_id,args.reason)
            elif args.operation=='usage':
                result=service.record_usage(args.attempt_id,args.call_id,json.loads(args.counters.read_text()))
            else:result=service.submit(args.attempt_id,json.loads(args.result.read_text()),source=args.source)
        print(json.dumps(result,ensure_ascii=False,indent=2))
        if isinstance(result,dict) and result.get('needs_main_attention'):return result.get('recommended_exit_code',2)
        if isinstance(result,dict) and result.get('delivery_package', {}).get('state')=='failed': return 2
        if isinstance(result,dict) and result.get('success') is False: return 2
        if isinstance(result,dict) and (result.get('status')=='blocked' or result.get('state') in {'failed','interrupted'}): return 2
        if isinstance(result,dict) and any(x.get('status')=='response_rejected' for x in result.get('results',[])): return 2
        if isinstance(result,dict) and any(x.get('status')=='uncertain' for x in result.get('results',[])): return 3
        return 0
    except KeyboardInterrupt:
        failure={'status':'blocked','interrupted':True,'error':'Foreground command interrupted. Inspect retained requests; do not infer completion or resend.'}
        if args.command in {'runner','bridge'} and args.operation in {'run','reconcile'}:
            try:
                from .supervision import terminal
                failure=terminal(Service(root/'tasks'/args.slug),failure,'cli.interrupt',forced_reason=failure['error'])
            except Exception as handoff_error:failure['handoff_error']=str(handoff_error)
        print(json.dumps(failure,ensure_ascii=False))
        return 130
    except (MPresError,sqlite3.Error,OSError,ValueError,TypeError) as exc:
        failure={'error':str(exc),'type':type(exc).__name__}
        if args.command in {'runner','bridge'} and args.operation in {'run','reconcile'}:
            try:
                from .supervision import terminal
                failure=terminal(Service(root/'tasks'/args.slug),{'status':'blocked',**failure},'cli.exception',forced_reason=str(exc))
            except Exception as handoff_error:failure['handoff_error']=str(handoff_error)
        print(json.dumps(failure,ensure_ascii=False))
        return 2
