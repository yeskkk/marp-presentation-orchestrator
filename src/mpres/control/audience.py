"""Sequential student reading on the existing audience review job/session.

Intermediate semantic results live in SQLite, not task process documents. The
host sees one bounded step at a time. Recorded coverage proves packet delivery,
not human cognition; final findings still require independent semantic judgment.
"""
from __future__ import annotations
import json
import copy
import re
from pathlib import Path
from mpres.marp_source import parse_deck
from mpres.util import MPresError, utc_now
from .store import encode, event
from .service import Service, require_text

CHUNK_SLIDES = 12
STEP_BUDGET = 48000


# These signals request a semantic deletion counterfactual; they never delete or
# fail source content by keyword. Code/math examples are excluded by the parser.
_ATTENTION_SIGNALS = (
    ('planning-field', re.compile(r'^(?:先修|预备知识|核心|扩展|教学目标|目标|本课目标)\s*[:：]|核心.*\d+.*分钟')),
    ('producer-voice', re.compile(r'教学假设|教学模拟|本页已|已按.*要求|资料缺口|另行提供|已明确标|本课使用.*规范术语')),
    ('invented-misunderstanding', re.compile(r'(?:并不|不)(?:代表|意味着|等于|表示)')),
    ('internal-source', re.compile(r'\.txt.*(?:行|L\d|:\d)|L\d+[-–]L?\d+|^(?:阅读|参考文献|引用材料|资料来源)\s*[:：]')),
    ('method-slogan', re.compile(r'(?:结论|总结).*(?:论证|证明|讨论|分析)|(?:证明|论证).*(?:保证|确保)')),
)


def attention_candidates(slides: list[dict]) -> list[dict]:
    from mpres.source_policy import parser
    output=[]
    for slide in slides:
        for index, token in enumerate(parser().parse(slide['markdown'])):
            if token.type!='inline' or not token.map:
                continue
            plain=''.join(child.content for child in token.children or [] if child.type=='text')
            reasons=[kind for kind, pattern in _ATTENTION_SIGNALS if pattern.search(plain)]
            if reasons:
                output.append({'candidate_id':f"{slide['slide_id']}@{token.map[0]+1}:{index}",
                               'slide_id':slide['slide_id'],'quote':token.content[:1200],
                               'signals':reasons,
                               'question':'删去/改写这段后，当前数学学习具体损失什么？关键词不是定罪，给有内容的保留或删改理由。'})
    return output


def validate_attention(result: dict, candidates: list[dict]) -> None:
    if not candidates and 'attention_checks' not in result:
        return
    checks=result.get('attention_checks')
    if not isinstance(checks,list):
        raise MPresError('attention_checks must address each proposed student-attention candidate')
    expected={r['candidate_id']:r for r in candidates}; seen=set()
    generic={'不是自夸','属于教学内容','可以避免误解','有利于学习','符合要求',
             '这是教学内容','会降低学习效果','无损失但属于教学内容','not self praise','teaching content'}
    for row in checks:
        key=row['candidate_id']
        if key not in expected or key in seen:
            raise MPresError('Unknown or duplicate attention candidate')
        seen.add(key)
        loss=require_text(row['learning_loss_if_removed'],'Concrete learning-loss counterfactual')
        require_text(row['reason'],'Concrete attention decision')
        if loss.strip(' .。！!;；').lower() in generic:
            raise MPresError('A generic teaching/compliance label is not a learning-loss counterfactual')
        index=row['finding_index']
        if row['disposition']=='keep':
            if index is not None:
                raise MPresError('A kept attention candidate must not point to a removal finding')
        elif (type(index) is not int or index<0 or index>=len(result['findings']) or
              expected[key]['slide_id'] not in result['findings'][index]['slide_ids']):
            raise MPresError('Attention removal/rewrite must route to a finding on the same slide')
    if seen!=set(expected):
        raise MPresError('Attention checks omitted a candidate; do not silently declare the page acceptable')


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
            if not conn.execute('SELECT 1 FROM audience_steps WHERE attempt_id=?',(attempt_id,)).fetchone():
                event(conn,'audience.contract',{'attempt_id':attempt_id,'version':2},job['id'])
            for seq,(phase,ids) in enumerate((phase,ids) for phase in ('student','production_language') for ids in chunks):
                conn.execute('INSERT OR IGNORE INTO audience_steps(attempt_id,sequence,phase,artifact_id,slide_ids_json,state) VALUES(?,?,?,?,?,\'pending\')',
                             (attempt_id,seq,phase,job['input_artifact_id'],encode(ids)))

    def rows(self, attempt_id):
        return self.store.rows('SELECT * FROM audience_steps WHERE attempt_id=? ORDER BY sequence',(attempt_id,))

    def protocol(self, attempt_id):
        rows=self.store.rows("SELECT detail_json FROM events WHERE kind='audience.contract' AND json_extract(detail_json,'$.attempt_id')=? ORDER BY id DESC LIMIT 1",(attempt_id,))
        return json.loads(rows[0]['detail_json'])['version'] if rows else 1

    def guidance_introduced(self, attempt_id):
        from .guidance import GUIDANCE_VERSION
        return bool(self.store.rows(
            "SELECT id FROM events WHERE kind IN ('audience.step_requested','provider.run_requested') "
            "AND json_extract(detail_json,'$.attempt_id')=? "
            "AND json_extract(detail_json,'$.semantic_guidance_version')=? "
            "AND json_extract(detail_json,'$.role_introduction')=1 LIMIT 1",
            (attempt_id, GUIDANCE_VERSION)))

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
            'Read as a student, not a rubric auditor. State the concrete learner question and learning gained; find missing meanings, unsupported transitions and unnecessary cognitive load. An example is an entry, not the definition of the entire course. Do not perform all five specialist roles.'
            if next_row['phase']=='student' else
            'Judge ATTENTION VALUE, not just compliance self-praise. For each candidate apply the deletion counterfactual: what specific current mathematical learning would be lost? Prerequisite lists, timing/core labels, isolated quotations, TXT line citations and invented misunderstandings are not justified merely by being educational. Preserve real conditions and necessary attribution. Recommend deletions/rewrites as findings; never edit the source. No positive observations quota.'
        )
        from .semantic import schema
        protocol=self.protocol(attempt['id'])
        candidates=attention_candidates(content) if protocol>=2 and next_row['phase']=='production_language' else []
        result_schema=copy.deepcopy(schema('review-result')['$defs']['audience_step'])
        if candidates:
            result_schema['required'].append('attention_checks')
        packet={'kind':'review','channel':'audience','presentation':job['presentation'],
                'phase':next_row['phase'],'sequence':next_row['sequence'],'artifact_id':job['input_artifact_id'],
                'slides':content,'read_slide_ids':targets,'input_files':assets,'writable_directory':None,
                'instructions':instruction,'continuity':prior[-2:],
                'learner_context':'Use the confirmed audience/prerequisites; do not rely on author self-evaluation.',
                'result_schema':result_schema,'reading_protocol':protocol,
                'attention_candidates':candidates,
                'limitations':'Historical feedback was briefed earlier; this is not a blind experiment or real student study.'}
        from .guidance import audience_guidance, attach_guidance
        attach_guidance(packet, audience_guidance(self.task.parent.parent, next_row['phase'], introduce=not self.guidance_introduced(attempt['id'])))
        # Audience/prerequisites should be read from confirmed TASK, not author
        # self-checks. Keep this context bounded rather than injecting task records.
        with self.store.transaction() as conn:
            cfg=self.service.confirmed(conn);settings=json.loads(cfg['settings_json'])
            from .semantic import teaching_context
            packet['teaching_context']=teaching_context(settings)
            # TASK is session context, never repeated for every page chunk.
            budget=settings.get('context_budget_bytes',262144)
        from .input_packet import compile_inputs,check_budget
        from .task_context import attach as attach_task_context
        attach_task_context(self.service, attempt, packet)
        compile_inputs(self.task,packet)
        check_budget(packet,budget)
        with self.store.transaction() as conn:
            row=conn.execute('SELECT state FROM audience_steps WHERE attempt_id=? AND sequence=?',(attempt['id'],next_row['sequence'])).fetchone()
            if row['state']!='pending':return None
            from .task_context import requested as request_task_context
            request_task_context(conn, self.service, attempt, f"audience:{attempt['id']}:{next_row['sequence']}", packet)
            conn.execute("UPDATE audience_steps SET state='dispatched' WHERE attempt_id=? AND sequence=?",(attempt['id'],next_row['sequence']))
            event(conn,'audience.step_requested',{'attempt_id':attempt['id'],'sequence':next_row['sequence'],'phase':next_row['phase'],'artifact_id':job['input_artifact_id'],'slide_ids':targets, 'semantic_guidance_version':packet['semantic_guidance_version'], 'role_introduction':'.agents/skills/audience-review/SKILL.md' in packet['semantic_guidance_sources']},job['id'])
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
        if self.protocol(attempt['id'])>=2 and row['phase']=='production_language':
            from mpres.source_policy import METADATA
            selected=[{'slide_id':sid,'markdown':METADATA.sub('',text[sid]).strip()} for sid in result['read_slide_ids']]
            validate_attention(result, attention_candidates(selected))
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
