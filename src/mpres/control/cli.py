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
    task = sub.add_parser('task').add_subparsers(dest='operation',required=True)
    init = task.add_parser('init'); init.add_argument('slug'); init.add_argument('--title',required=True)
    for action in ('present','confirm','status','metrics','jobs','materialize'):
        cmd = task.add_parser(action); cmd.add_argument('slug')
        if action=='confirm': cmd.add_argument('--by',required=True)
    backup = task.add_parser('backup-db'); backup.add_argument('slug'); backup.add_argument('destination',type=Path)
    imp = task.add_parser('import-legacy'); imp.add_argument('old_task',type=Path); imp.add_argument('--slug',required=True)
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
    workflow=sub.add_parser('workflow').add_subparsers(dest='operation',required=True)
    for name in ('advance','status','bundle','continue','retry-checks','retry-publish','recover-assembly'):
        cmd=workflow.add_parser(name);cmd.add_argument('slug')
        if name=='continue':cmd.add_argument('--by',required=True);cmd.add_argument('--note',required=True)
        if name in {'retry-checks','retry-publish'}:cmd.add_argument('--presentation',required=True);cmd.add_argument('--note',required=True)
        if name=='recover-assembly':cmd.add_argument('--job-id',required=True);cmd.add_argument('--note',required=True)
    toolchain=sub.add_parser('toolchain').add_subparsers(dest='operation',required=True)
    doctor=toolchain.add_parser('doctor');doctor.add_argument('--timeout',type=int,default=120)
    return parser


def json_input(value):
    return json.loads(sys.stdin.read() if value=='-' else Path(value).read_text())


def main(argv: list[str] | None = None) -> int:
    parser=build_parser();args=parser.parse_args(argv)
    try:
        root=args.root.resolve() if args.root else find_repo_root()
        if args.command=='toolchain':
            from mpres.toolchain import smoke_toolchain
            result=smoke_toolchain(root,timeout=args.timeout)
        elif args.command=='task' and args.operation=='init':
            result={'task':str(Service.create(root,args.slug,args.title).task)}
        elif args.command=='task' and args.operation=='import-legacy':
            result=import_legacy(root,args.old_task,args.slug)
        else:
            safe_id(args.slug,label='task slug')
            service=Service(root/'tasks'/args.slug)
            if args.command=='workflow':
                from .workflow import Workflow
                workflow=Workflow(service.task)
                if args.operation=='bundle':
                    from .delivery import Delivery
                    result=Delivery(service.task).bundle()
                elif args.operation=='continue':result=workflow.continue_delivery(args.by,args.note)
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
                elif args.operation=='run':result=runner.run(args.cycles,args.interval)
                else:result=getattr(runner,args.operation)()
            elif args.command=='task':
                if args.operation=='confirm':result=service.confirm(args.by)
                elif args.operation=='backup-db':
                    service.store.backup(args.destination);result={'database_backup':str(args.destination),'includes_artifacts':False}
                else:result=getattr(service,args.operation)()
            elif args.command=='session':
                result=service.register_session(args.handle,args.family,args.model,args.effort,args.receipt)
            elif args.operation=='show':result=service.job(args.job_id)
            elif args.operation=='bind':result=service.bind(args.job_id,args.handle)
            elif args.operation=='started':result=service.started(args.attempt_id,args.receipt)
            elif args.operation=='uncertain':result=service.uncertain(args.attempt_id,args.reason)
            elif args.operation=='usage':
                result=service.record_usage(args.attempt_id,args.call_id,json.loads(args.counters.read_text()))
            else:result=service.submit(args.attempt_id,json.loads(args.result.read_text()),source=args.source)
        print(json.dumps(result,ensure_ascii=False,indent=2))
        if isinstance(result,dict) and result.get('delivery_package', {}).get('state')=='failed': return 2
        if isinstance(result,dict) and result.get('success') is False: return 2
        if isinstance(result,dict) and (result.get('status')=='blocked' or result.get('state') in {'failed','interrupted'}): return 2
        if isinstance(result,dict) and any(x.get('status')=='uncertain' for x in result.get('results',[])): return 3
        return 0
    except (MPresError,sqlite3.Error,OSError,ValueError,TypeError) as exc:
        print(json.dumps({'error':str(exc),'type':type(exc).__name__},ensure_ascii=False))
        return 2
