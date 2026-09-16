"""Compact settled wire history into a replayable projection, never execution fiction.

A checkpoint contains exactly the routing/runtime/turn/usage facts produced by
WireIndex from the real journal. It does not grant acceptance or permit resends.
The newest real wire row remains, keeping INTEGER PRIMARY KEY monotonicity.
No sidecar is trusted as the sole source: projection is rebuilt from raw rows plus
the preceding validated seed. The seed and raw-row pruning commit together.
"""
from __future__ import annotations
import hashlib
import json
import sqlite3
from contextlib import closing
from pathlib import Path
from mpres.util import MPresError
from .maintenance_lock import readonly_connection
from .store import encode

TABLES=('rpc','threads','turns','issues')
SEED_SCHEMA='''CREATE TABLE IF NOT EXISTS wire_checkpoint (
 singleton INTEGER PRIMARY KEY CHECK(singleton=1), highwater INTEGER NOT NULL,
 projection_json TEXT NOT NULL, sha256 TEXT NOT NULL, checkpoint_id TEXT NOT NULL
)'''


def digest(text):return hashlib.sha256(text.encode()).hexdigest()


def read_seed(src):
    if not src.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='wire_checkpoint'").fetchone():return None
    row=src.execute('SELECT highwater,projection_json,sha256,checkpoint_id FROM wire_checkpoint WHERE singleton=1').fetchone()
    if row is None:return None
    if digest(row[1])!=row[2]:raise MPresError('Wire checkpoint checksum mismatch; preserve files and recover, never start a new turn')
    data=json.loads(row[1])
    if data.get('version')!=1 or data.get('highwater')!=row[0] or set(data.get('tables',{}))!=set(TABLES):
        raise MPresError('Unsupported or inconsistent wire checkpoint')
    return data


def restore(dst, data):
    """Caller holds a transaction. SQL identifiers come from schema, not payload."""
    for name in TABLES:
        columns=[r[1] for r in dst.execute('PRAGMA table_info('+name+')')]
        rows=data['tables'][name]
        if not isinstance(rows,list) or any(not isinstance(r,dict) or set(r)!=set(columns) for r in rows):
            raise MPresError('Malformed wire checkpoint rows: '+name)
        dst.execute('DELETE FROM '+name)
        dst.executemany('INSERT INTO '+name+'('+','.join(columns)+') VALUES('+','.join('?' for _ in columns)+')',
                        ([r[k] for k in columns] for r in rows))


def projection(dst, highwater):
    return {'version':1,'highwater':highwater,'tables':{
        name:[dict(r) for r in dst.execute('SELECT * FROM '+name+' ORDER BY '+('thread_id,id' if name=='turns' else 'wire_id' if name=='issues' else 'id'))]
        for name in TABLES}}


def build(journal: Path):
    from .codex_index import WireIndex,_SCHEMA
    reader=WireIndex.__new__(WireIndex)
    with closing(readonly_connection(journal)) as src, closing(sqlite3.connect(':memory:')) as dst:
        dst.row_factory=sqlite3.Row;dst.executescript(_SCHEMA)
        seed=read_seed(src);cursor=0
        if seed:restore(dst,seed);cursor=seed['highwater']
        top=src.execute('SELECT COALESCE(MAX(id),0) FROM wire').fetchone()[0]
        if top<cursor:raise MPresError('Wire journal is below checkpoint highwater')
        for row in src.execute('SELECT id,request_id,direction,payload FROM wire WHERE id>? AND id<=? ORDER BY id',(cursor,top)):
            try:msg=json.loads(row['payload'])
            except (ValueError,TypeError):reader._issue(dst,row['id'],'Malformed JSON; raw evidence retained');continue
            if not isinstance(msg,dict):reader._issue(dst,row['id'],'Non-object wire message');continue
            reader._ingest(dst,row,msg)
        return projection(dst,top)


def compact_envelope(raw, checkpoint_id, *, response=False):
    """Keep identities, exact usage and measured context metadata, not old prompts."""
    value=json.loads(raw)
    if '_current_checkpoint' in value:return raw
    keys={'runtime','receipt','handle','model','reasoning_effort','usage'} if response else {
        'request_id','attempt_id','operation','session_id','sequence','runtime','slot_id','job_id'}
    new={k:v for k,v in value.items() if k in keys}
    if not response and isinstance(value.get('packet'),dict):
        p=value['packet'];new['packet']={k:v for k,v in p.items() if k in {'kind','channel','presentation','context_bytes'}}
        if isinstance(p.get('repair_scope'),dict) and p['repair_scope'].get('case_id'):
            new['packet']['repair_scope']={'case_id':p['repair_scope']['case_id']}
        if isinstance(p.get('cost_context'),dict):
            new['packet']['cost_context']={k:v for k,v in p['cost_context'].items()
                if k in {'job_id','repair_case_id','batch_id','source','recorded_at'}}
        if isinstance(p.get('task_context'),dict):
            new['packet']['task_context']={k:v for k,v in p['task_context'].items() if k in {'action','digest','version'}}
    new['_current_checkpoint']={'id':checkpoint_id,'sha256':digest(raw),'original_bytes':len(raw.encode()),
        'disposition':'settled_no_replay_no_resend'}
    return encode(new)


def prune(journal: Path, checkpoint_id: str):
    """Exclusive task lease and a fully-settled proof are required by caller."""
    seed=build(journal);raw=encode(seed)
    with closing(sqlite3.connect(journal,timeout=1,isolation_level=None)) as c:
        c.row_factory=sqlite3.Row;c.execute('BEGIN EXCLUSIVE')
        try:
            top=c.execute('SELECT COALESCE(MAX(id),0) FROM wire').fetchone()[0]
            if top!=seed['highwater']:raise MPresError('Journal changed during checkpoint; no pruning committed')
            c.execute(SEED_SCHEMA)
            c.execute('INSERT OR REPLACE INTO wire_checkpoint VALUES(1,?,?,?,?)',(top,raw,digest(raw),checkpoint_id))
            # Keep unparsed/ambiguous raw evidence even at a settled boundary.
            issue_ids=[r['wire_id'] for r in seed['tables']['issues']]
            c.execute('CREATE TEMP TABLE preserve_wire(id INTEGER PRIMARY KEY)')
            c.executemany('INSERT OR IGNORE INTO preserve_wire VALUES(?)',((i,) for i in [top,*issue_ids]))
            before=c.execute('SELECT COUNT(*) FROM wire').fetchone()[0]
            c.execute('DELETE FROM wire WHERE id NOT IN (SELECT id FROM preserve_wire)')
            for row in c.execute('SELECT id,request,response FROM requests').fetchall():
                c.execute('UPDATE requests SET request=?,response=? WHERE id=?',(
                    compact_envelope(row['request'],checkpoint_id),
                    compact_envelope(row['response'],checkpoint_id,response=True) if row['response'] else None,row['id']))
            c.commit()
        except Exception:c.rollback();raise
        after=c.execute('SELECT COUNT(*) FROM wire').fetchone()[0]
    return {'wire_rows_before':before,'wire_rows_after':after,'highwater':top,'projection_bytes':len(raw.encode()),
        'projection_sha256':digest(raw),'issues_with_raw_evidence':len(issue_ids),'requests_reissued':0}


def evidence(journal: Path, wire_id: int):
    """Resolve a historical receipt even when its full wire body was collected."""
    if type(wire_id) is not int or wire_id<1:raise MPresError('Positive wire ID required')
    with closing(readonly_connection(journal)) as c:
        row=c.execute('SELECT id,request_id,direction,payload FROM wire WHERE id=?',(wire_id,)).fetchone()
        if row:return {'wire_id':wire_id,'state':'raw_retained','record':dict(row),'model_calls':0}
        seed=read_seed(c)
        if seed is None or wire_id>seed['highwater']:raise MPresError('No retained wire fact for this ID')
        matches=[]
        for table in TABLES:
            for row in seed['tables'][table]:
                if any((k.endswith('_wire') or k=='wire_id') and v==wire_id for k,v in row.items()):matches.append({'table':table,'fact':row})
        return {'wire_id':wire_id,'state':'body_pruned','projection_facts':matches,
            'checkpoint_highwater':seed['highwater'],'raw_reconstructed':False,'model_calls':0}
