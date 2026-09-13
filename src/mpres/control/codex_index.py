"""Incremental projections of an append-only Codex wire journal.

The source journal is evidence, not a task state machine. This expendable sidecar
keeps routing/turn/usage facts only; it never marks an mpres job accepted. Import
uses a high-water mark and bounded batches, including unrecognised events. RPC
ids and (thread, turn) keys -- never an ambient 'current request' -- route input.
"""
from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from pathlib import Path

from mpres.util import MPresError
from .store import encode

_SCHEMA = """
CREATE TABLE IF NOT EXISTS source (
 singleton INTEGER PRIMARY KEY CHECK(singleton=1), path TEXT NOT NULL,
 device INTEGER NOT NULL, inode INTEGER NOT NULL, cursor INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS rpc (
 id TEXT PRIMARY KEY, request_id TEXT, method TEXT NOT NULL, thread_id TEXT,
 out_wire INTEGER NOT NULL, response_wire INTEGER, turn_id TEXT, error_json TEXT
);
CREATE INDEX IF NOT EXISTS rpc_request ON rpc(request_id,method,out_wire);
CREATE TABLE IF NOT EXISTS threads (
 id TEXT PRIMARY KEY, model TEXT, effort TEXT, runtime_wire INTEGER,
 created_wire INTEGER, usage_json TEXT, usage_wire INTEGER
);
CREATE TABLE IF NOT EXISTS turns (
 thread_id TEXT NOT NULL, id TEXT NOT NULL, request_id TEXT,
 start_wire INTEGER, end_wire INTEGER, state TEXT NOT NULL DEFAULT 'unknown',
 started_ms INTEGER, completed_ms INTEGER,
 usage_json TEXT, usage_wire INTEGER, final_text TEXT, final_wire INTEGER,
 progress_wire INTEGER, progress_ms INTEGER, runtime_error TEXT,
 PRIMARY KEY(thread_id,id)
);
CREATE INDEX IF NOT EXISTS turns_request ON turns(request_id,start_wire);
CREATE INDEX IF NOT EXISTS turns_thread_end ON turns(thread_id,end_wire);
CREATE TABLE IF NOT EXISTS issues (
 wire_id INTEGER PRIMARY KEY, reason TEXT NOT NULL
);
PRAGMA user_version=1;
"""


def _rpc_id(value):
    # JSON-RPC integer 1 must not collide with string "1".
    return encode(value)


def _time(message):
    value = message.get('emittedAtMs')
    return value if type(value) is int else None


class WireIndex:
    def __init__(self, journal: Path, path: Path | None = None):
        self.journal = journal.resolve()
        self.path = (path or journal.with_name('codex-index.sqlite3')).resolve()
        if self.path == self.journal or not self.journal.is_file():
            raise MPresError('A distinct index and an existing wire journal are required')
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self.connect()) as conn:
            conn.executescript(_SCHEMA)
            st = self.journal.stat()
            old = conn.execute('SELECT * FROM source').fetchone()
            identity = (str(self.journal), st.st_dev, st.st_ino)
            if old and tuple(old[k] for k in ('path','device','inode')) != identity:
                raise MPresError('Wire source was replaced; build a new sidecar, do not reuse its cursor')
            conn.execute('INSERT OR IGNORE INTO source(singleton,path,device,inode) VALUES(1,?,?,?)', identity)
            conn.commit()

    def connect(self):
        conn = sqlite3.connect(self.path, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute('PRAGMA busy_timeout=30000')
        conn.execute('PRAGMA foreign_keys=ON')
        return conn

    def sync(self, *, batch_size: int = 512, max_rows: int | None = None):
        if type(batch_size) is not int or not 1 <= batch_size <= 10000:
            raise MPresError('Invalid wire batch size')
        if max_rows is not None and (type(max_rows) is not int or max_rows < 1):
            raise MPresError('max_rows must be positive')
        read = 0
        with closing(sqlite3.connect(self.journal.as_uri()+'?mode=ro', uri=True)) as src, closing(self.connect()) as dst:
            src.row_factory = sqlite3.Row
            if not {'id','request_id','direction','payload'} <= {r[1] for r in src.execute('PRAGMA table_info(wire)')}:
                raise MPresError('Unsupported wire journal schema')
            top = src.execute('SELECT COALESCE(MAX(id),0) FROM wire').fetchone()[0]
            start = dst.execute('SELECT cursor FROM source').fetchone()[0]
            if top < start:
                top=src.execute('SELECT COALESCE(MAX(id),0) FROM wire').fetchone()[0]
            if top < start:
                raise MPresError('Wire journal truncated below its indexed cursor')
            while max_rows is None or read < max_rows:
                # The source's INTEGER PRIMARY KEY handles this query. No JSON
                # filter/full-history messages() call belongs in the hot path.
                dst.execute('BEGIN IMMEDIATE')
                try:
                    cursor = dst.execute('SELECT cursor FROM source').fetchone()[0]
                    limit = min(batch_size, max_rows-read) if max_rows else batch_size
                    rows = src.execute('SELECT id,request_id,direction,payload FROM wire WHERE id>? AND id<=? ORDER BY id LIMIT ?', (cursor,top,limit)).fetchall()
                    if not rows:
                        dst.commit()
                        break
                    for row in rows:
                        try:
                            msg = json.loads(row['payload'])
                        except (ValueError, TypeError):
                            self._issue(dst,row['id'],'Malformed JSON; raw evidence retained')
                            continue
                        if not isinstance(msg,dict):
                            self._issue(dst,row['id'],'Non-object wire message')
                            continue
                        self._ingest(dst,row,msg)
                    dst.execute('UPDATE source SET cursor=? WHERE singleton=1', (rows[-1]['id'],))
                    dst.commit()
                    read += len(rows)
                except Exception:
                    dst.rollback()
                    raise
            cursor = dst.execute('SELECT cursor FROM source').fetchone()[0]
        return {'rows_read':read,'cursor':cursor,'source_highwater':top,
                'complete':cursor >= top,'source_modified':False,'model_calls':0}

    @staticmethod
    def _issue(conn, wire, reason):
        conn.execute('INSERT OR REPLACE INTO issues VALUES(?,?)',(wire,reason))

    @staticmethod
    def _turn(conn, thread, turn):
        conn.execute('INSERT OR IGNORE INTO threads(id) VALUES(?)',(thread,))
        conn.execute('INSERT OR IGNORE INTO turns(thread_id,id) VALUES(?,?)',(thread,turn))

    def _bind(self, conn, thread, turn, request, wire):
        self._turn(conn,thread,turn)
        old=conn.execute('SELECT request_id FROM turns WHERE thread_id=? AND id=?',(thread,turn)).fetchone()[0]
        if old is not None and request is not None and old != request:
            self._issue(conn,wire,'Conflicting request ownership for one thread/turn')
            conn.execute("UPDATE turns SET runtime_error='conflicting request ownership' WHERE thread_id=? AND id=?",(thread,turn))
            return
        if request:
            conn.execute('UPDATE turns SET request_id=? WHERE thread_id=? AND id=?',(request,thread,turn))

    def _ingest(self, conn, row, message):
        wire=row['id'];direction=row['direction'];method=message.get('method')
        p=message.get('params') or {}
        if not isinstance(p,dict):
            self._issue(conn,wire,'Malformed params');return
        if direction=='out' and 'id' in message and method:
            conn.execute('INSERT OR IGNORE INTO rpc(id,request_id,method,thread_id,out_wire) VALUES(?,?,?,?,?)',
                         (_rpc_id(message['id']),row['request_id'],method,p.get('threadId'),wire))
            return
        if direction!='in':return
        if 'id' in message and not method:
            rpc=conn.execute('SELECT * FROM rpc WHERE id=?',(_rpc_id(message['id']),)).fetchone()
            if rpc is None:
                self._issue(conn,wire,'RPC response has no recorded outgoing identity');return
            conn.execute('UPDATE rpc SET response_wire=?,error_json=? WHERE id=?',
                         (wire,encode(message['error']) if 'error' in message else None,rpc['id']))
            result=message.get('result') or {}
            if not isinstance(result,dict):return
            thread=result.get('thread') or {}
            if isinstance(thread,dict) and thread.get('id') and rpc['method'] in {'thread/start','thread/resume','thread/read'}:
                tid=thread['id']
                conn.execute('INSERT OR IGNORE INTO threads(id) VALUES(?)',(tid,))
                model=result.get('model',thread.get('model'));effort=result.get('reasoningEffort',thread.get('reasoningEffort'))
                if model and effort:
                    conn.execute('UPDATE threads SET model=?,effort=?,runtime_wire=? WHERE id=?',(model,effort,wire,tid))
                if rpc['method']=='thread/start':
                    conn.execute('UPDATE threads SET created_wire=COALESCE(created_wire,?) WHERE id=?',(wire,tid))
                conn.execute('UPDATE rpc SET thread_id=? WHERE id=?',(tid,rpc['id']))
                if rpc['method']=='thread/read':
                    for item in thread.get('turns',[]):
                        if not isinstance(item,dict) or not item.get('id'):continue
                        turn_id=item['id'];self._turn(conn,tid,turn_id)
                        if item.get('status') in {'completed','interrupted','failed'}:
                            conn.execute('UPDATE turns SET state=?,end_wire=COALESCE(end_wire,?) WHERE thread_id=? AND id=?', (item['status'],wire,tid,turn_id))
                            for output in item.get('items',[]):self._item(conn,tid,turn_id,wire,output)

            turn=result.get('turn') or {}
            if rpc['method']=='turn/start' and isinstance(turn,dict) and turn.get('id') and rpc['thread_id']:
                self._bind(conn,rpc['thread_id'],turn['id'],rpc['request_id'],wire)
                conn.execute('UPDATE rpc SET turn_id=? WHERE id=?',(turn['id'],rpc['id']))
                conn.execute('UPDATE turns SET start_wire=COALESCE(start_wire,?) WHERE thread_id=? AND id=?',(wire,rpc['thread_id'],turn['id']))
            return
        thread=p.get('threadId');turn=p.get('turnId') or (p.get('turn') or {}).get('id')
        if not isinstance(thread,str) or not isinstance(turn,str):return
        self._turn(conn,thread,turn)
        if method=='turn/started':
            # Notifications may precede the turn/start RPC response. Never use
            # legacy row.request_id: it was an unsafe process-global variable.
            waiting=conn.execute("SELECT * FROM rpc WHERE thread_id=? AND method='turn/start' AND (turn_id IS NULL OR turn_id=?) ORDER BY out_wire DESC LIMIT 2",(thread,turn)).fetchall()
            if len(waiting)==1:self._bind(conn,thread,turn,waiting[0]['request_id'],wire)
            started=(p.get('turn') or {}).get('startedAt')
            stamp=int(started*1000) if isinstance(started,(float,int)) else _time(message)
            conn.execute("UPDATE turns SET start_wire=COALESCE(start_wire,?),state=CASE WHEN end_wire IS NULL THEN 'inProgress' ELSE state END,started_ms=COALESCE(started_ms,?) WHERE thread_id=? AND id=?",(wire,stamp,thread,turn))
        elif method=='thread/tokenUsage/updated':
            usage=(p.get('tokenUsage') or {}).get('total')
            if not isinstance(usage,dict):
                self._issue(conn,wire,'Token update lacks cumulative total');return
            old=conn.execute('SELECT usage_json FROM turns WHERE thread_id=? AND id=?',(thread,turn)).fetchone()[0]
            old=json.loads(old) if old else {}
            conn.execute('UPDATE turns SET usage_json=?,usage_wire=? WHERE thread_id=? AND id=?',(encode(usage),wire,thread,turn))
            conn.execute('UPDATE threads SET usage_json=?,usage_wire=? WHERE id=?',(encode(usage),wire,thread))
            if type(usage.get('totalTokens')) is int and usage['totalTokens'] > (old.get('totalTokens') or 0):
                self._progress(conn,thread,turn,wire,_time(message))
        elif method=='item/completed':
            self._item(conn,thread,turn,wire,p.get('item') or {})
            self._progress(conn,thread,turn,wire,_time(message))
        elif method=='turn/completed':
            obj=p.get('turn') or {};state=obj.get('status','unknown')
            stamp=obj.get('completedAt')
            stamp=int(stamp*1000) if isinstance(stamp,(float,int)) else _time(message)
            previous=conn.execute('SELECT state,end_wire FROM turns WHERE thread_id=? AND id=?',(thread,turn)).fetchone()
            if previous['end_wire'] is not None and previous['state']!=state:
                self._issue(conn,wire,'Conflicting terminal status');return
            conn.execute('UPDATE turns SET state=?,end_wire=COALESCE(end_wire,?),completed_ms=COALESCE(completed_ms,?) WHERE thread_id=? AND id=?',(state,wire,stamp,thread,turn))
            for item in obj.get('items',[]):self._item(conn,thread,turn,wire,item)
        elif method=='model/rerouted':
            conn.execute('UPDATE turns SET runtime_error=? WHERE thread_id=? AND id=?',(encode(p),thread,turn))
        elif isinstance(method,str) and method.lower().endswith('delta') and p.get('delta'):
            self._progress(conn,thread,turn,wire,_time(message))

    @staticmethod
    def _progress(conn,thread,turn,wire,stamp):
        conn.execute('UPDATE turns SET progress_wire=?,progress_ms=COALESCE(?,progress_ms) WHERE thread_id=? AND id=?',(wire,stamp,thread,turn))

    @staticmethod
    def _item(conn,thread,turn,wire,item):
        if isinstance(item,dict) and item.get('type')=='agentMessage' and item.get('phase') in {None,'final_answer'} and isinstance(item.get('text'),str):
            conn.execute('UPDATE turns SET final_text=?,final_wire=? WHERE thread_id=? AND id=?',(item['text'],wire,thread,turn))

    def turns(self, *, request_id=None, thread_id=None):
        if (request_id is None)==(thread_id is None):raise MPresError('Supply one exact request or thread')
        field,value=('request_id',request_id) if request_id is not None else ('thread_id',thread_id)
        with closing(self.connect()) as conn:
            return [dict(r) for r in conn.execute(f'SELECT * FROM turns WHERE {field}=? ORDER BY start_wire', (value,))]

    def thread(self,handle):
        with closing(self.connect()) as conn:
            row=conn.execute('SELECT * FROM threads WHERE id=?',(handle,)).fetchone()
            return dict(row) if row else None

    def latest_usage(self,handle):
        row=self.thread(handle)
        if row and row['usage_json']:return json.loads(row['usage_json'])
        if row and row['created_wire'] and not self.turns(thread_id=handle):
            return dict.fromkeys(('inputTokens','cachedInputTokens','outputTokens','reasoningOutputTokens','totalTokens'),0)
        raise MPresError('No authoritative usage baseline for this thread; never infer zero for an imported thread')

    def summary(self):
        with closing(self.connect()) as conn:
            return {'index':str(self.path),'source':str(self.journal),
                    'cursor':conn.execute('SELECT cursor FROM source').fetchone()[0],
                    **{name:conn.execute(f'SELECT COUNT(*) FROM {name}').fetchone()[0] for name in ('rpc','threads','turns','issues')},
                    'model_calls':0,'source_modified':False}
