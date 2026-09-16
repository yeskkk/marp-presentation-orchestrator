"""Durable main-agent handoffs and explicit waits, not a polling agent.

Foreground return + nonzero exit is the supported delivery channel. A stored event
alone cannot wake a host. Acknowledging delivery never changes execution facts.
"""
from __future__ import annotations
import hashlib
import json
import uuid
from mpres.util import MPresError
from .store import encode,event

WAIT_REASONS={'user_decision','environment','resource','provider_reconciliation','scheduling','main_processing','other'}

def _text(value,label):
    if not isinstance(value,str) or not value.strip() or len(value)>2000:raise MPresError(label+' must be explicit nonempty text, at most 2000 characters')
    return value

def pending(service):
    rows=service.store.rows("SELECT id,kind,detail_json,created_at FROM events WHERE kind IN ('main.handoff_opened','main.handoff_acknowledged') ORDER BY id")
    opened={};acks=set()
    for row in rows:
        d=json.loads(row['detail_json'])
        if row['kind']=='main.handoff_opened':opened[d['handoff_id']]={**d,'event_id':row['id'],'created_at':row['created_at']}
        else:acks.add(d['handoff_id'])
    unsettled=service.store.rows("SELECT request_id,attempt_id,operation,state,last_error FROM host_requests WHERE state<>'accepted' ORDER BY created_at")
    return {'pending':[v for k,v in opened.items() if k not in acks],'unsettled_requests':unsettled,
            'delivery_capability':{'foreground_result':True,'host_push':False,'note':'A database row is not a wake-up signal. Nonzero foreground exits must be received by the invoking host.'}}

def acknowledge(service,handoff_id,*,by,note):
    _text(by,'Acknowledging actor');_text(note,'Handoff handling note')
    with service.store.transaction() as c:
        rows=c.execute("SELECT kind,detail_json FROM events WHERE kind IN ('main.handoff_opened','main.handoff_acknowledged') ORDER BY id").fetchall()
        relevant=[(r['kind'],json.loads(r['detail_json'])) for r in rows if json.loads(r['detail_json']).get('handoff_id')==handoff_id]
        if not relevant:raise MPresError('Unknown handoff ID')
        if any(k=='main.handoff_acknowledged' for k,d in relevant):return {'handoff_id':handoff_id,'already_acknowledged':True,'execution_state_changed':False}
        event(c,'main.handoff_acknowledged',{'handoff_id':handoff_id,'by':by,'note':note})
    return {'handoff_id':handoff_id,'already_acknowledged':False,'execution_state_changed':False}

def terminal(service,result,origin,*,forced_reason=None):
    failed=[r for r in result.get('results',[]) if r.get('status') in {'uncertain','response_rejected','failed'}]
    attention=bool(failed) or result.get('status') in {'blocked','awaiting_confirmation'} or bool(forced_reason)
    if not attention:return result
    summary={'origin':origin,'status':result.get('status'),'reason':(forced_reason or result.get('reason') or 'Inspect exact request/workflow state before continuing')[:2000],
        'requests':[{'request_id':r.get('request_id'),'status':r.get('status'),'error':str(r.get('error',''))[:2000]} for r in failed]}
    fingerprint=hashlib.sha256(encode(summary).encode()).hexdigest();handoff=None
    with service.store.transaction() as c:
        prior=c.execute("SELECT detail_json FROM events WHERE kind='main.handoff_opened' AND json_extract(detail_json,'$.fingerprint')=? ORDER BY id DESC LIMIT 1",(fingerprint,)).fetchone()
        if prior:
            d=json.loads(prior[0]);ack=c.execute("SELECT 1 FROM events WHERE kind='main.handoff_acknowledged' AND json_extract(detail_json,'$.handoff_id')=?",(d['handoff_id'],)).fetchone()
            if not ack:handoff=d
        if handoff is None:
            handoff={**summary,'handoff_id':'handoff-'+uuid.uuid4().hex,'fingerprint':fingerprint,
                'delivery_mode':'foreground_result','host_push':False,'ack_required':True}
            event(c,'main.handoff_opened',handoff)
    return {**result,'needs_main_attention':True,'handoff':handoff,'recommended_exit_code':3 if any(r.get('status')=='uncertain' for r in failed) else 2}

def wait_start(service,*,reason,by,note,presentation=None):
    if reason not in WAIT_REASONS:raise MPresError('Unknown wait reason')
    _text(by,'Wait actor');_text(note,'Wait reason note')
    value={'wait_id':'wait-'+uuid.uuid4().hex,'reason':reason,'by':by,'note':note,'presentation':presentation}
    with service.store.transaction() as c:
        if presentation and not c.execute('SELECT 1 FROM jobs WHERE presentation=?',(presentation,)).fetchone():raise MPresError('Unknown wait presentation')
        from .telemetry import control_scope
        value.update(control_scope(c,presentation=presentation))
        event(c,'main.wait_started',value)
    return value

def wait_end(service,wait_id,*,by):
    _text(by,'Wait actor')
    with service.store.transaction() as c:
        if not c.execute("SELECT 1 FROM events WHERE kind='main.wait_started' AND json_extract(detail_json,'$.wait_id')=?",(wait_id,)).fetchone():raise MPresError('Unknown wait ID')
        if c.execute("SELECT 1 FROM events WHERE kind='main.wait_ended' AND json_extract(detail_json,'$.wait_id')=?",(wait_id,)).fetchone():return {'wait_id':wait_id,'already_ended':True}
        event(c,'main.wait_ended',{'wait_id':wait_id,'by':by})
    return {'wait_id':wait_id,'already_ended':False}
