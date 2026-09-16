"""Foreground Codex JSON-RPC adapter with incremental evidence and exact routing.

No provider limit, fallback model, approval or sandbox permission is invented.
The task database owns dispatch/acceptance. The transport journal is append-only
evidence plus immutable request envelopes; its legacy `accepted` bit is ignored.
"""
from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import threading
import time
import uuid
from concurrent.futures import Future, ThreadPoolExecutor, TimeoutError as FutureTimeout
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path

from mpres import __version__
from mpres.util import MPresError
from .codex_index import WireIndex
from .store import encode

WORKER_INSTRUCTIONS = """You are a bounded semantic worker, not the main planner.
Execute the exact runner request. Respect packet.reading_order and task_context:
read_full once, reuse existing context, apply_delta for authorized changes only.
Read all required inputs; access on-demand resources only as needed and permitted.
Use only your role/step guidance. Write only inside writable_directory if present.
Do not schedule agents, alter task policy/databases/theme, or scan other workspaces.
Return the requested semantic JSON only; do not invent runtime/usage/receipt facts.
"""


def counters_delta(before, after):
    mapping={'input_tokens':'inputTokens','cached_input_tokens':'cachedInputTokens',
             'output_tokens':'outputTokens','reasoning_tokens':'reasoningOutputTokens','total_tokens':'totalTokens'}
    out={}
    for name,field in mapping.items():
        a,b=before.get(field),after.get(field)
        if a is None or b is None:out[name]=None
        elif type(a) is not int or type(b) is not int or a<0 or b<a:
            raise MPresError('Non-monotonic/invalid cumulative usage; reconcile the exact turn')
        else:out[name]=b-a
    if out['total_tokens'] is None:raise MPresError('Provider total usage unavailable')
    return out


@dataclass
class TurnClock:
    """Monotonic idle and absolute deadlines; only real progress resets idle."""
    started: float
    idle_seconds: float
    max_seconds: float
    progress: float
    marker: int = 0

    def observe(self, marker, now):
        if marker is not None and marker>self.marker:
            self.marker=marker;self.progress=now

    def remaining(self, now):
        absolute=self.started+self.max_seconds-now
        idle=self.progress+self.idle_seconds-now
        if absolute<=0:raise MPresError('Authorized turn wall budget exhausted; execution requires reconciliation')
        if idle<=0:raise MPresError('No meaningful turn progress before idle deadline; execution requires reconciliation')
        return min(absolute,idle)


class Journal:
    def __init__(self,task):
        self.path=task/'.mpres'/'codex-bridge.sqlite3'
        self.path.parent.mkdir(parents=True,exist_ok=True)
        self.lock=threading.RLock();self.sync_lock=threading.Lock()
        from .maintenance_lock import writable_connection
        self.db=writable_connection(self.path,task,check_same_thread=False,timeout=30)
        self.db.row_factory=sqlite3.Row
        self.db.executescript('''
          CREATE TABLE IF NOT EXISTS requests(id TEXT PRIMARY KEY, request TEXT NOT NULL,
            response TEXT, accepted INTEGER NOT NULL DEFAULT 0, baseline TEXT, runtime TEXT,
            sent INTEGER NOT NULL DEFAULT 0);
          CREATE TABLE IF NOT EXISTS wire(id INTEGER PRIMARY KEY,request_id TEXT,direction TEXT NOT NULL,payload TEXT NOT NULL);
          CREATE INDEX IF NOT EXISTS wire_request_direction_id ON wire(request_id,direction,id);
          CREATE TABLE IF NOT EXISTS handles(id TEXT PRIMARY KEY,receipt TEXT NOT NULL);
        ''')
        if 'sent' not in {r[1] for r in self.db.execute('PRAGMA table_info(requests)')}:
            # An old row is never presumed unsent.
            self.db.execute('ALTER TABLE requests ADD COLUMN sent INTEGER NOT NULL DEFAULT 1')
        self.db.commit();self.pending=0;self.last_flush=time.monotonic()
        self.index=WireIndex(self.path)
        self.index.sync()

    def record(self,direction,message,request_id=None):
        with self.lock:
            cur=self.db.execute('INSERT INTO wire(request_id,direction,payload) VALUES(?,?,?)',(request_id,direction,encode(message)))
            delta=direction=='in' and str(message.get('method','')).lower().endswith('delta')
            self.pending+=1
            if not delta or self.pending>=64 or time.monotonic()-self.last_flush>=.25:self.flush()
            return cur.lastrowid

    def flush(self):
        with self.lock:
            self.db.commit();self.pending=0;self.last_flush=time.monotonic()

    def sync(self):
        with self.sync_lock:
            self.flush()
            return self.index.sync()

    def row(self,rid):
        with self.lock:
            row=self.db.execute('SELECT * FROM requests WHERE id=?',(rid,)).fetchone()
            return dict(row) if row else None

    def enqueue(self,request):
        rid=request['request_id'];raw=encode(request)
        with self.lock:
            old=self.row(rid)
            if old and json.loads(old['request'])!=request:raise MPresError('Conflicting immutable transport request')
            self.db.execute('INSERT OR IGNORE INTO requests(id,request,sent) VALUES(?,?,0)',(rid,raw));self.flush()

    def before_send(self,rid,baseline=None,runtime=None):
        with self.lock:
            row=self.row(rid)
            if not row or row['sent']:raise MPresError('Request may already have executed; never resend')
            self.db.execute('UPDATE requests SET sent=1,baseline=?,runtime=? WHERE id=?',
                            (encode(baseline) if baseline is not None else None,encode(runtime) if runtime else None,rid));self.flush()

    def save(self,rid,response):
        with self.lock:
            old=self.row(rid)
            if old['response'] and json.loads(old['response'])!=response:raise MPresError('Cannot replace genuine transport response')
            self.db.execute('UPDATE requests SET response=? WHERE id=?',(encode(response),rid));self.flush()

    def handles(self):
        with self.lock:return [dict(r) for r in self.db.execute('SELECT id,receipt FROM handles')]

    def add_handle(self,handle,receipt):
        with self.lock:
            old=self.db.execute('SELECT receipt FROM handles WHERE id=?',(handle,)).fetchone()
            if not old:self.db.execute('INSERT INTO handles VALUES(?,?)',(handle,encode(receipt)))
            self.flush()

    def close(self):
        with self.lock:self.flush();self.db.close()


class RpcTransport:
    """One stdout reader, per-RPC futures, keyed notifications persisted once."""
    def __init__(self,journal,argv,cwd,rpc_timeout=60):
        self.journal=journal;self.timeout=rpc_timeout
        self.guard=threading.RLock();self.send_lock=threading.Lock();self.changed=threading.Condition()
        self.pending={};self.failure=None;self.interactions={};self.closed=False
        self.process=subprocess.Popen(argv,cwd=cwd,stdin=subprocess.PIPE,stdout=subprocess.PIPE,
                                      stderr=subprocess.DEVNULL,text=True,encoding='utf-8',bufsize=1)
        self.reader=threading.Thread(target=self._read,daemon=True,name='mpres-codex-receiver')
        self.reader.start()

    def _read(self):
        try:
            for line in self.process.stdout:
                message=json.loads(line)
                if not isinstance(message,dict):raise MPresError('Malformed Codex message')
                self.journal.record('in',message)  # no ambient request_id
                if 'id' in message and 'method' not in message:
                    with self.guard:f=self.pending.get(encode(message['id']))
                    if f is not None and not f.done():f.set_result(message)
                elif 'id' in message and 'method' in message:
                    thread=(message.get('params') or {}).get('threadId','*')
                    self.interactions[thread]=message['method']
                    # Never silently answer permission/user-input requests.
                    self.send({'id':message['id'],'error':{'code':-32601,'message':'User interaction required; unattended approval is prohibited'}})
                with self.changed:self.changed.notify_all()
            if not self.closed:raise MPresError('Codex disconnected; execution may still be unresolved')
        except Exception as exc:
            self.failure=exc
            with self.guard:
                for f in self.pending.values():
                    if not f.done():f.set_exception(exc)
            with self.changed:self.changed.notify_all()

    def send(self,message,request_id=None):
        with self.send_lock:
            if self.failure:raise self.failure
            self.journal.record('out',message,request_id)
            self.process.stdin.write(encode(message)+'\n');self.process.stdin.flush()

    def rpc(self,method,params=None,*,request_id=None):
        rid=uuid.uuid4().hex;future=Future()
        with self.guard:self.pending[encode(rid)]=future
        try:
            self.send({'id':rid,'method':method,'params':params or {}},request_id)
            try:reply=future.result(timeout=self.timeout)
            except FutureTimeout as exc:raise MPresError('RPC timeout; request identity is saved, do not resubmit') from exc
            if 'error' in reply:raise MPresError('Codex RPC error: '+encode(reply['error']))
            return reply['result']
        finally:
            with self.guard:self.pending.pop(encode(rid),None)

    def wait(self,seconds,thread):
        if self.failure:raise self.failure
        if thread in self.interactions or '*' in self.interactions:
            raise MPresError('Codex requests explicit user interaction; no automatic permission grant')
        with self.changed:self.changed.wait(timeout=min(seconds,.25))

    def close(self):
        self.closed=True
        if self.process.stdin:self.process.stdin.close()
        try:self.process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            self.process.terminate()
            try:self.process.wait(timeout=3)
            except subprocess.TimeoutExpired:self.process.kill();self.process.wait()
        self.reader.join(timeout=3)
        if self.process.stdout:self.process.stdout.close()


class CodexBridge:
    def __init__(self,task: Path,*,executable='codex',transport_factory=RpcTransport):
        from .runner import Runner
        self.task=task.resolve();self.runner=Runner(self.task);self.settings=self.runner.settings()
        self.loaded={};self.guard=threading.RLock();self.session_locks={}
        self.journal=None;self.transport=None
        try:
            import fcntl
        except ImportError as exc:raise MPresError('Native bridge ownership is supported on POSIX only') from exc
        self.ownership=(self.task/'.mpres'/'codex-adapter.lock').open('a')
        try:fcntl.flock(self.ownership,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError as exc:
            self.ownership.close();raise MPresError('Another adapter owns this task') from exc
        try:
            self.journal=Journal(self.task)
            # Default stdio works across CLI versions; do not assume a --stdio flag.
            self.transport=transport_factory(self.journal,[executable,'app-server'],self.task)
            self.transport.rpc('initialize',{'clientInfo':{'name':'mpres','version':__version__},'capabilities':{'experimentalApi':True}})
            self.transport.send({'method':'initialized','params':{}})
        except Exception:
            self.close();raise

    @staticmethod
    def runtime(receipt,expected):
        actual={'model':receipt.get('model'),'reasoning_effort':receipt.get('reasoningEffort')}
        if actual!={k:expected[k] for k in actual}:
            raise MPresError('Actual provider runtime missing or different; no fallback accepted')
        return actual

    def capabilities(self):
        data=self.transport.rpc('thread/loaded/list',{})
        handles=set(data['data']);cursor=data.get('nextCursor');seen=set()
        while cursor:
            if cursor in seen:raise MPresError('Repeated provider inventory cursor')
            seen.add(cursor);data=self.transport.rpc('thread/loaded/list',{'cursor':cursor})
            handles.update(data['data']);cursor=data.get('nextCursor')
        # Read only missing known identities. Do not resume every idle thread or
        # request includeTurns=True to discover counters on every inventory pass.
        for saved in self.journal.handles():
            if saved['id'] not in handles:
                result=self.transport.rpc('thread/read',{'threadId':saved['id'],'includeTurns':False})
                if result.get('thread',{}).get('id')!=saved['id']:raise MPresError('Provider inventory identity mismatch')
                handles.add(saved['id'])
        self.journal.sync()
        limit=self.runner.settings()['provider']['handle_limit']
        if type(limit) is not int or limit<1:
            raise MPresError('Set an explicitly confirmed local handle ceiling; this adapter cannot discover a provider global cap')
        return {'handle_limit':limit,'handles':sorted(handles),'supports_close':False,'supports_reset':False,
                'usage_reporting':True,'receipt':encode({'adapter':'codex-app-server','source':'live inventory',
                  'capacity_kind':'confirmed adapter-local ceiling, not provider global limit',
                  'wire_highwater':self.journal.index.summary()['cursor']})}

    def _lock(self,handle):
        with self.guard:return self.session_locks.setdefault(handle,threading.Lock())

    def _reference(self,thread,turn=None,wire=None):
        return encode({'adapter':'codex-app-server','journal':'.mpres/codex-bridge.sqlite3',
                       'thread_id':thread,'turn_id':turn,'wire_row':wire})

    def _source(self,request,response):
        if request['operation']=='run' and request['packet'].get('writable_directory'):
            from .files import inside
            work=inside(self.task/'.mpres'/'work',request['attempt_id'])
            path=Path(request['packet']['writable_directory'])
            if not path.is_absolute() or not path.is_relative_to(work):raise MPresError('Invalid runner output boundary')
            checked=inside(work,path.relative_to(work).as_posix())
            if not checked.is_relative_to(work/'output') or not checked.is_dir():raise MPresError('Output is outside this attempt')
            response['source_dir']=checked.relative_to(work).as_posix()
        return response

    def completed(self,request):
        self.journal.sync();row=self.journal.row(request['request_id'])
        if row is None:return None
        if row['response']:return json.loads(row['response'])
        if request['operation']=='create':
            with closing(self.journal.index.connect()) as conn:
                records=conn.execute("SELECT * FROM rpc WHERE request_id=? AND method='thread/start' AND response_wire IS NOT NULL",(request['request_id'],)).fetchall()
            if not records:return None
            if len(records)!=1:raise MPresError('Ambiguous thread creation history')
            rpc=records[0];handle=rpc['thread_id'];record=self.journal.index.thread(handle)
            if not record:raise MPresError('Creation lacks provider thread evidence')
            actual=self.runtime({'model':record['model'],'reasoningEffort':record['effort']},request['runtime'])
            response={'handle':handle,**actual,'receipt':self._reference(handle,wire=rpc['response_wire'])}
            self.journal.add_handle(handle,response);return response
        turns=self.journal.index.turns(request_id=request['request_id'])
        if not turns:return None
        if len(turns)!=1:raise MPresError('Multiple actual turns require explicit usage reconciliation')
        turn=turns[0]
        if turn['thread_id']!=request['session_id']:raise MPresError('Turn belongs to another thread')
        if turn['runtime_error']:raise MPresError('Provider model reroute or identity conflict: '+turn['runtime_error'])
        if not turn['end_wire']:return None
        if turn['state']!='completed':raise MPresError('Provider terminal state is '+turn['state']+'; do not invent completion')
        if not turn['usage_json'] or row['baseline'] is None or row['runtime'] is None or turn['final_text'] is None:
            return None  # some versions deliver usage just after completed
        actual=json.loads(row['runtime'])
        if actual!={k:request['runtime'][k] for k in actual}:raise MPresError('Stored runtime does not match request')
        try:semantic=json.loads(turn['final_text'])
        except ValueError:semantic=turn['final_text']  # preserve real completion for the normal reject path
        response={'runtime':actual,'receipt':self._reference(turn['thread_id'],turn['id'],turn['end_wire']),
                  'usage':[{'call_id':turn['id'],'counters':counters_delta(json.loads(row['baseline']),json.loads(turn['usage_json']))}]}
        if request['operation']=='brief':response['readback']=semantic.get('readback',semantic) if isinstance(semantic,dict) else semantic
        else:response['result']=semantic
        return self._source(request,response)

    def execute(self,request):
        if '_current_checkpoint' in request:raise MPresError('Settled request body was pruned; it cannot be re-executed or resent')
        if request['operation']=='capabilities':return self.capabilities()
        if request.get('operation') not in {'create','brief','run','audience_step'}:raise MPresError('Unsupported bridge operation')
        identity=request['request_id'];key=request.get('session_id') or 'create-pool'
        with self._lock(key):
            self.journal.enqueue(request);row=self.journal.row(identity)
            if row['response'] or row['sent']:
                response=self.completed(request)
                if response is None:raise MPresError('Sent request unresolved; reconcile, never resend')
                self.journal.save(identity,response);return response
            if request['operation']=='create':
                limit=self.runner.settings()['provider']['handle_limit']
                if type(limit) is not int or len(self.journal.handles())>=limit:raise MPresError('Local persistent pool ceiling reached')
                expected=request['runtime'];self.journal.before_send(identity)
                receipt=self.transport.rpc('thread/start',{'model':expected['model'],
                    'config':{'model_reasoning_effort':expected['reasoning_effort']},'cwd':str(self.task),
                    'developerInstructions':WORKER_INSTRUCTIONS,'ephemeral':False},request_id=identity)
                self.runtime(receipt,expected);handle=receipt['thread']['id'];self.loaded[handle]=receipt
                self.journal.add_handle(handle,receipt);response=self.completed(request)
            else:
                handle=request['session_id'];expected=request['runtime']
                receipt=self.loaded.get(handle)
                if receipt is None:
                    receipt=self.transport.rpc('thread/resume',{'threadId':handle,'excludeTurns':True})
                    self.loaded[handle]=receipt
                if receipt.get('thread',{}).get('id')!=handle:raise MPresError('Resume returned wrong thread')
                actual=self.runtime(receipt,expected);self.journal.sync()
                baseline=self.journal.index.latest_usage(handle)
                self.journal.before_send(identity,baseline,actual)
                packet=request['packet']
                prompt='Execute this exact '+request['operation']+' request. Return only semantic JSON. '+('For brief return an object containing readback. ' if request['operation']=='brief' else '')+encode(packet)
                started=time.monotonic()
                self.transport.rpc('turn/start',{'threadId':handle,'model':expected['model'],'effort':expected['reasoning_effort'],
                    'input':[{'type':'text','text':prompt}]},request_id=identity)
                settings=self.runner.settings();hard=settings.get('provider_timeout_seconds',1200)
                idle=settings.get('provider_idle_timeout_seconds',hard)
                clock=TurnClock(started,idle,hard,started)
                while True:
                    response=self.completed(request)
                    if response is not None:break
                    turns=self.journal.index.turns(request_id=identity)
                    if turns:clock.observe(turns[-1]['progress_wire'],time.monotonic())
                    self.transport.wait(clock.remaining(time.monotonic()),handle)
            if response is None:raise MPresError('Missing creation/turn evidence; reconcile without a new call')
            self.journal.save(identity,response);return response

    def reconcile(self,request_id):
        """Read-only reconciliation, never a start/resume/retry of a model turn."""
        from .host_journal import HostJournal
        settled=self.runner.store.rows('SELECT state,request_json FROM host_requests WHERE request_id=?',(request_id,))
        if settled and settled[0]['state']=='accepted' and '_current_checkpoint' in json.loads(settled[0]['request_json']):return self.runner.replay(request_id)
        q=self.runner.store.rows('SELECT request_json FROM host_requests WHERE request_id=?',(request_id,))
        if not q:raise MPresError('No canonical business request to reconcile')
        request=json.loads(q[0]['request_json']);response=self.completed(request)
        if response is None and request.get('session_id'):
            # Explicit recovery only. Routine inventory never fetches full turns.
            result=self.transport.rpc('thread/read',{'threadId':request['session_id'],'includeTurns':True},request_id='reconcile:'+request_id)
            self.journal.sync()
            response=self.completed(request)
            turns=self.journal.index.turns(request_id=request_id)
            if len(turns)!=1:raise MPresError('Cannot identify exactly one original turn')
            matches=[t for t in result.get('thread',{}).get('turns',[]) if t.get('id')==turns[0]['id']]
            if response is None and len(matches)==1 and matches[0].get('status')=='completed':
                # Evidence remains the real RPC row. Do not manufacture a server
                # notification. Without persisted terminal/usage, require another
                # authoritative source rather than guessing from authored prose.
                raise MPresError('History confirms completion; persisted terminal/usage remains incomplete. No model was restarted.')
        if response is None:raise MPresError('No complete provider evidence; keep execution unresolved')
        self.journal.save(request_id,response)
        return self.runner.accept(request,response)

    def drive(self,cycles=100):
        if type(cycles) is not int or cycles<1:raise MPresError('cycles must be positive')
        def execute(q):
            started=time.monotonic()
            from .cost_report import wall_now
            wall_started=wall_now()
            prior=self.journal.row(q['request_id'])
            invocation_kind='reconciliation' if prior and prior.get('sent') else 'provider_invoke'
            try:return {'request_id':q['request_id'],'status':'accepted','result':self.runner.accept(q,self.execute(q))}
            except Exception as exc:
                from .host_journal import HostJournal
                journal=HostJournal(self.runner.service)
                known=False
                if q['operation']!='create':
                    try:a,b=journal.replay_data(q['request_id']);journal.validate_execution(a,b);known=True
                    except Exception:pass
                if not known:
                    if q['operation']=='create':self.runner.creation_uncertain(q['slot_id'],str(exc))
                    else:self.runner.service.uncertain(q['attempt_id'],str(exc))
                return {'request_id':q['request_id'],'status':'response_rejected' if known else 'uncertain','error':str(exc)}
            finally:
                from .store import event
                with self.runner.store.transaction() as conn:event(conn,'provider.duration',{'request_id':q['request_id'],'seconds':time.monotonic()-started,'started_at':wall_started,'finished_at':wall_now(),'invocation_kind':invocation_kind})
        # Only canonical outstanding requests may block/replay. A local historical
        # accepted=0 flag is not a second workflow state machine.
        outstanding=self.runner.store.rows("SELECT request_json FROM host_requests WHERE state<>'accepted' ORDER BY created_at")
        from .supervision import terminal
        last={}
        for _ in range(cycles):
            if outstanding:
                requests=[json.loads(r['request_json']) for r in outstanding];outstanding=[]
                last={'status':'reconciling','requests':requests}
            else:
                self.runner.observe_host(self.capabilities());last=self.runner.tick();requests=last['requests']
            if not requests:return terminal(self.runner.service,last,'bridge.drive')
            for q in requests:
                if q['operation']!='capabilities':self.journal.enqueue(q)
            # tick already made admission/independence decisions transactionally.
            with ThreadPoolExecutor(max_workers=max(1,len(requests))) as pool:
                results=list(pool.map(execute,requests))
            last={**last,'results':results}
            if any(r['status']!='accepted' for r in results):return terminal(self.runner.service,last,'bridge.drive')
        return terminal(self.runner.service,last,'bridge.drive',forced_reason='Authorized foreground cycle budget reached; inspect state before continuing')

    def close(self):
        if self.transport:self.transport.close();self.transport=None
        if self.journal:self.journal.close();self.journal=None
        if getattr(self,'ownership',None):self.ownership.close();self.ownership=None
        if getattr(self,'task',None) and getattr(self,'runner',None):
            from .checkpoints import maybe_run
            self.maintenance_result=maybe_run(self.task)

    def __enter__(self):return self
    def __exit__(self,*args):self.close()
