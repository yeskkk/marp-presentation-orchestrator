"""Sequential student reading on the existing audience review job/session.

Intermediate semantic results live in SQLite, not task process documents. The
host sees one bounded step at a time. Recorded coverage proves packet delivery,
not human cognition; final findings still require independent semantic judgment.
"""
from __future__ import annotations
import json
from pathlib import Path
from mpres.marp_source import parse_deck
from mpres.util import MPresError, utc_now
from .store import encode, event
from .service import Service, require_text

CHUNK_SLIDES = 12
STEP_BUDGET = 48000


def applies(job):
    return job['kind']=='review' and job['channel']=='audience'


class Audience:
    def __init__(self, task: Path):
        self.service=Service(task);self.task=self.service.task;self.store=self.service.store

    def _slides(self, job):
        row=self.store.rows('SELECT path FROM artifacts WHERE id=?',(job['input_artifact_id'],))
        if not row:raise MPresError('Audience review requires an immutable source revision')
        source=self.task/row[0]['path']
        return source,parse_deck(source/'presentation.md').slides

    def ensure(self, attempt_id):
        attempt=self.service.attempt(attempt_id);job=self.service.job(attempt['job_id'])
        if not applies(job):return
        source,slides=self._slides(job)
        if not slides or any(not s.slide_id for s in slides):raise MPresError('Audience input has missing slide IDs')
        chunks=[];current=[];used=0
        for slide in slides:
            cost=len(slide.source.encode('utf-8'))
            if cost>STEP_BUDGET:raise MPresError('One student slide exceeds bounded reading input; split the source, do not truncate')
            if current and (len(current)>=CHUNK_SLIDES or used+cost>STEP_BUDGET):
                chunks.append(current);current=[];used=0
            current.append(slide.slide_id);used+=cost
        if current:chunks.append(current)
        with self.store.transaction() as conn:
            self.service.confirmed(conn)
            for seq,(phase,ids) in enumerate((phase,ids) for phase in ('student','production_language') for ids in chunks):
                conn.execute('INSERT OR IGNORE INTO audience_steps(attempt_id,sequence,phase,artifact_id,slide_ids_json,state) VALUES(?,?,?,?,?,\'pending\')',
                             (attempt_id,seq,phase,job['input_artifact_id'],encode(ids)))

    def rows(self, attempt_id):
        return self.store.rows('SELECT * FROM audience_steps WHERE attempt_id=? ORDER BY sequence',(attempt_id,))

    def request(self, job, attempt, runtime):
        self.ensure(attempt['id'])
        rows=self.rows(attempt['id']);next_row=next((r for r in rows if r['state']!='completed'),None)
        if next_row is None:return None
        if next_row['state']=='dispatched':return None
        source,slides=self._slides(job);targets=json.loads(next_row['slide_ids_json'])
        by_id={s.slide_id:s for s in slides}
        from mpres.source_policy import METADATA
        content=[{'slide_id':sid,'markdown':METADATA.sub('',by_id[sid].source).strip()} for sid in targets]
        # Only referenced teaching assets, never producer checks, full PDF, DB or
        # author result paths. No pretending an already-briefed session is blind.
        from mpres.source_policy import inspect_markdown
        from .files import inside
        from urllib.parse import unquote
        assets=[]
        for item in content:
            for image in inspect_markdown(item['markdown'])['images']:
                path=inside(source,unquote(image['src']))
                if str(path) not in assets:assets.append(str(path))
        prior=[json.loads(r['result_json'])['summary'] for r in rows if r['state']=='completed' and r['phase']==next_row['phase']]
        instruction = (
            'Read these slides sequentially as a student with the stated prerequisites. Explain what can be learned and identify concrete confusion, missing conditions, undefined symbols or unexplained diagram/formula links. Do not perform all five specialist roles.'
            if next_row['phase']=='student' else
            'Read ONLY for audience/production voice: find compliance self-praise, author-to-manager status reports and requests for production inputs. Preserve legitimate modeling assumptions, simulation disclosures and limitations that affect what students learn. Cite actual text, not keyword matches.'
        )
        from .semantic import schema
        packet={'kind':'review','channel':'audience','presentation':job['presentation'],
                'phase':next_row['phase'],'sequence':next_row['sequence'],'artifact_id':job['input_artifact_id'],
                'slides':content,'read_slide_ids':targets,'input_files':assets,'writable_directory':None,
                'instructions':instruction,'continuity':prior[-2:],
                'learner_context':'Use the confirmed audience/prerequisites; do not rely on author self-evaluation.',
                'result_schema':schema('review-result')['$defs']['audience_step'],
                'limitations':'Historical feedback was briefed earlier; this is not a blind experiment or real student study.'}
        # Audience/prerequisites should be read from confirmed TASK, not author
        # self-checks. Keep this context bounded rather than injecting task records.
        with self.store.transaction() as conn:
            cfg=self.service.confirmed(conn);settings=json.loads(cfg['settings_json'])
            packet['confirmed_task_brief']=cfg['task_text']
            budget=settings.get('context_budget_bytes',262144)
        if len(encode(packet).encode())+sum(Path(p).stat().st_size for p in assets if Path(p).suffix.lower() in {'.svg','.txt','.json'})>budget:raise MPresError('Audience step exceeds confirmed context budget; no silent truncation')
        with self.store.transaction() as conn:
            row=conn.execute('SELECT state FROM audience_steps WHERE attempt_id=? AND sequence=?',(attempt['id'],next_row['sequence'])).fetchone()
            if row['state']!='pending':return None
            conn.execute("UPDATE audience_steps SET state='dispatched' WHERE attempt_id=? AND sequence=?",(attempt['id'],next_row['sequence']))
            event(conn,'audience.step_requested',{'attempt_id':attempt['id'],'sequence':next_row['sequence'],'phase':next_row['phase'],'artifact_id':job['input_artifact_id'],'slide_ids':targets},job['id'])
        return {'operation':'audience_step','request_id':f"audience:{attempt['id']}:{next_row['sequence']}",
                'attempt_id':attempt['id'],'sequence':next_row['sequence'],'session_id':attempt['session_id'],'runtime':runtime,'packet':packet}

    def pending(self, attempt_id):
        self.ensure(attempt_id)
        return any(r['state']!='completed' for r in self.rows(attempt_id))

    def accept(self, request, response):
        attempt=self.service.attempt(request['attempt_id']);job=self.service.job(attempt['job_id'])
        if not applies(job):raise MPresError('Not an audience review attempt')
        if request.get('request_id')!=f"audience:{attempt['id']}:{request.get('sequence')}":
            raise MPresError('Audience request identity mismatch')
        with self.store.transaction() as conn:
            self.service.confirmed(conn);expected=self.service.expected_runtime(conn,job)
        actual=response.get('runtime',{})
        if (actual.get('model'),actual.get('reasoning_effort'))!=(expected['model'],expected['reasoning_effort']):
            raise MPresError('Audience runtime differs from confirmed configuration')
        if response.get('source_dir') is not None:raise MPresError('Student reading may not edit source')
        receipt=require_text(response.get('receipt'),'Audience step receipt')
        rows=self.rows(attempt['id']);row=next((r for r in rows if r['sequence']==request['sequence']),None)
        if not row or row['state'] not in {'dispatched','completed'}:raise MPresError('Audience step was not dispatched')
        if any(r['state']!='completed' for r in rows if r['sequence']<row['sequence']):raise MPresError('Audience steps must be sequential')
        result=response.get('result');from jsonschema import Draft202012Validator
        from .semantic import schema
        errors=list(Draft202012Validator(schema('review-result')['$defs']['audience_step']).iter_errors(result))
        if errors:raise MPresError('Invalid audience step result: '+errors[0].message)
        if result['phase']!=row['phase'] or result['read_slide_ids']!=json.loads(row['slide_ids_json']):
            raise MPresError('Audience phase/coverage does not match the exact dispatched pages')
        _,slides=self._slides(job);text={s.slide_id:s.source for s in slides};allowed=set(result['read_slide_ids'])
        for note in result['observations']:
            if note['slide_id'] not in allowed or not note['quote'].strip() or note['quote'] not in text[note['slide_id']]:
                raise MPresError('Audience evidence is outside the dispatched source or invented')
        for finding in result['findings']:
            if not set(finding['slide_ids'])<=allowed:raise MPresError('Audience finding cites an unread page')
        calls=response.get('usage')
        if not isinstance(calls,list) or not calls:raise MPresError('Audience steps require real usage receipts')
        # Namespace per-step IDs; providers may reuse a local call ID in a session.
        for call in calls:self.service.record_usage(attempt['id'],f"audience:{row['sequence']}:{call['call_id']}",call['counters'])
        encoded=encode(result)
        with self.store.transaction() as conn:
            current=conn.execute('SELECT * FROM audience_steps WHERE attempt_id=? AND sequence=?',(attempt['id'],row['sequence'])).fetchone()
            if current['state']=='completed':
                if (current['receipt'],current['result_json'])!=(receipt,encoded):raise MPresError('Conflicting audience replay')
                return {'already_recorded':True,'sequence':row['sequence']}
            a=conn.execute('SELECT * FROM attempts WHERE id=?',(attempt['id'],)).fetchone()
            if a['state'] not in {'reserved','uncertain'}:raise MPresError('Audience attempt is no longer accepting steps')
            conn.execute("UPDATE audience_steps SET state='completed',receipt=?,result_json=?,completed_at=? WHERE attempt_id=? AND sequence=?",(receipt,encoded,utc_now(),attempt['id'],row['sequence']))
            b=conn.execute('SELECT run_dispatched FROM attempt_briefings WHERE attempt_id=?',(attempt['id'],)).fetchone()
            if a['state']=='uncertain' and not a['provider_receipt'] and not b['run_dispatched']:
                conn.execute("UPDATE attempts SET state='reserved',error=NULL WHERE id=?",(attempt['id'],))
                conn.execute("UPDATE sessions SET state='open' WHERE id=?",(attempt['session_id'],))
            event(conn,'audience.step_completed',{'attempt_id':attempt['id'],'sequence':row['sequence'],'phase':row['phase'],'slide_ids':result['read_slide_ids']},job['id'])
        return {'already_recorded':False,'sequence':row['sequence']}

    def final_context(self, attempt_id):
        if self.pending(attempt_id):raise MPresError('Student reading and production-language passes must finish before final review')
        return [{'phase':r['phase'],'sequence':r['sequence'],**{k:v for k,v in json.loads(r['result_json']).items() if k!='observations'}} for r in self.rows(attempt_id)]

    def require_final(self, attempt_id, result):
        context=self.final_context(attempt_id)
        findings=result.get('findings',[])
        for step in context:
            for earlier in step['findings']:
                if earlier not in findings:raise MPresError('Final audience findings dropped an earlier student/production-language issue')
