"""Typed authorization heads over immutable historical policy events.

No model reads free-form feedback to infer capacity. Only three explicit event
schemas are recognized. Original settings/runtime/config rows are never rewritten.
"""
from __future__ import annotations
import copy
import difflib
import hashlib
import json
from mpres.util import MPresError, utc_now
from .store import encode, event

KINDS = {'task.text_amended':'task_text','capacity.authorized':'handle_limit',
         'context_budget.authorized':'context_budget_bytes'}


def validate_event(conn, row):
    data=json.loads(row['detail_json'])
    if not isinstance(data,dict) or not isinstance(data.get('actor'),str) or not data['actor'].strip():
        raise MPresError('Policy event lacks explicit attribution')
    cid=data.get('config_id')
    if cid is None:
        configs=conn.execute('SELECT id FROM configs').fetchall()
        if row['kind']!='capacity.authorized' or len(configs)!=1:
            raise MPresError('Legacy authorization has ambiguous configuration scope')
        cid=configs[0][0]
    if not conn.execute('SELECT 1 FROM configs WHERE id=?',(cid,)).fetchone():
        raise MPresError('Policy authorization refers to unknown configuration')
    name=KINDS[row['kind']]
    if name=='task_text':
        text=data.get('task_text')
        if not isinstance(text,str) or not text.strip() or data.get('task_digest')!=hashlib.sha256(text.encode()).hexdigest():
            raise MPresError('Authorized TASK text/digest is invalid')
        value=text
    else:
        value=data.get('limit' if name=='handle_limit' else 'bytes')
        if type(value) is not int or value<1:
            raise MPresError('Authorized operational limit must be a positive integer')
    return cid,name,value


def sync(conn):
    cursor=conn.execute('SELECT event_id FROM policy_cursor WHERE singleton=1').fetchone()[0]
    top=conn.execute('SELECT COALESCE(MAX(id),0) FROM events').fetchone()[0]
    for row in conn.execute("SELECT id,kind,detail_json FROM events WHERE id>? AND id<=? AND kind IN ('task.text_amended','capacity.authorized','context_budget.authorized') ORDER BY id",(cursor,top)):
        cid,name,_=validate_event(conn,row)
        conn.execute('INSERT INTO policy_values VALUES(?,?,?) ON CONFLICT(config_id,name) DO UPDATE SET event_id=excluded.event_id',(cid,name,row['id']))
    conn.execute('UPDATE policy_cursor SET event_id=? WHERE singleton=1',(top,))


def resolve(conn, base, *, readonly=False):
    """Return effective values plus exact event identities; no text heuristics."""
    result=dict(base);result['task_revision']=0
    settings=json.loads(base['settings_json']);sources={}
    if readonly:
        rows=[]
        for kind in KINDS:
            # Launcher may open a pre-migration database without making writes.
            # Several confirmed configs may exist. A later grant for another
            # config must not conceal this config's latest exact authorization.
            for row in conn.execute('SELECT id,kind,detail_json FROM events WHERE kind=? ORDER BY id DESC', (kind,)):
                cid, _, _ = validate_event(conn, row)
                if cid == base['id']:
                    rows.append(row)
                    break
    else:
        sync(conn)
        rows=conn.execute('SELECT e.id,e.kind,e.detail_json FROM policy_values v JOIN events e ON e.id=v.event_id WHERE v.config_id=?',(base['id'],)).fetchall()
    for row in rows:
        cid,name,value=validate_event(conn,row)
        if cid!=base['id']:continue
        sources[name]=row['id']
        if name=='task_text':
            result.update(task_text=value,task_revision=row['id'],task_digest=json.loads(row['detail_json'])['task_digest'])
        elif name=='handle_limit':settings['provider']['handle_limit']=value
        else:settings[name]=value
    result['settings_json']=encode(settings)
    result['document_settings_json']=base['settings_json']
    result['policy_sources']=sources
    return result


def quiescent(conn, *, allow_local_inputs=False):
    live=conn.execute("SELECT a.*,j.state job_state FROM attempts a JOIN jobs j ON a.job_id=j.id WHERE a.state IN ('reserved','running','uncertain')").fetchall()
    local_only=bool(live) and allow_local_inputs and all(a['state']=='reserved' and a['job_state']=='blocked' for a in live)
    if conn.execute('SELECT status FROM task').fetchone()[0] not in {'paused','completed'} and not local_only:
        raise MPresError('Policy/batch changes require a task pause or purely local input block')
    if (live and not local_only) or conn.execute("SELECT 1 FROM pool_slots WHERE state IN ('creating','uncertain')").fetchone():
        raise MPresError('Reconcile outstanding execution before changing policy or scope')
    if local_only:
        for a in live:
            b=conn.execute('SELECT run_dispatched FROM attempt_briefings WHERE attempt_id=?',(a['id'],)).fetchone()
            if (b and b[0]) or conn.execute("SELECT 1 FROM audience_steps WHERE attempt_id=? AND state='dispatched'",(a['id'],)).fetchone() or conn.execute("SELECT 1 FROM host_requests WHERE attempt_id=? AND state<>'accepted'",(a['id'],)).fetchone():
                raise MPresError('Reconcile outstanding dispatch before amending a local input limit')
    if conn.execute("SELECT 1 FROM host_requests q JOIN host_responses r USING(request_id) WHERE q.state<>'accepted'").fetchone():
        raise MPresError('Saved response requires acceptance before changing scope')


class Policy:
    def __init__(self, task):
        from .service import Service
        self.service=Service(task);self.store=self.service.store

    def pause(self, actor, note):
        from .service import require_text
        require_text(actor, 'User attribution');require_text(note, 'Amendment reason')
        with self.store.transaction() as conn:
            self.service.confirmed(conn)
            if conn.execute('SELECT status FROM task').fetchone()[0]!='running':
                raise MPresError('Only a running task can enter an amendment pause')
            conn.execute("UPDATE task SET status='paused'")
            quiescent(conn)  # Failure rolls back the pause as well.
            if conn.execute("SELECT 1 FROM host_requests WHERE state<>'accepted'").fetchone():
                raise MPresError('Reconcile outstanding requests before pausing')
            event(conn,'policy.paused',{'actor':actor,'note':note})
        return {'paused':True}

    def resume(self, actor):
        from .service import require_text
        require_text(actor, 'User continuation attribution')
        with self.store.transaction() as conn:
            self.service.confirmed(conn);quiescent(conn)
            last=conn.execute("SELECT kind FROM events WHERE kind IN ('policy.paused','policy.resumed') ORDER BY id DESC LIMIT 1").fetchone()
            if not last or last['kind']!='policy.paused':
                raise MPresError('No amendment pause to resume')
            from .batches import active
            if not active(conn):raise MPresError('An existing active batch is required')
            conn.execute("UPDATE task SET status='running'")
            event(conn,'policy.resumed',{'actor':actor})
        return {'resumed':True}

    def _proposal(self,conn,handle_limit=None,context_budget_bytes=None):
        base=conn.execute('SELECT c.* FROM configs c JOIN task t ON t.config_id=c.id').fetchone()
        if not base:raise MPresError('Task must be confirmed first')
        current=resolve(conn,base)
        doc=self.service.documents()
        if doc['runtime']!=json.loads(base['runtime_json']) or doc['settings']!=json.loads(base['settings_json']):
            raise MPresError('This policy amendment may not change runtime or course plan/settings files')
        changes={}
        if doc['task_text']!=current['task_text']:
            changes['task_text']={'text':doc['task_text'],'digest':doc['task_digest']}
        settings=json.loads(current['settings_json'])
        for key,value,old in [('handle_limit',handle_limit,settings['provider']['handle_limit']),('context_budget_bytes',context_budget_bytes,settings.get('context_budget_bytes',262144))]:
            if value is not None:
                if type(value) is not int or value<1:raise MPresError('Operational limits must be positive integers')
                if value!=old:changes[key]=value
        quiescent(conn,allow_local_inputs='task_text' not in changes and bool(changes))
        return {'type':'operational-policy','config_id':base['id'],'base_sources':current['policy_sources'],
                'changes':changes,'runtime_changed':False,
                'task_diff':''.join(difflib.unified_diff(current['task_text'].splitlines(True),doc['task_text'].splitlines(True),fromfile='effective/TASK.md',tofile='proposed/TASK.md'))}

    def present(self, *, handle_limit=None, context_budget_bytes=None):
        with self.store.transaction() as conn:
            proposal=self._proposal(conn,handle_limit,context_budget_bytes)
            event(conn,'policy.presented',proposal)
            pid=conn.execute('SELECT last_insert_rowid()').fetchone()[0]
            proposal['presentation_id']=pid
            conn.execute('UPDATE task SET presented_json=?',(encode(proposal),))
        return proposal

    def confirm(self, presentation_id, actor):
        if not isinstance(actor,str) or not actor.strip():raise MPresError('Explicit confirmation attribution is required')
        with self.store.transaction() as conn:
            old=conn.execute("SELECT detail_json FROM events WHERE kind='policy.confirmed' AND json_extract(detail_json,'$.presentation_id')=?",(presentation_id,)).fetchone()
            if old:
                if json.loads(old[0])['actor']!=actor:raise MPresError('Conflicting policy confirmation attribution')
                return {'presentation_id':presentation_id,'already_confirmed':True,'runtime_changed':False}
            raw=conn.execute('SELECT presented_json FROM task').fetchone()[0]
            proposal=json.loads(raw or '{}')
            if proposal.get('type')!='operational-policy' or proposal.get('presentation_id')!=presentation_id:
                raise MPresError('Present the exact policy changes before user confirmation')
            ch=proposal['changes']
            current=self._proposal(conn,ch.get('handle_limit'),ch.get('context_budget_bytes'))
            if current!={k:v for k,v in proposal.items() if k!='presentation_id'}:
                raise MPresError('Policy changed after presentation; show the new differences')
            for key,value in ch.items():
                data={'actor':actor,'config_id':proposal['config_id'],'proposal_id':presentation_id,'note':'Explicitly presented policy amendment'}
                if key=='task_text':kind='task.text_amended';data.update(task_text=value['text'],task_digest=value['digest'])
                elif key=='handle_limit':kind='capacity.authorized';data['limit']=value
                else:kind='context_budget.authorized';data['bytes']=value
                event(conn,kind,data)
            sync(conn)
            conn.execute('UPDATE task SET presented_json=NULL')
            event(conn,'policy.confirmed',{'presentation_id':presentation_id,'actor':actor})
        return self.show()

    def show(self):
        with self.store.transaction() as conn:
            base=conn.execute('SELECT c.* FROM configs c JOIN task t ON t.config_id=c.id').fetchone()
            if not base:raise MPresError('Task has not been confirmed')
            cfg=resolve(conn,base)
        settings=json.loads(cfg['settings_json'])
        return {'config_id':cfg['id'],'task_revision':cfg['task_revision'],'sources':cfg['policy_sources'],
                'handle_limit':settings['provider']['handle_limit'],'context_budget_bytes':settings.get('context_budget_bytes',262144),
                'task_text':cfg['task_text'],'runtime_changed':False}
