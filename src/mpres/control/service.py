from __future__ import annotations

import json
import sqlite3
import uuid
from pathlib import Path
from typing import Any

from mpres.runtime_profile import normalize_runtime_profile, resolve_runtime
from mpres.util import MPresError, read_yaml, safe_id, task_sha256, utc_now, write_yaml_atomic
from .files import inside, remove_tree, snapshot
from .store import Store, encode, event

CHANNELS = ('domain_accuracy', 'pedagogy', 'audience', 'language', 'layout')
ROLES = {'write': 'lesson-author', 'edit': 'deck-revision-author',
         'revise': 'deck-revision-author', 'review': 'specialist-reviewer',
         'diagnose': 'diagnostic-reviewer'}
TOKEN_FIELDS = ('input_tokens', 'cached_input_tokens', 'output_tokens', 'reasoning_tokens', 'total_tokens')


def uid(prefix: str) -> str:
    return prefix + '-' + uuid.uuid4().hex


def require_text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip() or '[[' in value:
        raise MPresError(f'{label} requires real non-placeholder text')
    return value.strip()


def settings_document(value: Any) -> dict:
    if not isinstance(value, dict):
        raise MPresError('task.yaml must be a mapping')
    allowed = {'schema_version','engine','title','delivery','author_concurrency','max_attempts','provider','presentations','context_budget_bytes','provider_timeout_seconds','quality','workflow','recovery','teaching'}
    if set(value) - allowed:
        raise MPresError(f'Unknown task settings: {sorted(set(value)-allowed)}')
    if value.get('schema_version') != 1 or value.get('engine') != 'compact':
        raise MPresError('Expected compact schema_version 1')
    require_text(value.get('title'), 'title')
    if value.get('delivery') not in {'all','pilot','each'}:
        raise MPresError('delivery must be all, pilot or each')
    for key in ('author_concurrency','max_attempts'):
        if type(value.get(key)) is not int or not 1 <= value[key] <= 32:
            raise MPresError(f'{key} must be an integer from 1 to 32')
    p = value.get('provider')
    if not isinstance(p, dict) or set(p) != {'mode','command','handle_limit','external_handles','recovery_reserve','supports_close','supports_reset'}:
        raise MPresError('provider must use the exact fields in the template')
    if p['mode'] not in {'bridge','command'} or not isinstance(p['command'], list) or any(not isinstance(x,str) or not x for x in p['command']):
        raise MPresError('Invalid provider mode/command argv')
    if p['mode'] == 'command' and not p['command']:
        raise MPresError('command mode requires a user-configured JSON-stdio adapter')
    if p['mode'] == 'bridge' and p['command']:
        raise MPresError('bridge mode does not execute a command')
    if p['handle_limit'] is not None and (type(p['handle_limit']) is not int or p['handle_limit'] < 1):
        raise MPresError('handle_limit must be null or a positive integer')
    for key in ('external_handles','recovery_reserve'):
        if type(p[key]) is not int or p[key] < 0:
            raise MPresError(f'provider.{key} must be non-negative')
    for key in ('supports_close','supports_reset'):
        if type(p[key]) is not bool:
            raise MPresError(f'provider.{key} must be a boolean')
    for key in ('context_budget_bytes','provider_timeout_seconds'):
        if key in value and (type(value[key]) is not int or value[key]<1):
            raise MPresError(f'{key} must be a positive integer')
    if value.get('workflow', 'authoring') not in {'authoring', 'full'}:
        raise MPresError('workflow must be authoring or full')
    quality = value.get('quality')
    if quality is not None:
        if not isinstance(quality, dict) or set(quality) != {'browser', 'timeout_seconds'}:
            raise MPresError('quality requires browser and timeout_seconds only')
        if quality['browser'] not in {'auto', 'chrome', 'firefox'}:
            raise MPresError('Unsupported Marp browser')
        if type(quality['timeout_seconds']) is not int or not 1 <= quality['timeout_seconds'] <= 7200:
            raise MPresError('quality.timeout_seconds must be 1..7200')
    recovery = value.get('recovery', {})
    from .recovery import DEFAULTS
    if not isinstance(recovery, dict) or set(recovery)-set(DEFAULTS):
        raise MPresError('recovery accepts transient_tool_retries and host_observation_retries only')
    if any(type(x) is not int or not 0 <= x <= 3 for x in recovery.values()):
        raise MPresError('Recovery retries must be integers from 0 to 3')
    teaching = value.get('teaching')
    if teaching is not None:
        if not isinstance(teaching, dict) or set(teaching) != {'audience','proof_depth'}:
            raise MPresError('teaching requires audience and proof_depth only')
        require_text(teaching['audience'], 'Student audience, not workflow instructions')
        if teaching['proof_depth'] not in {'minimal','explanatory','rigorous'}:
            raise MPresError('proof_depth must be minimal, explanatory or rigorous')
    decks = value.get('presentations')
    if not isinstance(decks, list) or not decks:
        raise MPresError('Supply a semantic course plan in task.yaml before presenting')
    seen = set()
    for deck in decks:
        if not isinstance(deck,dict) or set(deck)-{'id','title','units','estimated_pages'} or not {'id','title','units'} <= set(deck):
            raise MPresError('Each presentation requires id, title and units')
        if 'estimated_pages' in deck and (type(deck['estimated_pages']) is not int or deck['estimated_pages'] < 1):
            raise MPresError('estimated_pages must be a positive integer')
        safe_id(deck['id'])
        if deck['id'] in seen:
            raise MPresError('Duplicate presentation ID')
        seen.add(deck['id'])
        require_text(deck['title'], 'presentation title')
        units = deck['units']
        if not isinstance(units,list) or not units:
            raise MPresError('Each presentation needs at least one unit')
        unit_ids = set()
        for unit in units:
            if not isinstance(unit,dict) or set(unit) != {'id','title','brief','sources'}:
                raise MPresError('Each unit requires id, title, brief and sources')
            safe_id(unit['id'])
            if unit['id'] in unit_ids:
                raise MPresError('Duplicate unit ID in a presentation')
            unit_ids.add(unit['id'])
            require_text(unit['title'], 'unit title')
            require_text(unit['brief'], 'unit semantic brief')
            if not isinstance(unit['sources'],list) or any(not isinstance(x,str) or not x.startswith('sources/') for x in unit['sources']):
                raise MPresError('Sources must be task-relative sources/ paths')
    from .semantic import validate
    validate('plan', {'presentations': decks})
    return value


class Service:
    def __init__(self, task: Path):
        self.task = task.resolve()
        self.store = Store(self.task)

    @classmethod
    def create(cls, root: Path, slug: str, title: str) -> 'Service':
        safe_id(slug, label='task slug')
        task = root.resolve() / 'tasks' / slug
        if task.exists():
            raise MPresError('Task already exists; initialization never overwrites it')
        task.mkdir(parents=True)
        templates = root / 'templates' / 'compact'
        try:
            for source, target in [('TASK.template.md','TASK.md'),('task.template.yaml','task.yaml'),
                                   ('TASK-RUNTIME-PROFILE.template.yaml','TASK-RUNTIME-PROFILE.yaml')]:
                (task/target).write_bytes((templates/source).read_bytes())
            settings = read_yaml(task/'task.yaml')
            settings['title'] = require_text(title,'title')
            write_yaml_atomic(task/'task.yaml',settings)
            for folder in ('sources','content','deliverables'):
                (task/folder).mkdir()
            service = cls(task)
            service.store.initialize(title)
            from .feedback import Feedback
            Feedback(service.task).seed()
            return service
        except Exception:
            remove_tree(task)
            raise

    def documents(self) -> dict:
        settings = settings_document(read_yaml(self.task/'task.yaml'))
        for deck in settings['presentations']:
            for unit in deck['units']:
                for source in unit['sources']:
                    path = inside(self.task, source)
                    if not path.is_file():
                        raise MPresError(f'Missing authorized source: {source}')
        return {'settings':settings, 'runtime':normalize_runtime_profile(read_yaml(self.task/'TASK-RUNTIME-PROFILE.yaml')),
                'task_text':(self.task/'TASK.md').read_text(encoding='utf-8'),
                'task_digest':task_sha256(self.task/'TASK.md')}

    def present(self) -> dict:
        doc = self.documents()
        with self.store.transaction() as conn:
            task = conn.execute('SELECT * FROM task').fetchone()
            if task['config_id'] is not None:
                self.confirmed(conn)
            conn.execute('UPDATE task SET presented_json=?', (encode(doc),))
            event(conn,'task.presented',{})
        from .feedback import Feedback
        from .semantic import teaching_context, teaching_conflicts
        from .inspection import plan_checks
        return {**doc, 'page_estimates': plan_checks(doc['settings']), 'historical_feedback': Feedback(self.task).list(),
                'teaching_context': teaching_context(doc['settings']),
                'teaching_conflicts': teaching_conflicts(doc['settings'],doc['task_text'])}

    def confirm(self, actor: str) -> dict:
        actor = require_text(actor,'explicit user confirmation attribution')
        doc = self.documents()
        with self.store.transaction() as conn:
            task = conn.execute('SELECT * FROM task').fetchone()
            if task['config_id'] is not None:
                current = self.confirmed(conn)
                return {'config_id':current['id'],'already_confirmed':True}
            if not task['presented_json'] or json.loads(task['presented_json']) != doc:
                raise MPresError('Present the exact documents to the user before confirmation')
            from .inspection import plan_checks
            over = [pid for pid, check in plan_checks(doc['settings']).items() if not check['success']]
            if over:
                raise MPresError('Plan exceeds 100 estimated pages; split before confirmation: '+', '.join(over))
            cur = conn.execute('INSERT INTO configs(settings_json,runtime_json,task_text,task_digest,confirmed_by,confirmed_at) VALUES(?,?,?,?,?,?)',
                               (encode(doc['settings']),encode(doc['runtime']),doc['task_text'],doc['task_digest'],actor,utc_now()))
            cid = cur.lastrowid
            ordinal = 0
            for deck in doc['settings']['presentations']:
                for unit in deck['units']:
                    ordinal += 1
                    conn.execute('INSERT INTO plan_items(config_id,presentation,unit,deck_title,title,ordinal,brief,sources_json) VALUES(?,?,?,?,?,?,?,?)',
                                 (cid,deck['id'],unit['id'],deck['title'],unit['title'],ordinal,unit['brief'],encode(unit['sources'])))
            conn.execute("UPDATE task SET config_id=?,status='running'", (cid,))
            event(conn,'task.confirmed',{'config_id':cid,'actor':actor})
        return {'config_id':cid,'already_confirmed':False}

    def confirmed(self, conn: sqlite3.Connection) -> dict:
        row = conn.execute('SELECT configs.* FROM configs JOIN task ON task.config_id=configs.id').fetchone()
        if row is None:
            raise MPresError('Task has not been confirmed by the user')
        from .policy import resolve
        row = resolve(conn, row)
        expected = {'settings':json.loads(row['document_settings_json']),'runtime':json.loads(row['runtime_json']),
                    'task_text':row['task_text'],'task_digest':row['task_digest']}
        if self.documents() != expected:
            raise MPresError('Confirmed task files changed. Restore them; runtime changes during execution are forbidden')
        return dict(row)

    def ensure_job(self, conn: sqlite3.Connection, *, key: str, presentation: str, kind: str,
                   plan_item_id: int | None = None, round: int = 0, channel: str = '',
                   artifact: str | None = None, needs: tuple[str,...] = ()) -> str:
        config = self.confirmed(conn)
        family = 'reviewer' if kind in {'review','diagnose'} else 'author' if kind in {'write','edit','revise'} else None
        if not conn.execute('SELECT 1 FROM plan_items WHERE config_id=? AND presentation=?',(config['id'],presentation)).fetchone():
            raise MPresError('Job presentation is outside the approved plan')
        if plan_item_id is not None:
            plan = conn.execute('SELECT * FROM plan_items WHERE id=?',(plan_item_id,)).fetchone()
            if plan is None or plan['config_id'] != config['id'] or plan['presentation'] != presentation:
                raise MPresError('Job coordinates do not match the approved plan item')
        if kind == 'write' and plan_item_id is None:
            raise MPresError('A writing job must refer to an approved unit')
        if artifact is not None:
            item = conn.execute('SELECT presentation FROM artifacts WHERE id=?',(artifact,)).fetchone()
            if item is None or item['presentation'] != presentation:
                raise MPresError('Job input revision belongs to a different presentation')
        if kind == 'review' and channel not in CHANNELS:
            raise MPresError('Unknown review channel')
        row = conn.execute('SELECT * FROM jobs WHERE key=?',(key,)).fetchone()
        payload = (config['id'],plan_item_id,presentation,kind,family,round,channel,artifact)
        if row:
            previous = tuple(row[x] for x in ('config_id','plan_item_id','presentation','kind','family','round','channel','input_artifact_id'))
            deps = tuple(sorted(x[0] for x in conn.execute('SELECT needs_id FROM dependencies WHERE job_id=?',(row['id'],))))
            if previous != payload or tuple(sorted(needs)) != deps:
                raise MPresError('Idempotency key conflicts with an existing job')
            return str(row['id'])
        job_id = uid('j')
        conn.execute('INSERT INTO jobs(id,key,config_id,plan_item_id,presentation,kind,family,round,channel,input_artifact_id,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)',
                     (job_id,key,*payload,utc_now()))
        for dep in needs:
            conn.execute('INSERT INTO dependencies VALUES(?,?)',(job_id,dep))
        event(conn,'job.created',{'kind':kind},job_id)
        return job_id

    def materialize(self) -> list[dict]:
        with self.store.transaction() as conn:
            self.confirmed(conn)
            for p in conn.execute('SELECT * FROM plan_items ORDER BY ordinal').fetchall():
                self.ensure_job(conn,key=f"write:{p['id']}",presentation=p['presentation'],kind='write',plan_item_id=p['id'])
        return self.jobs()

    def jobs(self) -> list[dict]:
        return self.store.rows('SELECT j.*,p.unit FROM jobs j LEFT JOIN plan_items p ON p.id=j.plan_item_id ORDER BY j.created_at,j.rowid')

    def job(self, job_id: str) -> dict:
        rows = self.store.rows('SELECT * FROM jobs WHERE id=?',(job_id,))
        if not rows:
            raise MPresError('Unknown job ID; use the ID returned by the database')
        return rows[0]

    def expected_runtime(self, conn: sqlite3.Connection, job: dict | sqlite3.Row) -> dict:
        config = self.confirmed(conn)
        if job['kind'] not in ROLES:
            raise MPresError('Mechanical jobs have no model runtime')
        return resolve_runtime(json.loads(config['runtime_json']),ROLES[job['kind']],
                               channel=job['channel'] or None,presentation_id=job['presentation'])

    def register_session(self, handle: str, family: str, model: str, effort: str, receipt: str) -> dict:
        require_text(handle,'provider handle')
        require_text(receipt,'provider session receipt')
        with self.store.transaction() as conn:
            self.confirmed(conn)
            old = conn.execute('SELECT * FROM sessions WHERE id=?',(handle,)).fetchone()
            if old:
                if (old['family'],old['model'],old['effort'],old['receipt']) != (family,model,effort,receipt):
                    raise MPresError('Existing provider handle has different immutable attributes')
                return dict(old)
            conn.execute('INSERT INTO sessions(id,family,model,effort,receipt,created_at) VALUES(?,?,?,?,?,?)',
                         (handle,family,model,effort,receipt,utc_now()))
            event(conn,'session.registered',{'handle':handle,'family':family})
        return self.store.rows('SELECT * FROM sessions WHERE id=?',(handle,))[0]

    def eligible(self, conn: sqlite3.Connection, job: dict | sqlite3.Row, session: dict | sqlite3.Row) -> bool:
        expected = self.expected_runtime(conn,job)
        if session['state'] != 'open' or (session['family'],session['model'],session['effort']) != (expected['runtime_family'],expected['model'],expected['reasoning_effort']):
            return False
        if conn.execute("SELECT 1 FROM attempts WHERE session_id=? AND state IN ('reserved','running','uncertain')",(session['id'],)).fetchone():
            return False
        history = conn.execute('SELECT * FROM participation WHERE session_id=? AND presentation=?',(session['id'],job['presentation'])).fetchall()
        if job['family'] == 'reviewer' and any(x['kind'] in {'write','edit','revise'} for x in history):
            return False
        if job['kind'] == 'review' and any(x['kind']=='review' and x['round']==job['round'] and x['channel']!=job['channel'] for x in history):
            return False
        if job['kind'] == 'revise' and any(x['kind']=='review' for x in history):
            return False
        return True

    def bind(self, job_id: str, handle: str) -> dict:
        from .feedback import Feedback
        Feedback(self.task).seed()
        with self.store.transaction() as conn:
            self.confirmed(conn)
            job = conn.execute('SELECT * FROM jobs WHERE id=?',(job_id,)).fetchone()
            if job is None:
                raise MPresError('Unknown job ID; no state has been written')
            if conn.execute('SELECT status FROM task').fetchone()[0] != 'running':
                from .repairs import Repairs
                if not Repairs.proposal_job(conn, job_id):
                    raise MPresError('Task is paused or completed')
            from .batches import active, targets
            batch=active(conn)
            if batch and job['presentation'] not in targets(conn,batch['id']):
                raise MPresError('Job is outside the confirmed production batch')
            if job['state'] != 'queued':
                raise MPresError('Job is not queued')
            if job['kind']=='write':
                task_row=conn.execute('SELECT author_slots_limit FROM task').fetchone()
                config=json.loads(self.confirmed(conn)['settings_json'])
                limit=task_row['author_slots_limit'] or config['author_concurrency']
                active=conn.execute("SELECT count(*) FROM attempts a JOIN jobs j ON j.id=a.job_id WHERE j.kind='write' AND a.state IN ('reserved','running','uncertain')").fetchone()[0]
                if active>=limit:
                    raise MPresError('Confirmed/admitted author concurrency is already occupied')
            if conn.execute("SELECT 1 FROM dependencies d JOIN jobs j ON j.id=d.needs_id WHERE d.job_id=? AND j.state<>'succeeded'",(job_id,)).fetchone():
                raise MPresError('Job dependencies have not succeeded')
            session = conn.execute('SELECT * FROM sessions WHERE id=?',(handle,)).fetchone()
            if session is None or not self.eligible(conn,job,session):
                raise MPresError('Session is unavailable, runtime-incompatible or not independent')
            seq = conn.execute('SELECT coalesce(max(sequence),0)+1 FROM attempts WHERE job_id=?',(job_id,)).fetchone()[0]
            attempt = uid('a')
            conn.execute("INSERT INTO attempts(id,job_id,session_id,sequence,state,started_at) VALUES(?,?,?,?,'reserved',?)",
                         (attempt,job_id,handle,seq,utc_now()))
            Feedback.reserve(conn,attempt,job['presentation'])
            conn.execute("UPDATE jobs SET state='running' WHERE id=?",(job_id,))
            conn.execute('INSERT OR IGNORE INTO participation VALUES(?,?,?,?,?)',
                         (handle,job['presentation'],job['kind'],job['round'],job['channel']))
            event(conn,'attempt.reserved',{'attempt_id':attempt,'handle':handle},job_id)
        return self.attempt(attempt)

    def attempt(self, attempt_id: str) -> dict:
        rows = self.store.rows('SELECT * FROM attempts WHERE id=?',(attempt_id,))
        if not rows:
            raise MPresError('Unknown attempt ID')
        return rows[0]

    def started(self, attempt_id: str, receipt: str) -> dict:
        require_text(receipt,'provider execution receipt')
        with self.store.transaction() as conn:
            self.confirmed(conn)
            row = conn.execute('SELECT * FROM attempts WHERE id=?',(attempt_id,)).fetchone()
            if row and row['state']=='succeeded' and row['provider_receipt']==receipt:
                return dict(row)
            if not row or row['state'] not in {'reserved','running','uncertain'}:
                raise MPresError('Attempt is not reserved/running/uncertain')
            from .feedback import Feedback
            Feedback.require_readback(conn, attempt_id)
            if row['provider_receipt'] and row['provider_receipt'] != receipt:
                raise MPresError('Provider receipt is immutable')
            conn.execute("UPDATE attempts SET state='running',provider_receipt=? WHERE id=?",(receipt,attempt_id))
            event(conn,'attempt.started',{'attempt_id':attempt_id,'receipt':receipt},row['job_id'])
        return self.attempt(attempt_id)

    def uncertain(self, attempt_id: str, reason: str) -> None:
        require_text(reason,'uncertainty reason')
        with self.store.transaction() as conn:
            row = conn.execute('SELECT * FROM attempts WHERE id=?',(attempt_id,)).fetchone()
            if not row or row['state'] not in {'reserved','running','uncertain'}:
                raise MPresError('Only an outstanding attempt can be uncertain')
            conn.execute("UPDATE attempts SET state='uncertain',error=? WHERE id=?",(reason,attempt_id))
            conn.execute("UPDATE sessions SET state='uncertain' WHERE id=?",(row['session_id'],))
            event(conn,'attempt.uncertain',{'reason':reason},row['job_id'])

    def reject_completed(self, attempt_id: str, reason: str, result: dict) -> dict:
        """Requeue only a known-completed, acknowledged content response.

        The exact configured max_attempts bounds all executions of this job. Retrying
        the HTTP/stdio run itself is forbidden: correction has a NEW attempt identity.
        """
        with self.store.transaction() as conn:
            cfg=self.confirmed(conn)
            a=conn.execute('SELECT * FROM attempts WHERE id=?',(attempt_id,)).fetchone()
            if not a or a['state']!='running' or not a['provider_receipt']:
                raise MPresError('A content rejection needs a known completed execution receipt')
            limit=json.loads(cfg['settings_json'])['max_attempts']
            queued=a['sequence'] < limit
            state='queued' if queued else 'blocked'
            conn.execute("UPDATE attempts SET state='failed',finished_at=?,error=?,result_json=? WHERE id=?",
                         (utc_now(),reason,encode(result),attempt_id))
            conn.execute('UPDATE jobs SET state=? WHERE id=?',(state,a['job_id']))
            conn.execute("UPDATE sessions SET state='open' WHERE id=?",(a['session_id'],))
            detail={'attempt_id':attempt_id,'reason':reason,'sequence':a['sequence'],
                    'limit':limit,'action':'correct_content' if queued else 'budget_exhausted'}
            event(conn,'attempt.content_rejected',detail,a['job_id'])
            if not queued:
                presentation=conn.execute('SELECT presentation FROM jobs WHERE id=?',(a['job_id'],)).fetchone()[0]
                conn.execute('INSERT INTO decisions(kind,presentation,detail_json) VALUES(?,?,?)',
                             ('content-retry-budget',presentation,encode(detail)))
        return {'attempt_id':attempt_id,'submission_rejected':True,'next_action':detail['action']}

    def submit(self, attempt_id: str, result: dict, *, source: Path | None = None) -> dict:
        from mpres.util import SubmissionRejected
        if not isinstance(result,dict):
            raise SubmissionRejected('Result must be a JSON object')
        try:
            require_text(result.get('summary'),'semantic summary')
        except MPresError as exc:
            raise SubmissionRejected(str(exc)) from exc
        attempt = self.attempt(attempt_id)
        job = self.job(attempt['job_id'])
        from .semantic import validate, result_schema_name
        if job['family'] is not None:
            validate(result_schema_name(job['kind']), result)
        from .review_data import prepare as prepare_review, storage_result
        raw_result = result
        historical_result = (attempt['state']=='succeeded' and json.loads(attempt['result_json'] or '{}').get('storage_schema') != 'review-references-v1')
        if not historical_result:
            result = prepare_review(self, job, attempt_id, result)
        from .audience import Audience, applies
        if applies(job) and (attempt['state']!='succeeded' or Audience(self.task).rows(attempt_id)):
            Audience(self.task).require_final(attempt_id,result)
        canonical = encode(result if historical_result else storage_result(job, result))
        if source is not None:
            if not source.resolve().is_relative_to(self.task):
                raise MPresError('Submission source must be under this task')
            relative=source.absolute().relative_to(self.task)
            inside(self.task,relative.as_posix())
            if not source.is_dir() or any(p.is_symlink() for p in source.rglob('*')):
                raise MPresError('Submission requires a directory without symlinks')
        if source is not None:
            from mpres.source_policy import require_source
            require_source(source)
        if attempt['state'] == 'succeeded':
            if attempt['result_json'] not in {canonical, encode(result)}:
                raise MPresError('Duplicate submission differs; accepted results are immutable')
            if source is not None:
                prior = self.store.rows('SELECT path FROM artifacts WHERE attempt_id=?',(attempt_id,))
                if not prior:
                    raise MPresError('Duplicate submission unexpectedly includes source')
                frozen = self.task/prior[0]['path']
                from mpres.source_policy import comparable_files
                old_files=comparable_files(frozen)
                new_files=comparable_files(source)
                if old_files != new_files:
                    raise MPresError('Duplicate submission source differs from its accepted revision')
            return {'attempt_id':attempt_id,'already_submitted':True}
        if attempt['state'] not in {'running','uncertain'} or not attempt['provider_receipt']:
            raise MPresError('An acknowledged execution receipt is required before submitting')
        needs_source = job['kind'] in {'write','edit','revise'}
        if needs_source and (source is None or not (source/'presentation.md').is_file()):
            from mpres.util import SubmissionRejected
            raise SubmissionRejected('Author/edit result requires its source directory with presentation.md')
        if not needs_source and source is not None:
            raise MPresError('A reviewer or diagnostic worker cannot replace source')
        from .feedback import Feedback
        Feedback(self.task).validate_result(attempt_id, job, result, source)
        from .repairs import Repairs
        Repairs(self.task).validate_result(job, result, source)
        from .workflow import validate_result
        validate_result(self, job, result, source)
        artifact = None
        if source is not None:
            if not source.resolve().is_relative_to(self.task):
                raise MPresError('Submission source must be under this task')
            if source.resolve().is_relative_to(self.task/'.mpres'/'artifacts'):
                raise MPresError('Submit from a writable work/content directory, not a frozen artifact')
            artifact = snapshot(self.task,source,fixed_theme=True)
        try:
            with self.store.transaction() as conn:
                self.confirmed(conn)
                row = conn.execute('SELECT * FROM attempts WHERE id=?',(attempt_id,)).fetchone()
                if row['state']=='succeeded':
                    if row['result_json'] != canonical:
                        raise MPresError('Conflicting concurrent result')
                    if artifact:
                        previous=conn.execute('SELECT path FROM artifacts WHERE attempt_id=?',(attempt_id,)).fetchone()
                        if not previous:
                            raise MPresError('Concurrent submission source differs')
                        old_root=self.task/previous['path'];new_root=self.task/artifact[1]
                        old_files={p.relative_to(old_root).as_posix():p.read_bytes() for p in old_root.rglob('*') if p.is_file()}
                        new_files={p.relative_to(new_root).as_posix():p.read_bytes() for p in new_root.rglob('*') if p.is_file()}
                        if old_files!=new_files:
                            raise MPresError('Concurrent submission source differs')
                        remove_tree(self.task/artifact[1])
                    return {'attempt_id':attempt_id,'already_submitted':True}
                if row['state'] not in {'running','uncertain'}:
                    raise MPresError('Attempt is no longer accepting results')
                if job['kind']=='review':
                    event(conn, 'review.result_received', {'attempt_id':attempt_id,'receipt':row['provider_receipt'],'raw_result':raw_result},job['id'])
                    findings = result.get('findings')
                    if not isinstance(findings,list) or job['input_artifact_id'] is None:
                        raise MPresError('Review requires findings and a frozen input revision')
                    for index,item in enumerate(findings,1):
                        if not isinstance(item,dict):
                            raise MPresError('Each finding must be a mapping')
                        require_text(item.get('message'),'finding message')
                        if not isinstance(item.get('slide_ids'),list) or not item['slide_ids']:
                            raise MPresError('Each finding requires slide ID evidence')
                        conn.execute('INSERT INTO findings(id,job_id,artifact_id,channel,detail_json) VALUES(?,?,?,?,?)',
                                     (f'{job["id"]}:{index}',job['id'],job['input_artifact_id'],job['channel'],encode(item)))
                if artifact:
                    p = conn.execute('SELECT unit FROM plan_items WHERE id=?',(job['plan_item_id'],)).fetchone()
                    conn.execute('INSERT INTO artifacts(id,attempt_id,presentation,unit,path,created_at,origin) VALUES(?,?,?,?,?,?,?)',
                                 (artifact[0],attempt_id,job['presentation'],p['unit'] if p else None,artifact[1],utc_now(),'submission'))
                if job['kind']=='revise' and artifact and result.get('resolutions') is not None:
                    for resolution in result['resolutions']:
                        conn.execute('UPDATE findings SET resolution_json=? WHERE id=?',
                                     (encode({**resolution, 'artifact_id': artifact[0], 'attempt_id': attempt_id}), resolution['finding_id']))
                if job['kind']=='diagnose':
                    Repairs(self.task).accept_proposal(conn, job, result)
                conn.execute("UPDATE attempts SET state='succeeded',result_json=?,finished_at=?,error=NULL WHERE id=?",(canonical,utc_now(),attempt_id))
                conn.execute("UPDATE jobs SET state='succeeded' WHERE id=?",(job['id'],))
                conn.execute("UPDATE sessions SET state='open' WHERE id=? AND state='uncertain'",(row['session_id'],))
                event(conn,'attempt.submitted',{'attempt_id':attempt_id,'artifact_id':artifact[0] if artifact else None},job['id'])
        except Exception:
            if artifact:
                remove_tree(self.task/artifact[1])
            raise
        return {'attempt_id':attempt_id,'artifact_id':artifact[0] if artifact else None,'already_submitted':False}

    def record_usage(self, attempt_id: str, call_id: str, counters: dict) -> None:
        self.attempt(attempt_id)
        if set(counters)-set(TOKEN_FIELDS):
            raise MPresError('Unknown token fields')
        for value in counters.values():
            if value is not None and (type(value) is not int or value<0):
                raise MPresError('Token counters must be null or non-negative integers')
        values = tuple(counters.get(field) for field in TOKEN_FIELDS)
        with self.store.transaction() as conn:
            old = conn.execute('SELECT * FROM usage WHERE attempt_id=? AND call_id=?',(attempt_id,call_id)).fetchone()
            if old:
                if tuple(old[k] for k in TOKEN_FIELDS) != values:
                    raise MPresError('A token call receipt cannot be silently changed')
                return
            conn.execute('INSERT INTO usage VALUES(?,?,?,?,?,?,?,?)',(attempt_id,require_text(call_id,'call ID'),*values,utc_now()))

    def metrics(self) -> dict:
        rows = self.store.rows('SELECT * FROM usage')
        attempts = self.store.rows('SELECT * FROM attempts WHERE session_id IS NOT NULL')
        fields = {}
        for field in TOKEN_FIELDS:
            known = [r[field] for r in rows if r[field] is not None]
            complete = bool(rows) and len(known)==len(rows)
            fields[field] = {'total':sum(known) if complete else None,'known_sum':sum(known),
                             'known_records':len(known),'unknown_records':len(rows)-len(known)}
        covered = {r['attempt_id'] for r in rows}
        fresh=[r['input_tokens']-r['cached_input_tokens'] for r in rows if r['input_tokens'] is not None and r['cached_input_tokens'] is not None]
        attributed=self.store.rows('SELECT u.*,j.kind,j.presentation,p.unit FROM usage u JOIN attempts a ON a.id=u.attempt_id JOIN jobs j ON j.id=a.job_id LEFT JOIN plan_items p ON p.id=j.plan_item_id')
        groups={}
        for row in attributed:
            key=(row['kind'],row['presentation'],row['unit'])
            groups.setdefault(key,[]).append(row)
        grouped=[]
        for (kind,presentation,unit),items in groups.items():
            totals={field:sum(r[field] for r in items) if all(r[field] is not None for r in items) else None for field in TOKEN_FIELDS}
            grouped.append({'kind':kind,'presentation':presentation,'unit':unit,'calls':len(items),'totals':totals})
        return {'calls_observed':len(rows),'attempts_expected':len(attempts),'by_job_coordinates':grouped,
                'fresh_input_total':sum(fresh) if rows and len(fresh)==len(rows) else None,
                'fresh_input_known_sum':sum(fresh),'lifecycle_coverage':'not_established_by_attempt_coverage',
                'attempts_with_usage':len(covered),'attempt_coverage':len(covered)/len(attempts) if attempts else None,
                'record_field_coverage':sum(all(r[f] is not None for f in TOKEN_FIELDS) for r in rows)/len(rows) if rows else None,
                'fields':fields,'cost_currency':None}

    def status(self) -> dict:
        from .delivery import Delivery
        state = self.store.rows('SELECT singleton,title,status,created_at,config_id FROM task')[0]
        state.update({'database':str(self.store.path),'jobs':self.store.rows('SELECT kind,state,count(*) AS count FROM jobs GROUP BY kind,state'),
                      'unresolved_decisions':self.store.rows('SELECT * FROM decisions WHERE resolved_at IS NULL'),
                      'artifacts':self.store.rows('SELECT id,presentation,unit,origin,verified FROM artifacts'),
                      'model_control_roles':[], 'delivery_package': Delivery(self.task).status()})
        from .repairs import Repairs
        state['repairs']=Repairs(self.task).status()
        return state
