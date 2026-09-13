"""Durable request/response boundary, separate from semantic acceptance.

Only the business database decides accepted state. Raw responses survive validator
failure. No method here invokes a provider, invents completion or releases capacity.
"""
from __future__ import annotations

import json
from mpres.util import MPresError, utc_now
from .store import encode, event

SEMANTIC = {'brief', 'run', 'audience_step'}


def issue(conn, request):
    """Call inside the same short transaction which sets the dispatch flag."""
    op = request.get('operation')
    if op not in SEMANTIC | {'create'}:
        raise MPresError('Unsupported journal operation')
    rid = request.get('request_id')
    if not isinstance(rid, str) or not rid.strip():
        raise MPresError('Missing request identity')
    raw = encode(request)
    row = conn.execute('SELECT request_json FROM host_requests WHERE request_id=?', (rid,)).fetchone()
    if row:
        if row['request_json'] != raw:
            raise MPresError('Conflicting immutable host request')
        return
    conn.execute('INSERT INTO host_requests(request_id,attempt_id,operation,session_id,request_json,created_at) VALUES(?,?,?,?,?,?)',
        (rid, request.get('attempt_id'), op, request.get('session_id'), raw, utc_now()))


class HostJournal:
    def __init__(self, service):
        self.service = service
        self.store = service.store

    def _legacy_dispatch(self, conn, request):
        """Import an actual old dispatch, not arbitrary caller supplied work."""
        op = request['operation']
        if op == 'create':
            slot = conn.execute('SELECT * FROM pool_slots WHERE id=?', (request.get('slot_id'),)).fetchone()
            if not slot or slot['state'] not in {'creating','uncertain','ready'} or request['request_id'] != f"slot-{slot['id']}":
                raise MPresError('No existing creation dispatch')
        else:
            a = conn.execute('SELECT * FROM attempts WHERE id=?', (request.get('attempt_id'),)).fetchone()
            if not a or a['session_id'] != request.get('session_id'):
                raise MPresError('Host request does not match the bound session')
            if op == 'audience_step':
                step = conn.execute('SELECT state FROM audience_steps WHERE attempt_id=? AND sequence=?', (a['id'],request.get('sequence'))).fetchone()
                expected = f"audience:{a['id']}:{request.get('sequence')}"
                if not step or step['state'] not in {'dispatched','completed'}:
                    raise MPresError('No existing audience dispatch')
            else:
                expected = ('brief:' if op == 'brief' else '') + a['id']
                b = conn.execute('SELECT * FROM attempt_briefings WHERE attempt_id=?', (a['id'],)).fetchone()
                if not b or not b['brief_dispatched' if op == 'brief' else 'run_dispatched']:
                    raise MPresError('No existing semantic dispatch')
            if request['request_id'] != expected:
                raise MPresError('Host request identity mismatch')
        issue(conn, request)

    def receive(self, request, response):
        """Persist exact incoming bytes as JSON evidence before semantic validation."""
        if not isinstance(request, dict) or request.get('operation') not in SEMANTIC | {'create'}:
            raise MPresError('Unknown host request')
        if not isinstance(response, dict):
            raise MPresError('Provider response must be a JSON object')
        raw = encode(response)
        with self.store.transaction() as conn:
            row = conn.execute('SELECT * FROM host_requests WHERE request_id=?', (request.get('request_id'),)).fetchone()
            if not row:
                self._legacy_dispatch(conn, request)
            elif row['request_json'] != encode(request):
                raise MPresError('Conflicting immutable host request')
            previous = conn.execute('SELECT response_json FROM host_responses WHERE request_id=?', (request['request_id'],)).fetchone()
            if previous:
                if previous['response_json'] != raw:
                    raise MPresError('Conflicting provider response; raw receipt cannot be overwritten')
            else:
                conn.execute('INSERT INTO host_responses VALUES(?,?,?)', (request['request_id'],raw,utc_now()))
                conn.execute("UPDATE host_requests SET state='received' WHERE request_id=? AND state<>'accepted'",(request['request_id'],))

    def validate_execution(self, request, response):
        """Truth of execution is checked before accepting semantic output."""
        if request['operation'] not in SEMANTIC:
            return
        receipt = response.get('receipt')
        if not isinstance(receipt, str) or not receipt.strip():
            raise MPresError('Actual execution receipt is missing')
        job = self.service.job(self.service.attempt(request['attempt_id'])['job_id'])
        with self.store.transaction() as conn:
            runtime = self.service.expected_runtime(conn, job)
        actual = response.get('runtime', {})
        if not isinstance(actual,dict) or any(actual.get(k) != runtime[k] for k in ('model','reasoning_effort')):
            raise MPresError('Provider runtime differs or is unavailable; do not accept a fallback model')
        calls = response.get('usage')
        if not isinstance(calls,list) or not calls:
            raise MPresError('Provider promised token reporting but supplied no call receipts')
        from .service import TOKEN_FIELDS
        # Validate the entire vector before writing any counter. Missing individual
        # fields stay null; they do not invalidate an otherwise genuine receipt.
        for call in calls:
            if not isinstance(call,dict) or not isinstance(call.get('call_id'),str) or not call['call_id'].strip():
                raise MPresError('Invalid provider usage identity')
            counters=call.get('counters')
            if not isinstance(counters,dict) or set(counters)-set(TOKEN_FIELDS):
                raise MPresError('Malformed provider usage counters')
            if any(v is not None and (type(v) is not int or v<0) for v in counters.values()):
                raise MPresError('Invalid provider usage value')
        for call in calls:
            cid=call['call_id']
            if request['operation']=='audience_step': cid=f"audience:{request['sequence']}:{cid}"
            self.service.record_usage(request['attempt_id'],cid,call['counters'])

    def state(self, rid, accepted=False, error=None):
        with self.store.transaction() as conn:
            row=conn.execute('SELECT state FROM host_requests WHERE request_id=?',(rid,)).fetchone()
            if not row: raise MPresError('Unknown host request')
            if row['state']=='accepted': return
            conn.execute('UPDATE host_requests SET state=?,last_error=?,accepted_at=? WHERE request_id=?',
                ('accepted' if accepted else 'rejected', None if accepted else str(error),utc_now() if accepted else None,rid))
            event(conn,'host.response_accepted' if accepted else 'host.response_rejected',
                {'request_id':rid,'error':None if accepted else str(error)})

    def replay_data(self, rid):
        rows=self.store.rows('SELECT q.request_json,r.response_json FROM host_requests q JOIN host_responses r USING(request_id) WHERE request_id=?',(rid,))
        if not rows: raise MPresError('No saved response; reconcile the provider, do not reissue')
        return json.loads(rows[0]['request_json']),json.loads(rows[0]['response_json'])

    def pending(self):
        return self.store.rows("SELECT q.request_id,q.attempt_id,q.operation,q.state,q.last_error,r.received_at FROM host_requests q JOIN host_responses r USING(request_id) WHERE q.state<>'accepted' ORDER BY q.created_at")
