"""The confirmed TASK is initial context of a session, not of every job.

No extra model call, file, hash or schema. The existing successful provider
receipt attests completion of the request's reading instruction, not human
comprehension. No acknowledgement is inferred for older in-flight requests.
"""
from __future__ import annotations

import difflib
import json

from mpres.util import MPresError
from .store import encode, event

REQUESTED = 'session.task_context_requested'
ACCEPTED = 'session.task_context_received'


def _previous(conn, session_id):
    row = conn.execute(
        "SELECT e.id,e.detail_json,c.task_text FROM events e JOIN configs c "
        "ON c.id=json_extract(e.detail_json,'$.config_id') WHERE e.kind=? "
        "AND json_extract(e.detail_json,'$.session_id')=? ORDER BY e.id DESC LIMIT 1",
        (ACCEPTED, session_id)).fetchone()
    if row:
        row=dict(row);row['task_text']=_text(conn,json.loads(row['detail_json']))
    return row


def _text(conn, detail):
    revision=detail.get('task_revision',0)
    if revision:
        row=conn.execute("SELECT id,kind,detail_json FROM events WHERE id=? AND kind='task.text_amended'",(revision,)).fetchone()
        if not row:raise MPresError('Missing authorized TASK revision')
        from .policy import validate_event
        cid,name,text=validate_event(conn,row)
        if cid!=detail['config_id']:raise MPresError('TASK revision belongs to another configuration')
        return text
    return conn.execute('SELECT task_text FROM configs WHERE id=?',(detail['config_id'],)).fetchone()[0]


def context(service, attempt, conn=None):
    """Read the exact confirmed source; unchanged context has no repeated text."""
    if conn is None:
        with service.store.transaction() as connection:
            return context(service, attempt, connection)
    config = service.confirmed(conn)
    row = conn.execute('SELECT session_id FROM attempts WHERE id=?', (attempt['id'],)).fetchone()
    if not row or not row['session_id'] or row['session_id'] != attempt['session_id']:
        raise MPresError('TASK context requires the actual bound session')
    old = _previous(conn, row['session_id'])
    result = {'version': 1, 'config_id': config['id'], 'task_revision':config.get('task_revision',0), 'session_id': row['session_id'],
              'source': str(service.task / 'TASK.md'), 'policy': 'once_per_session_per_task'}
    if old and old['task_text'] == config['task_text']:
        result.update(action='reuse', baseline_event_id=old['id'],
                      instruction='Use the TASK already read in this session. Do not reread it for a new job, retry or audience step.')
    elif old:
        previous = json.loads(old['detail_json'])
        result.update(action='apply_delta', baseline_event_id=old['id'],
                      base_config_id=previous['config_id'], base_task_revision=previous.get('task_revision',0),
                      delta=''.join(difflib.unified_diff(old['task_text'].splitlines(keepends=True),
                          config['task_text'].splitlines(keepends=True),
                          fromfile='previously-read/TASK.md', tofile='confirmed/TASK.md')),
                      instruction='Apply this authorized TASK change before role work; do not reread the whole document. If the baseline context is unavailable, report that fact instead of claiming to remember it.')
    else:
        result.update(action='read_full', text=config['task_text'],
                      instruction='The task and current direction are established. Read this exact TASK.md in full once before role guidance, job details or feedback work. Do not treat teacher planning fields as student slide prose.')
    return result


def attach(service, attempt, packet):
    ctx = context(service, attempt)
    packet['task_context'] = ctx
    # A host must not rely on JSON key order. This order is an explicit contract.
    packet['reading_order'] = ['task_context', 'semantic_guidance', 'job_scope_and_feedback',
                               'input_files_and_relevant_resources']
    # TASK is supplied inline once; never duplicate it as on-demand or required file.
    source = ctx['source']
    packet['input_files'] = [p for p in packet.get('input_files', []) if str(p) != source]
    return ctx


def requested(conn, service, attempt, request_id, packet):
    """Called in the existing dispatch transaction, not on packet previews."""
    ctx = packet['task_context']
    if ctx != context(service, attempt, conn):
        raise MPresError('TASK context changed before dispatch; recompile the request')
    detail = {'request_id': request_id, 'attempt_id': attempt['id'],
              'session_id': attempt['session_id'], 'config_id': ctx['config_id'],
              'action': ctx['action'], 'task_revision':ctx.get('task_revision',0)}
    if ctx['action'] == 'apply_delta':
        detail['base_config_id'] = ctx['base_config_id']
        detail['base_task_revision'] = ctx.get('base_task_revision',0)
    rows = conn.execute("SELECT detail_json FROM events WHERE kind=? AND json_extract(detail_json,'$.request_id')=?",
                        (REQUESTED, request_id)).fetchall()
    if rows:
        if any(json.loads(r['detail_json']) != detail for r in rows):
            raise MPresError('Conflicting TASK context dispatch')
    else:
        event(conn, REQUESTED, detail, attempt['job_id'])


def validate_response_request(service, request):
    """Old requests stay valid, but cannot manufacture a new reading record."""
    if request.get('operation') not in {'brief','run','audience_step'}:
        return None
    with service.store.transaction() as conn:
        stored = conn.execute("SELECT detail_json FROM events WHERE kind=? AND json_extract(detail_json,'$.request_id')=? ORDER BY id DESC LIMIT 1",
                              (REQUESTED, request['request_id'])).fetchone()
        supplied = request.get('packet', {}).get('task_context')
        if not stored:
            if supplied is not None:
                raise MPresError('No dispatched TASK context matches this response')
            return None  # request genuinely dispatched by a pre-0.8.2 engine
        detail = json.loads(stored['detail_json'])
        if not isinstance(supplied, dict) or any(
                supplied.get(k) != detail[k] for k in ('session_id','config_id','action')):
            raise MPresError('Response request has different TASK context identity')
        if request.get('attempt_id') != detail['attempt_id'] or request.get('session_id') != detail['session_id']:
            raise MPresError('Response belongs to a different task session/attempt')
        if supplied.get('task_revision',0)!=detail.get('task_revision',0):raise MPresError('Response TASK amendment identity differs')
        config={'task_text':_text(conn,detail)}
        if detail['action'] == 'read_full' and supplied.get('text') != config['task_text']:
            raise MPresError('Dispatched TASK text was changed or truncated')
        if detail['action'] == 'apply_delta':
            base={'task_text':_text(conn,{'config_id':detail['base_config_id'],'task_revision':detail.get('base_task_revision',0)})}
            expected_delta = ''.join(difflib.unified_diff(base['task_text'].splitlines(keepends=True),
                config['task_text'].splitlines(keepends=True), fromfile='previously-read/TASK.md',
                tofile='confirmed/TASK.md'))
            if supplied.get('base_config_id') != detail['base_config_id'] or supplied.get('base_task_revision',0)!=detail.get('base_task_revision',0) or supplied.get('delta') != expected_delta:
                raise MPresError('Dispatched TASK change was modified')
        return detail


def received(service, detail, receipt):
    if not detail or detail['action'] == 'reuse':
        return
    if not isinstance(receipt, str) or not receipt.strip():
        raise MPresError('TASK context completion needs the actual execution receipt')
    with service.store.transaction() as conn:
        existing = conn.execute("SELECT detail_json FROM events WHERE kind=? AND json_extract(detail_json,'$.request_id')=?",
                                (ACCEPTED, detail['request_id'])).fetchone()
        payload = {**detail, 'receipt': receipt,
                   'evidence': 'provider accepted the instructed request; not proof of semantic understanding'}
        if existing:
            if json.loads(existing['detail_json']) != payload:
                raise MPresError('Conflicting TASK context receipt')
            return
        old = _previous(conn, detail['session_id'])
        if old and (json.loads(old['detail_json'])['config_id'],json.loads(old['detail_json']).get('task_revision',0)) > (detail['config_id'],detail.get('task_revision',0)):
            return  # a late older receipt must not regress the current context
        job = conn.execute('SELECT job_id FROM attempts WHERE id=?', (detail['attempt_id'],)).fetchone()
        event(conn, ACCEPTED, payload, job['job_id'])
