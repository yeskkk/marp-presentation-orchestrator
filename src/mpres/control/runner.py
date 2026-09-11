"""Durable semantic-job runner and conservative persistent session-pool admission.

This stage executes already-approved jobs, not the full deck release state machine.
No model chooses commands; the bridge forwards exact requests. External side effects
are never assumed to be SQLite-transactional or blindly retried.
"""
from __future__ import annotations

import json
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from mpres.runtime_profile import resolve_runtime
from mpres.util import MPresError, read_yaml, utc_now
from .files import copy_tree, inside
from .service import CHANNELS, ROLES, Service, require_text
from .store import encode, event

HOST_TTL_SECONDS = 120


class Runner:
    def __init__(self, task: Path):
        self.service = Service(task)
        self.store = self.service.store
        self.task = self.service.task

    def settings(self) -> dict:
        with self.store.transaction() as conn:
            config=self.service.confirmed(conn)
            return json.loads(config['settings_json'])

    def observe_host(self, report: dict) -> dict:
        """Record actual host evidence, without modifying user-confirmed runtime."""
        if not isinstance(report,dict) or set(report) != {'handle_limit','handles','supports_close','supports_reset','usage_reporting','receipt'}:
            raise MPresError('Host report requires handle_limit, handles, supports_close, supports_reset, usage_reporting, receipt')
        if type(report['handle_limit']) is not int or report['handle_limit']<1:
            raise MPresError('Host limit must be a positive integer')
        handles=report['handles']
        if not isinstance(handles,list) or any(not isinstance(h,str) or not h for h in handles) or len(set(handles)) != len(handles):
            raise MPresError('Host inventory must contain distinct actual provider handle strings')
        if len(handles)>report['handle_limit']:
            raise MPresError('Host inventory exceeds its own limit')
        if any(type(report[k]) is not bool for k in ('supports_close','supports_reset','usage_reporting')):
            raise MPresError('Host capability flags must be booleans')
        require_text(report['receipt'],'host inventory receipt')
        with self.store.transaction() as conn:
            self.service.confirmed(conn)
            conn.execute('INSERT INTO runtime_host(singleton,report_json,observed_at) VALUES(1,?,?) ON CONFLICT(singleton) DO UPDATE SET report_json=excluded.report_json,observed_at=excluded.observed_at',
                         (encode(report),utc_now()))
            event(conn,'host.observed',report)
        return {'observed':True,'handle_count':len(handles)}

    def capacity(self) -> dict:
        with self.store.transaction() as conn:
            return self._capacity(conn)

    def _capacity(self, conn) -> dict:
        config=self.service.confirmed(conn);settings=json.loads(config['settings_json'])
        runtime=json.loads(config['runtime_json']);provider=settings['provider']
        record=conn.execute('SELECT * FROM runtime_host WHERE singleton=1').fetchone()
        if provider['handle_limit'] is None:
            return {'ok':False,'reason':'User has not configured an allowed handle limit','needs_host_observation':False}
        if not record:
            return {'ok':False,'reason':'No actual host capability/inventory receipt','needs_host_observation':True}
        observed=datetime.fromisoformat(record['observed_at'].replace('Z','+00:00'))
        if (datetime.now(timezone.utc)-observed).total_seconds()>HOST_TTL_SECONDS:
            return {'ok':False,'reason':'Host inventory is stale; refresh it before admission','needs_host_observation':True}
        host=json.loads(record['report_json'])
        if not host['usage_reporting']:
            return {'ok':False,'reason':'Provider token collector/reporting is unavailable; do not start production jobs','needs_host_observation':False}
        sessions=conn.execute("SELECT * FROM sessions WHERE state<>'closed'").fetchall()
        absent=[s['id'] for s in sessions if s['id'] not in host['handles']]
        if absent:
            return {'ok':False,'reason':'Known live sessions are absent from host inventory; reconcile, do not assume released','missing_sessions':absent,'needs_host_observation':True}
        known={s['id'] for s in sessions}
        external=max(provider['external_handles'],len(set(host['handles'])-known))
        limit=min(provider['handle_limit'],host['handle_limit'])
        # A pool definition is a reservation, not an actual model handle. Writer
        # slots are adjustable within the user upper bound; runtimes never change.
        decks=settings['presentations']
        fixed={};writers={}
        for deck in decks:
            spec=resolve_runtime(runtime,'lesson-author',presentation_id=deck['id'])
            key=(spec['model'],spec['reasoning_effort'])
            writers[key]=max(writers.get(key,0),min(settings['author_concurrency'],len(deck['units'])))
            spec=resolve_runtime(runtime,'deck-revision-author',presentation_id=deck['id'])
            key=('edit','',spec['model'],spec['reasoning_effort'],0)
            fixed[key]={'kind':'edit','channel':'','family':'author','model':spec['model'],'effort':spec['reasoning_effort'],'ordinal':0}
            for channel in CHANNELS:
                spec=resolve_runtime(runtime,'specialist-reviewer',channel=channel,presentation_id=deck['id'])
                key=('review',channel,spec['model'],spec['reasoning_effort'],0)
                fixed[key]={'kind':'review','channel':channel,'family':'reviewer','model':spec['model'],'effort':spec['reasoning_effort'],'ordinal':0}
        for job in conn.execute("SELECT j.* FROM jobs j JOIN repair_jobs r ON r.job_id=j.id JOIN repair_cases c ON c.id=r.case_id WHERE r.stage='proposal' AND c.state='diagnosing'"):
            spec=resolve_runtime(runtime,'diagnostic-reviewer',presentation_id=job['presentation'])
            key=('review','diagnosis',spec['model'],spec['reasoning_effort'],0)
            fixed[key]={'kind':'review','channel':'diagnosis','family':'reviewer','model':spec['model'],'effort':spec['reasoning_effort'],'ordinal':0}
        existing_slots=conn.execute('SELECT * FROM pool_slots').fetchall()
        attached={s['session_id'] for s in existing_slots if s['session_id']}
        # Unattached registered handles still occupy capacity; they are never
        # silently discarded. Attach them to a compatible slot to avoid counting twice.
        unattached=len(known-attached)
        cap=settings['author_concurrency']
        def definition(concurrency):
            slots=list(fixed.values())
            for (model,effort),maximum in sorted(writers.items()):
                for i in range(min(maximum,concurrency)):
                    slots.append({'kind':'write','channel':'','family':'author','model':model,'effort':effort,'ordinal':i})
            return slots
        while cap>1 and len(definition(cap))+external+provider['recovery_reserve']+unattached>limit:
            cap-=1
        slots=definition(cap)
        # Once created, a persistent no-close pool cannot be shrunk to pretend that
        # existing handles have gone away. Current admission must cover both sets.
        planned={encode(s) for s in slots}
        existing={s['key'] for s in existing_slots}
        reserved=len(planned|existing)
        required=reserved+external+provider['recovery_reserve']+unattached
        return {'ok':required<=limit,'reason':None if required<=limit else 'Full-lifecycle persistent pool cannot fit; no new handle may start',
                'limit':limit,'external_handles':external,'recovery_reserve':provider['recovery_reserve'],
                'unattached_registered_handles':unattached,'reserved_pool_handles':reserved,'required_peak_handles':required,
                'actual_author_concurrency':cap,'requested_author_concurrency':settings['author_concurrency'],
                'reviewer_slots_reserved':len([s for s in slots if s['kind']=='review']),
                'editor_slots_reserved':len([s for s in slots if s['kind']=='edit']),
                'slots':slots,'needs_host_observation':False,
                'supports_close_used':False,'supports_reset_used':False}

    def ensure_pool(self) -> dict:
        with self.store.transaction() as conn:
            report=self._capacity(conn)
            if not report['ok']:
                return report
            conn.execute('UPDATE task SET author_slots_limit=?',(report['actual_author_concurrency'],))
            for slot in report['slots']:
                conn.execute('INSERT OR IGNORE INTO pool_slots(key,kind,channel,family,model,effort,ordinal,state) VALUES(?,?,?,?,?,?,?,?)',
                             (encode(slot),slot['kind'],slot['channel'],slot['family'],slot['model'],slot['effort'],slot['ordinal'],'pending'))
            event(conn,'pool.admitted',{k:v for k,v in report.items() if k!='slots'})
        return report

    def attach(self, slot_id: int, handle: str, model: str, effort: str, receipt: str) -> dict:
        """Reconcile a creation receipt. Repeated identical replies are harmless."""
        require_text(handle,'actual provider handle');require_text(receipt,'provider creation receipt')
        with self.store.transaction() as conn:
            self.service.confirmed(conn)
            slot=conn.execute('SELECT * FROM pool_slots WHERE id=?',(slot_id,)).fetchone()
            if not slot:
                raise MPresError('Unknown slot; use the requested database slot ID')
            if (model,effort)!=(slot['model'],slot['effort']):
                raise MPresError('Provider created a different runtime from the fixed task choice')
            if slot['session_id']:
                if slot['session_id']!=handle:
                    raise MPresError('A slot already has a different actual handle')
                previous=conn.execute('SELECT receipt FROM sessions WHERE id=?',(handle,)).fetchone()
                if previous['receipt']!=receipt:
                    raise MPresError('Conflicting creation receipt')
                return {'slot_id':slot_id,'already_attached':True}
            previous=conn.execute('SELECT * FROM sessions WHERE id=?',(handle,)).fetchone()
            if previous:
                if (previous['family'],previous['model'],previous['effort'],previous['receipt']) != (slot['family'],model,effort,receipt):
                    raise MPresError('Handle identity/runtime does not match the slot')
                if previous['state']!='open':
                    raise MPresError('An unavailable session cannot be adopted')
            else:
                conn.execute('INSERT INTO sessions(id,family,model,effort,receipt,created_at) VALUES(?,?,?,?,?,?)',
                             (handle,slot['family'],model,effort,receipt,utc_now()))
            conn.execute("UPDATE pool_slots SET session_id=?,state='ready' WHERE id=?",(handle,slot_id))
            event(conn,'pool.attached',{'slot_id':slot_id,'handle':handle})
        return {'slot_id':slot_id,'already_attached':False}

    def creation_uncertain(self, slot_id: int, reason: str) -> None:
        with self.store.transaction() as conn:
            row=conn.execute('SELECT * FROM pool_slots WHERE id=?',(slot_id,)).fetchone()
            if not row or row['state'] not in {'creating','uncertain'}:
                raise MPresError('Slot has no outstanding creation')
            conn.execute("UPDATE pool_slots SET state='uncertain' WHERE id=?",(slot_id,))
            event(conn,'pool.creation_uncertain',{'slot_id':slot_id,'reason':reason})

    def outstanding(self) -> dict:
        return {'creations':self.store.rows("SELECT * FROM pool_slots WHERE state IN ('creating','uncertain')"),
                'executions':self.store.rows("SELECT id,job_id,session_id,state,provider_receipt,error FROM attempts WHERE state IN ('reserved','running','uncertain')")}

    def packet(self, job: dict, attempt_id: str) -> dict:
        config=self.settings()
        work=self.task/'.mpres'/'work'/attempt_id
        work.mkdir(parents=True,exist_ok=True)
        output=work/'output';output.mkdir(exist_ok=True)
        inputs=work/'input';inputs.mkdir(exist_ok=True)
        packet={'job_id':job['id'],'kind':job['kind'],'presentation':job['presentation'],
                'channel':job['channel'] or None,'writable_directory':str(output),
                'required_result':{'summary':'Concrete semantic outcome, not a process report'},
                'constraints':['Use provided material and verifiable public sources within the approved topic; cite event dates and sources, label hypothetical data. If tools/evidence are unavailable report the gap, never fabricate','Do not change task config, DB, evidence or runtime',
                               'No screenshots, OCR or model-vision PDF checking',
                               'Do not author workflow status, assignment files or gate receipts'],
                'input_files':[]}
        if job['plan_item_id']:
            item=self.store.rows('SELECT * FROM plan_items WHERE id=?',(job['plan_item_id'],))[0]
            packet['unit']={'id':item['unit'],'title':item['title'],'brief':item['brief']}
            for index,relative in enumerate(json.loads(item['sources_json'])):
                src=inside(self.task,relative)
                if src.suffix.lower() not in {'.md','.txt','.json','.csv'}:
                    raise MPresError('Writer references must be extracted text/data, not raw PDF or executable files')
                target=inputs/f'{index:03d}-{src.name}'
                if target.exists() and target.read_bytes()!=src.read_bytes():
                    raise MPresError('Input snapshot already differs; do not mutate an execution packet')
                if not target.exists():
                    target.write_bytes(src.read_bytes());target.chmod(0o444)
                packet['input_files'].append(str(target))
            imported=self.store.rows("SELECT * FROM artifacts WHERE presentation=? AND unit=? AND origin='import' ORDER BY created_at DESC LIMIT 1",(job['presentation'],item['unit']))
            if imported:
                packet['existing_unverified_source']=str(self.task/imported[0]['path'])
                packet['input_files'].extend(str(p) for p in (self.task/imported[0]['path']).rglob('*') if p.is_file() and (p.name in {imported[0]['entrypoint'],'theme.css'} or 'assets' in p.relative_to(self.task/imported[0]['path']).parts))
                packet['constraints'].append('Reuse existing content as a starting point; imported status is not gate approval')
        if job['input_artifact_id']:
            artifact=self.store.rows('SELECT * FROM artifacts WHERE id=?',(job['input_artifact_id'],))[0]
            path=self.task/artifact['path']
            packet['frozen_source_directory']=str(path)
            packet['input_files'].extend(str(p) for p in path.rglob('*') if p.is_file() and (p.name in {'presentation.md','theme.css'} or 'assets' in p.relative_to(path).parts))
            if job['kind']=='review':
                packet['scope']='full_frozen_deck'
                packet['required_result']['findings']='List of message, slide_ids and severity; [] is allowed'
                packet['writable_directory']=None
        if job['kind'] in {'write','edit','revise'}:
            packet['source_contract'] = {'files': ['presentation.md','assets/ as needed'], 'read_only_project_files':['theme.css'],
                'frontmatter': {'marp': True, 'theme': 'mathist-academic', 'paginate': True, 'size':'16:9', 'math':'mathjax'},
                'slide_id': 'stable unique comment <!-- slide-id: pNN-lNN-sNN -->',
                'classes': ['core','support'], 'no_process_documents': True, 'raw_html':'forbidden', 'local_style':'forbidden'}
            packet['constraints'].extend(['Quote size: "16:9" in YAML',
                'Use assets/<unit-id>/ paths. Never edit CSS/theme/frontmatter layout. No raw HTML, inline SVG or image size/background directives. Split/rewrite content to fit fixed layout. Run mpres source check on output before submission'])
            if job['input_artifact_id']:
                from .files import writable
                for src in path.rglob('*'):
                    if src.is_file() and (src.name in {'presentation.md'} or 'assets' in src.relative_to(path).parts):
                        target=output/src.relative_to(path)
                        if not target.exists():
                            target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(src.read_bytes())
                writable(output)
            from mpres.source_policy import install_theme
            install_theme(output)
        if not job['plan_item_id']:
            packet['course_outline'] = self.store.rows('SELECT unit,title,brief FROM plan_items WHERE presentation=? ORDER BY ordinal',(job['presentation'],))
        if job['input_artifact_id']:
            from .quality import Quality
            from .semantic import gate_excerpt
            q = Quality(self.task)
            failed = self.store.rows("SELECT detail_json FROM gate_runs WHERE artifact_id=? AND state='failed' ORDER BY sequence DESC LIMIT 1", (job['input_artifact_id'],))
            if failed:
                packet['mechanical_findings'] = gate_excerpt(json.loads(failed[0]['detail_json']))
            if job['kind']=='review':
                full_gate = q.latest(job['input_artifact_id'],'full')
                if full_gate and full_gate['state']=='passed':
                    pdf = inside(self.task,full_gate['pdf_path'])
                    packet['frozen_pdf'] = str(pdf)
                    packet['input_files'].append(str(pdf))
                    packet['mechanical_evidence'] = gate_excerpt(json.loads(full_gate['detail_json']))
                packet['required_result']['findings'] = 'Exactly message, slide_ids (existing canonical IDs), severity (minor/major/critical); [] permitted'
            if job['kind']=='revise':
                decks=self.store.rows('SELECT frozen_id FROM decks WHERE presentation=?',(job['presentation'],))
                frozen=decks[0]['frozen_id'] if decks else job['input_artifact_id']
                packet['findings']=[{'finding_id':r['id'], 'channel':r['channel'], **json.loads(r['detail_json'])} for r in self.store.rows('SELECT * FROM findings WHERE artifact_id=?',(frozen,))]
                packet['required_result']['resolutions'] = 'One per finding: finding_id, status addressed|needs_decision, explanation; retain frozen slide IDs'
        from .repairs import Repairs
        repair=Repairs(self.task).context(job)
        if repair:
            packet['repair_scope']=repair
            packet['constraints'].append('Preserve unrelated correct material and original slide IDs. Apply only the user-confirmed issue family and related forms, never unrelated polishing.')
            if job['kind']=='diagnose':
                packet['writable_directory']=None
                packet['scope']='read_only_problem_expansion_not_authorized_repair'
                packet['required_result']['expansion']='Actively describe variants AND related problems; for each give detection/correction guidance. Distinguish observed from possible. Include non-goals, acceptance criteria and evidence/source needs. This is a proposal for user confirmation, not authorization.'
            else:
                packet['required_result']['repair_checks']='Every confirmed variant and related problem: problem_id, addressed|not_found|needs_decision, explanation, actual slide_ids. Independently inspect the whole selected deck; do not accept the author readback as proof.'
        from .semantic import schema, result_schema_name, guidance
        from .feedback import Feedback
        packet['historical_feedback'] = Feedback(self.task).briefing(attempt_id)['feedback']
        packet['as_of_date'] = datetime.now(timezone.utc).date().isoformat()
        packet['required_result']['feedback_checks'] = 'One disposition for every historical feedback id/version, with actual slide excerpts; issue is not a pass; no automatic not_applicable by channel'
        packet['result_schema'] = schema(result_schema_name(job['kind']))
        packet['semantic_guidance'] = guidance(self.root if hasattr(self, 'root') else self.task.parent.parent, job['kind'])
        text_suffixes={'.md','.css','.txt','.json','.yaml','.yml','.csv','.svg'}
        packet['attachment_bytes']=sum(Path(p).stat().st_size for p in set(packet['input_files']) if Path(p).suffix.lower() not in text_suffixes)
        count=len(encode(packet).encode('utf-8'))+sum(Path(p).stat().st_size for p in set(packet['input_files']) if Path(p).suffix.lower() in text_suffixes)
        budget=config.get('context_budget_bytes',262144)
        if count>budget:
            raise MPresError(f'Context packet is {count} bytes, over confirmed budget {budget}; reduce authorized input, not runtime')
        packet['context_bytes']=count
        packet['sandbox_enforced_by_project']=False
        return packet

    def _blocked_packet(self, attempt_id: str, error: Exception) -> None:
        # This path is called strictly before external dispatch. It can safely
        # release the local claim, unlike an ambiguous external launch failure.
        with self.store.transaction() as conn:
            a=conn.execute('SELECT * FROM attempts WHERE id=?',(attempt_id,)).fetchone()
            conn.execute("UPDATE attempts SET state='failed',finished_at=?,error=? WHERE id=?",(utc_now(),str(error),attempt_id))
            conn.execute("UPDATE jobs SET state='blocked' WHERE id=?",(a['job_id'],))
            conn.execute('INSERT INTO decisions(kind,presentation,detail_json) SELECT ?,presentation,? FROM jobs WHERE id=?',
                         ('input-boundary',encode({'error':str(error),'job_id':a['job_id']}),a['job_id']))
            event(conn,'packet.blocked_before_dispatch',{'error':str(error)},a['job_id'])

    def tick(self) -> dict:
        """Reserve and return exact operations, never a narrative launch plan.

        Repeated ticks do not issue creating slots or claimed jobs again. The bridge
        must reconcile outstanding requests rather than treating them as new work.
        """
        from .workflow import Workflow
        workflow = Workflow(self.task)
        workflow_report = workflow.advance()
        full = workflow_report['enabled']
        if workflow_report.get('delivery_package', {}).get('state') == 'failed':
            return {'status': 'blocked', 'reason': 'Delivery ZIP could not be generated; retry packaging, not content production',
                    'requests': [], 'workflow': workflow_report, 'release_pipeline_enabled': full}
        from .repairs import Repairs
        repairs=Repairs(self.task)
        proposals=repairs.pending_presentations()
        repair_status=repairs.status()
        task_status = self.service.status()['status']
        if task_status in {'paused', 'completed'} and not proposals:
            return {'status': 'awaiting_confirmation' if repair_status['awaiting_confirmation'] else task_status, 'repairs':repair_status, 'requests': [], 'workflow': workflow_report, 'release_pipeline_enabled': full}
        if full and not (workflow.allowed() | proposals):
            return {'status': 'blocked', 'requests': [], 'workflow': workflow_report, 'release_pipeline_enabled': True}
        capacity=self.ensure_pool()
        if not capacity['ok']:
            return {'status':'blocked','capacity':capacity,'requests':[]}
        outstanding=self.outstanding()
        if any(x['state']=='uncertain' for x in outstanding['creations']+outstanding['executions']):
            return {'status':'blocked','reason':'Uncertain external execution requires receipt reconciliation, not a retry',
                    'capacity':{k:v for k,v in capacity.items() if k!='slots'},'requests':[],'outstanding':outstanding}
        self.service.materialize()
        from .quality import Quality
        quality = Quality(self.task)
        for artifact in self.store.rows("SELECT a.id FROM artifacts a WHERE a.origin='submission' AND NOT EXISTS (SELECT 1 FROM gate_runs g WHERE g.artifact_id=a.id AND g.level='source')"):
            quality.inspect(artifact['id'])
        admitted_presentations = (workflow.allowed() | proposals) if full else None
        requests=[]
        with self.store.transaction() as conn:
            jobs=conn.execute("SELECT j.* FROM jobs j LEFT JOIN plan_items p ON p.id=j.plan_item_id WHERE j.state='queued' AND j.family IS NOT NULL AND NOT EXISTS (SELECT 1 FROM dependencies d JOIN jobs x ON x.id=d.needs_id WHERE d.job_id=j.id AND x.state<>'succeeded') ORDER BY CASE j.kind WHEN 'revise' THEN 0 WHEN 'review' THEN 1 WHEN 'edit' THEN 2 ELSE 3 END,p.ordinal,j.rowid").fetchall()
            deck_order=[d['id'] for d in json.loads(self.service.confirmed(conn)['settings_json'])['presentations']]
            unfinished={r[0] for r in conn.execute("SELECT DISTINCT presentation FROM jobs WHERE kind='write' AND state<>'succeeded'")}
            current=next((i for i,p in enumerate(deck_order) if p in unfinished),len(deck_order))
            allowed=admitted_presentations if full else set(deck_order[current:current+2])
            active_writes=conn.execute("SELECT count(*) FROM attempts a JOIN jobs j ON j.id=a.job_id WHERE j.kind='write' AND a.state IN ('reserved','running','uncertain')").fetchone()[0]
            pending_creates=conn.execute("SELECT count(*) FROM pool_slots WHERE kind='write' AND state IN ('creating','uncertain')").fetchone()[0]
            for job in jobs:
                if full and job['presentation'] not in allowed:
                    continue
                if job['kind']=='write' and (job['presentation'] not in allowed or active_writes+pending_creates>=capacity['actual_author_concurrency']):
                    continue
                expected=self.service.expected_runtime(conn,job)
                kind='review' if job['kind'] in {'review','diagnose'} else 'write' if job['kind']=='write' else 'edit'
                channel=('diagnosis' if job['kind']=='diagnose' else job['channel']) if kind=='review' else ''
                slots=conn.execute('SELECT * FROM pool_slots WHERE kind=? AND channel=? AND model=? AND effort=? ORDER BY ordinal,id',
                                   (kind,channel,expected['model'],expected['reasoning_effort'])).fetchall()
                for slot in slots:
                    if slot['state']=='pending':
                        request={'operation':'create','request_id':f"slot-{slot['id']}",'slot_id':slot['id'],
                                 'runtime':{'family':slot['family'],'model':slot['model'],'reasoning_effort':slot['effort']}}
                        conn.execute("UPDATE pool_slots SET state='creating' WHERE id=?",(slot['id'],))
                        event(conn,'provider.create_requested',request)
                        requests.append(request)
                        if kind=='write': pending_creates+=1
                        break
        # Bound execution uses Service.bind's own short transaction. Races between
        # runners converge through database uniqueness and queued-state checks.
        for job in sorted(self.service.jobs(), key=lambda j: {'revise':0,'review':1,'edit':2,'write':3}.get(j['kind'],4)):
            if (full and job['presentation'] not in allowed) or job['state']!='queued' or not job['family'] or (job['kind']=='write' and job['presentation'] not in allowed):
                continue
            with self.store.transaction() as conn:
                active=conn.execute("SELECT count(*) FROM attempts a JOIN jobs j ON j.id=a.job_id WHERE j.kind='write' AND a.state IN ('reserved','running','uncertain')").fetchone()[0]
                creating=conn.execute("SELECT count(*) FROM pool_slots WHERE kind='write' AND state IN ('creating','uncertain')").fetchone()[0]
                if job['kind']=='write' and active+creating>=capacity['actual_author_concurrency']:
                    continue
                expected=self.service.expected_runtime(conn,job)
                kind='review' if job['kind'] in {'review','diagnose'} else 'write' if job['kind']=='write' else 'edit'
                channel=('diagnosis' if job['kind']=='diagnose' else job['channel']) if kind=='review' else ''
                slots=conn.execute("SELECT s.* FROM pool_slots p JOIN sessions s ON s.id=p.session_id WHERE p.state='ready' AND p.kind=? AND p.channel=? AND p.model=? AND p.effort=? ORDER BY p.ordinal,p.id",
                                   (kind,channel,expected['model'],expected['reasoning_effort'])).fetchall()
                handle=next((s['id'] for s in slots if self.service.eligible(conn,job,s)),None)
            if handle is None:
                continue
            try:
                attempt=self.service.bind(job['id'],handle)
            except MPresError:
                continue
            try:
                request=self.execution_request(job,attempt)
                if request: requests.append(request)
            except Exception as exc:
                self._blocked_packet(attempt['id'],exc)
        for attempt in self.store.rows("SELECT a.* FROM attempts a JOIN attempt_briefings b ON b.attempt_id=a.id WHERE a.state='reserved' AND b.acknowledgement_json IS NOT NULL AND b.run_dispatched=0"):
            try:
                request=self.execution_request(self.service.job(attempt['job_id']),attempt)
                if request: requests.append(request)
            except Exception as exc:
                self._blocked_packet(attempt['id'],exc)
        return {'status':'requests_ready' if requests else 'idle_or_waiting','capacity':{k:v for k,v in capacity.items() if k!='slots'},'requests':requests,'outstanding':self.outstanding(),
                'release_pipeline_enabled':full, 'workflow':workflow_report}

    def execution_request(self, job: dict, attempt: dict) -> dict | None:
        from .feedback import Feedback
        brief=Feedback(self.task).briefing(attempt['id'])
        operation='run' if brief['acknowledged'] else 'brief'
        flag='run_dispatched' if operation=='run' else 'brief_dispatched'
        if brief[flag]: return None
        with self.store.transaction() as conn:
            runtime=self.service.expected_runtime(conn,job)
        if operation=='run':
            packet=self.packet(job,attempt['id'])
        else:
            packet={'kind':job['kind'],'presentation':job['presentation'],
                    'channel':job['channel'],'historical_feedback':brief['feedback'],
                    'instructions':'Before any writing/review: restate how each feedback item will be applied or checked in this job. Return readback [{id,version,approach}]. Do not edit source or produce findings yet.',
                    'writable_directory':None}
            if job['plan_item_id']:
                packet['unit']=self.store.rows('SELECT unit,title,brief FROM plan_items WHERE id=?',(job['plan_item_id'],))[0]
            from .repairs import Repairs
            scope=Repairs(self.task).context(job)
            if scope: packet['repair_scope']=scope
        if len(encode(packet).encode()) > self.settings().get('context_budget_bytes',262144):
            raise MPresError('Historical feedback exceeds the context budget; never silently truncate it')
        with self.store.transaction() as conn:
            current=conn.execute('SELECT * FROM attempt_briefings WHERE attempt_id=?',(attempt['id'],)).fetchone()
            if current[flag]: return None
            conn.execute('UPDATE attempt_briefings SET '+flag+'=1 WHERE attempt_id=?',(attempt['id'],))
            event(conn,'provider.'+operation+'_requested',{'attempt_id':attempt['id'],'context_bytes':packet.get('context_bytes',len(encode(packet).encode()))},job['id'])
        return {'operation':operation,'request_id':('brief:' if operation=='brief' else '')+attempt['id'],
                'attempt_id':attempt['id'],'session_id':attempt['session_id'],'runtime':runtime,'packet':packet}

    def accept(self, request: dict, response: dict) -> dict:
        if not isinstance(response,dict):
            raise MPresError('Provider response must be a JSON object')
        if request['operation']=='create':
            return self.attach(request['slot_id'],response['handle'],response['model'],response['reasoning_effort'],response['receipt'])
        if request['operation']=='brief':
            from .feedback import Feedback
            attempt_id=request['attempt_id']
            job=self.service.job(self.service.attempt(attempt_id)['job_id'])
            with self.store.transaction() as conn: expected=self.service.expected_runtime(conn,job)
            actual=response.get('runtime',{})
            if (actual.get('model'),actual.get('reasoning_effort'))!=(expected['model'],expected['reasoning_effort']):
                raise MPresError('Pre-work readback runtime differs from the confirmed profile')
            if response.get('source_dir') is not None:
                raise MPresError('Pre-work readback may not submit source')
            usage=response.get('usage')
            if not isinstance(usage,list) or not usage: raise MPresError('Pre-work readback requires genuine usage receipts')
            for call in usage:
                self.service.record_usage(attempt_id,call['call_id'],call['counters'])
            result=Feedback(self.task).acknowledge(attempt_id,response.get('readback'),response.get('receipt'))
            # A late, exact readback can resolve an uncertain *brief* only. A lost
            # content execution still follows the existing receipt reconciliation.
            with self.store.transaction() as conn:
                a=conn.execute('SELECT * FROM attempts WHERE id=?',(attempt_id,)).fetchone()
                b=conn.execute('SELECT run_dispatched FROM attempt_briefings WHERE attempt_id=?',(attempt_id,)).fetchone()
                if a['state']=='uncertain' and not a['provider_receipt'] and not b['run_dispatched']:
                    conn.execute("UPDATE attempts SET state='reserved',error=NULL WHERE id=?",(attempt_id,))
                    conn.execute("UPDATE sessions SET state='open' WHERE id=?",(a['session_id'],))
            return result
        if request['operation']!='run':
            raise MPresError('Unknown external operation')
        attempt_id=request['attempt_id']
        self.service.started(attempt_id,require_text(response.get('receipt'),'execution receipt'))
        job=self.service.job(self.service.attempt(attempt_id)['job_id'])
        with self.store.transaction() as conn:
            expected=self.service.expected_runtime(conn,job)
        actual=response.get('runtime')
        if not isinstance(actual,dict) or (actual.get('model'),actual.get('reasoning_effort')) != (expected['model'],expected['reasoning_effort']):
            raise MPresError('Provider execution runtime differs or is unavailable; do not accept a fallback model')
        result=response.get('result')
        source=None
        if response.get('source_dir') is not None:
            work=self.task/'.mpres'/'work'/attempt_id
            source=inside(work,response['source_dir'])
            if not source.is_relative_to(work/'output'):
                raise MPresError('Provider may submit only its own output subtree')
        # Provider fields are authoritative counters, not inferred prices. Missing
        # telemetry remains visibly absent; task creation is already timestamped.
        usage=response.get('usage')
        if not isinstance(usage,list) or not usage:
            raise MPresError('Provider promised token reporting but supplied no call receipts; reconcile this execution')
        for call in usage:
            if not isinstance(call,dict) or not isinstance(call.get('counters'),dict):
                raise MPresError('Malformed provider usage receipt')
            self.service.record_usage(attempt_id,call['call_id'],call['counters'])
        return self.service.submit(attempt_id,result,source=source)

    def invoke(self, payload: dict) -> dict:
        settings=self.settings();provider=settings['provider']
        if provider['mode']!='command' or not provider['command']:
            raise MPresError('No command adapter configured; use bridge requests and receipt submission')
        process=subprocess.run(provider['command'],input=encode(payload),text=True,
                               stdout=subprocess.PIPE,stderr=subprocess.PIPE,cwd=self.task,
                               timeout=settings.get('provider_timeout_seconds',1200),shell=False)
        if process.returncode:
            raise MPresError(f'Provider command exited {process.returncode}: {process.stderr[-2000:]}')
        return json.loads(process.stdout)

    def run_once(self) -> dict:
        """Command adapter mode. External I/O runs with no SQLite write lock held."""
        host=self.invoke({'operation':'capabilities'})
        self.observe_host(host)
        tick=self.tick()
        def execute(request):
            started=time.monotonic()
            try:
                response=self.invoke(request)
                result=self.accept(request,response)
                return {'request_id':request['request_id'],'status':'accepted','result':result}
            except Exception as exc:
                if request['operation']=='create':self.creation_uncertain(request['slot_id'],str(exc))
                else:self.service.uncertain(request['attempt_id'],str(exc))
                return {'request_id':request['request_id'],'status':'uncertain','error':str(exc)}
            finally:
                with self.store.transaction() as conn:
                    event(conn,'provider.duration',{'request_id':request['request_id'],'seconds':time.monotonic()-started})
        with ThreadPoolExecutor(max_workers=max(1,len(tick['requests']))) as pool:
            results=list(pool.map(execute,tick['requests']))
        return {**tick,'results':results}

    def run(self, cycles: int = 100, interval: float = 1) -> dict:
        """Foreground runner until idle/blocked; no model-based periodic observer."""
        if cycles<1 or interval<0:
            raise MPresError('Invalid runner cycle bounds')
        last={}
        for _ in range(cycles):
            last=self.run_once()
            if not last['requests'] or any(x['status']=='uncertain' for x in last.get('results',[])):
                break
            if interval:time.sleep(interval)
        return last
