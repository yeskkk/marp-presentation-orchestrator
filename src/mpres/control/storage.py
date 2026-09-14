"""Conservative, offline retention. No model, permission grant, or guessed status.

Raw expired bodies can be replaced by hashed retention records. Stable wire IDs,
RPC routing, terminal/usage/final-message evidence and business facts survive.
The retained projection is deliberately identical when the sidecar is rebuilt.
No unbounded compressed archive is created. Explicit optional backups are owned
by the caller; delivery sources, task requirements and usage are never removed.
"""
from __future__ import annotations
import hashlib
import json
import shutil
import sqlite3
import uuid
from contextlib import closing
from datetime import datetime,timezone,timedelta
from pathlib import Path
from mpres.util import MPresError,utc_now
from .store import encode,Store
from .maintenance_lock import Lease,readonly_connection

DATABASES=('task.sqlite3','codex-bridge.sqlite3','codex-index.sqlite3')

def digest(value):return hashlib.sha256(value.encode('utf-8')).hexdigest()
def stamp(value):
    if not value:return None
    try:
        dt=datetime.fromisoformat(value.replace('Z','+00:00'))
        return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)
    except (ValueError,TypeError):return None

def inspect(task: Path):
    output={'version':1,'task':str(task.resolve()),'read_only':True,'model_calls':0,'databases':[]}
    for name in DATABASES:
        p=task/'.mpres'/name
        if not p.exists():continue
        with closing(readonly_connection(p)) as c:
            tables=[]
            for row in c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"):
                table=row[0];quoted='"'+table.replace('"','""')+'"'
                item={'name':table,'rows':c.execute('SELECT COUNT(*) FROM '+quoted).fetchone()[0]}
                try:item['allocated_bytes']=c.execute('SELECT SUM(pgsize) FROM dbstat WHERE name=?',(table,)).fetchone()[0] or 0
                except sqlite3.Error:item['allocated_bytes']=None
                tables.append(item)
            output['databases'].append({'name':name,'bytes':p.stat().st_size,
                'wal_bytes':Path(str(p)+'-wal').stat().st_size if Path(str(p)+'-wal').exists() else 0,
                'schema_version':c.execute('PRAGMA user_version').fetchone()[0],
                'freelist_bytes':c.execute('PRAGMA freelist_count').fetchone()[0]*c.execute('PRAGMA page_size').fetchone()[0],
                'tables':tables})
    output['database_bytes']=sum(d['bytes']+d['wal_bytes'] for d in output['databases'])
    output['resource_cache_bytes']=sum(p.stat().st_size for p in (task/'.mpres'/'resource-cache').glob('*') if p.is_file() and not p.is_symlink())
    output['not_counted_as_database']='Artifacts, work directories and optional caller-owned backups are not removed by this command.'
    return output

def _business(task):
    with closing(readonly_connection(task/'.mpres'/'task.sqlite3')) as c:
        tables={r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        def rows(t):return [dict(r) for r in c.execute('SELECT * FROM '+t)] if t in tables else []
        return {t:rows(t) for t in ('attempts','host_requests','sessions','gate_runs','checks','usage','artifacts','pool_slots')}

def _quiescent(business):
    active=[r['id'] for r in business['attempts'] if r['state'] in {'reserved','running','uncertain'}]
    active += [r['id'] for r in business['gate_runs'] if r['state']=='running']
    active += [str(r['id']) for r in business['pool_slots'] if r['state'] in {'creating','uncertain'}]
    if active:raise MPresError('Maintenance blocked by live or unresolved work: '+', '.join(active[:10]))
    if any(r['state'] in {'issued','received','rejected'} for r in business['host_requests']):
        raise MPresError('Maintenance blocked by an unaccepted host request; reconcile it, never infer completion from age')

def _eligible_threads(c,b,now,success_days,failure_days):
    attempts={a['id']:a for a in b['attempts']};accepted={r['request_id']:r for r in b['host_requests'] if r['state']=='accepted'}
    sessions={s['id']:s for s in b['sessions']};good={};bad=set()
    for row in c.execute('SELECT id,request,response,sent FROM requests'):
        try:q=json.loads(row['request']);response=json.loads(row['response']) if row['response'] else {}
        except (ValueError,TypeError):continue
        thread=q.get('session_id') or response.get('handle')
        if not isinstance(thread,str):continue
        a=attempts.get(q.get('attempt_id'));limit=success_days;at=None;terminal=False
        if a:
            if a['state']=='succeeded':terminal=True;at=stamp(a['finished_at'])
            elif a['state']=='failed' and any(x['job_id']==a['job_id'] and x['state']=='succeeded' and x['sequence']>a['sequence'] for x in attempts.values()):
                terminal=True;at=stamp(a['finished_at']);limit=failure_days
        elif row['id'] in accepted:
            terminal=True;at=stamp(accepted[row['id']]['accepted_at'])
        elif q.get('operation')=='create' and thread in sessions:
            terminal=True;at=stamp(sessions[thread].get('created_at'))
        if not terminal or at is None or not row['sent'] or not response or at>now-timedelta(days=limit):bad.add(thread)
        else:good[thread]=max(good.get(thread,at),at)
    return set(good)-bad,bad

def _small_item(item):
    if not isinstance(item,dict):return item
    if item.get('type')=='agentMessage':return item  # final answer and commentary evidence retained
    return {k:v for k,v in item.items() if k in {'id','type','status','phase','error'}}

def _transform(message,method=None):
    """Preserve exactly the fields consumed by WireIndex._ingest/_item."""
    value=json.loads(encode(message));reason=None
    if method in {'thread/resume','thread/read'} and isinstance(value.get('result'),dict):
        thread=value['result'].get('thread')
        if isinstance(thread,dict) and isinstance(thread.get('turns'),list) and thread['turns']:
            if method=='thread/resume':thread['turns']=[];reason='expired_repeated_resume_history'
            else:
                thread['turns']=[{**{k:v for k,v in t.items() if k in {'id','status'}},'items':[_small_item(i) for i in t.get('items',[])]} if isinstance(t,dict) else t for t in thread['turns']]
                reason='expired_read_tool_bodies'
    p=value.get('params')
    if isinstance(p,dict):
        name=value.get('method','')
        if name.lower().endswith('delta') and p.get('delta'):
            p['delta']='[expired]';reason='expired_stream_body'
        elif name=='item/completed' and isinstance(p.get('item'),dict) and p['item'].get('type')!='agentMessage':
            p['item']=_small_item(p['item']);reason='expired_tool_body'
        elif name=='turn/completed' and isinstance(p.get('turn'),dict):
            p['turn']['items']=[_small_item(i) for i in p['turn'].get('items',[])];reason='expired_terminal_tool_body'
    return value,reason

def _wire_changes(task,b,now,success_days,failure_days):
    p=task/'.mpres'/'codex-bridge.sqlite3'
    if not p.exists():return
    with closing(readonly_connection(p)) as c:
        allowed,protected=_eligible_threads(c,b,now,success_days,failure_days)
        rpc={}
        for row in c.execute('SELECT id,direction,payload FROM wire ORDER BY id'):
            raw=row['payload']
            try:m=json.loads(raw)
            except (ValueError,TypeError):continue
            if not isinstance(m,dict) or '_mpres_retention' in m:continue
            params=m.get('params') or {};method=None;thread=params.get('threadId') if isinstance(params,dict) else None
            if row['direction']=='out' and 'id' in m:
                rpc[encode(m['id'])]=(m.get('method'),thread);continue
            if row['direction']!='in':continue
            if 'id' in m and not m.get('method'):
                method,thread=rpc.get(encode(m['id']),(None,None))
                actual=(m.get('result') or {}).get('thread',{}) if isinstance(m.get('result'),dict) else {}
                if method in {'thread/resume','thread/read'} and actual.get('id')!=thread:continue
            if thread not in allowed:continue
            replacement,reason=_transform(m,method)
            if not reason:continue
            replacement['_mpres_retention']={'version':1,'sha256':digest(raw),'original_bytes':len(raw.encode()),'policy':reason,'expired_on':now.date().isoformat()}
            new=encode(replacement);saving=len(raw.encode())-len(new.encode())
            if saving<64:continue
            yield {'database':'codex-bridge.sqlite3','table':'wire','id':row['id'],'old_sha256':digest(raw),'new':new,'saved_payload_bytes':saving,'reason':reason}

def _check_changes(b):
    gates={g['id']:g for g in b['gate_runs']}
    for r in b['checks']:
        raw=r['detail_json']
        try:d=json.loads(raw);g=gates.get(d.get('gate_id'));full=json.loads(g['detail_json']) if g and g['detail_json'] else {}
        except (ValueError,TypeError):continue
        if 'storage_schema' in d or d.get('gate_id') is None:continue
        expected=full.get('checks',{}).get(r['name'])
        if expected is None or {k:v for k,v in d.items() if k!='gate_id'}!=expected:continue
        new=encode({'storage_schema':'gate-check-reference-v1','gate_id':d['gate_id'],'check_name':r['name']})
        saving=len(raw.encode())-len(new.encode())
        if saving>0:yield {'database':'task.sqlite3','table':'checks','id':r['id'],'old_sha256':digest(raw),'new':new,'saved_payload_bytes':saving,'reason':'exact_duplicate_gate_report'}

def _plan(task,success_days=7,failure_days=30,now=None):
    if any(type(x) is not int or x<0 or x>3650 for x in (success_days,failure_days)):raise MPresError('Retention days must be integers in 0..3650')
    now=now or datetime.now(timezone.utc)
    # A plan remains stable within one UTC calendar day. New database writes
    # alter the fingerprint, so an old dry-run can never authorize a wider set.
    day=now.astimezone(timezone.utc).replace(hour=0,minute=0,second=0,microsecond=0)
    b=_business(task);changes=list(_check_changes(b))+list(_wire_changes(task,b,day,success_days,failure_days))
    files={name:{'bytes':(task/'.mpres'/name).stat().st_size,'mtime_ns':(task/'.mpres'/name).stat().st_mtime_ns} for name in DATABASES if (task/'.mpres'/name).is_file()}
    summary={'version':1,'task':str(task.resolve()),'retention':{'success_days':success_days,'resolved_failure_days':failure_days,'cutoff_day_utc':day.date().isoformat()},'file_fingerprint':files,
        'rows':len(changes),'estimated_payload_bytes':sum(x['saved_payload_bytes'] for x in changes),
        'by_reason':{},'protected':['unresolved work','unaccepted requests','usage','requirements/authorizations','final responses','all artifact files','wire IDs/RPC/terminal evidence'],
        'database_bytes_reclaimed':None,'warning':'Payload reduction is not physical disk reclamation; compact separately. No archive is created by default.'}
    for x in changes:
        part=summary['by_reason'].setdefault(x['reason'],{'rows':0,'payload_bytes':0});part['rows']+=1;part['payload_bytes']+=x['saved_payload_bytes']
    try:_quiescent(b);summary['safe_to_apply']=True
    except MPresError as exc:summary['safe_to_apply']=False;summary['blocked_reason']=str(exc)
    summary['plan_id']=digest(encode({'summary':summary,'changes':[{k:v for k,v in x.items() if k!='new'} for x in changes]}))
    return summary,changes,b

def plan(task,**kwargs):return _plan(task,**kwargs)[0]

def apply(task,plan_id,*,by,success_days=7,failure_days=30,backup_dir=None):
    if not isinstance(by,str) or not by.strip():raise MPresError('Explicit cleanup actor is required')
    # Schema migration is an explicit prerequisite; it changes the dry-run hash.
    with closing(readonly_connection(task/'.mpres'/'task.sqlite3')) as c:
        if c.execute('PRAGMA user_version').fetchone()[0]!=Store.SCHEMA_VERSION:raise MPresError('Run storage migrate, then make a new dry-run plan')
    with Lease(task,exclusive=True):
        summary,changes,b=_plan(task,success_days,failure_days)
        if summary['plan_id']!=plan_id:raise MPresError('Cleanup plan changed; review a new dry run')
        _quiescent(b)
        if backup_dir:
            backup_dir=Path(backup_dir)
            if backup_dir.exists():raise MPresError('Backup directory must be new; caller controls its bounded retention')
            backup_dir.mkdir(parents=True)
            for name in DATABASES:
                p=task/'.mpres'/name
                if p.is_file():
                    with closing(readonly_connection(p)) as src,closing(sqlite3.connect(backup_dir/name)) as dst:src.backup(dst)
        run_id='clean-'+uuid.uuid4().hex;started=utc_now();done=[]
        # One database transaction at a time. A later database failure cannot
        # pretend to roll back an earlier commit; return/audit partial state.
        try:
            for name in ('codex-bridge.sqlite3','task.sqlite3'):
                selected=[x for x in changes if x['database']==name]
                if not selected:continue
                with closing(sqlite3.connect(task/'.mpres'/name,timeout=1,isolation_level=None)) as c:
                    c.execute('BEGIN EXCLUSIVE')
                    try:
                        for x in selected:
                            column='payload' if x['table']=='wire' else 'detail_json'
                            old=c.execute(f'SELECT {column} FROM {x["table"]} WHERE id=?',(x['id'],)).fetchone()
                            if not old or digest(old[0])!=x['old_sha256']:raise MPresError('Cleanup source changed during apply')
                            c.execute(f'UPDATE {x["table"]} SET {column}=? WHERE id=?',(x['new'],x['id']))
                        c.commit();done.append(name)
                    except Exception:c.rollback();raise
            result={**summary,'run_id':run_id,'state':'completed','committed_databases':done,'backup_directory':str(backup_dir) if backup_dir else None,'model_calls':0}
        except Exception as exc:
            result={**summary,'run_id':run_id,'state':'partial' if done else 'failed','committed_databases':done,'error':str(exc)}
            _audit(task,run_id,'prune',by,started,result)
            raise MPresError('Cleanup '+result['state']+': '+str(exc)) from exc
        _audit(task,run_id,'prune',by,started,result)
        return result

def _audit(task,rid,op,by,started,result):
    with closing(sqlite3.connect(task/'.mpres'/'task.sqlite3')) as c:
        c.execute('INSERT INTO maintenance_runs VALUES(?,?,?,?,?,?,?,?)',(rid,op,by,started,utc_now(),result['state'],result.get('plan_id'),encode(result)))
        c.commit()

def compact(task,*,by):
    if not by or not by.strip():raise MPresError('Explicit maintenance actor required')
    with Lease(task,exclusive=True):
        _quiescent(_business(task));before=inspect(task);done=[]
        for name in DATABASES:
            p=task/'.mpres'/name
            if not p.is_file():continue
            if shutil.disk_usage(p.parent).free<2*p.stat().st_size:raise MPresError('Insufficient free disk for safe VACUUM; completed: '+', '.join(done))
            with closing(sqlite3.connect(p,timeout=1,isolation_level=None)) as c:
                c.execute('PRAGMA locking_mode=EXCLUSIVE')
                if c.execute('PRAGMA quick_check').fetchone()[0]!='ok':raise MPresError('Database integrity check failed: '+name)
                checkpoint=c.execute('PRAGMA wal_checkpoint(TRUNCATE)').fetchone()
                if checkpoint and checkpoint[0]:raise MPresError('Active WAL readers/writers; stop and retry')
                c.execute('VACUUM')
                if c.execute('PRAGMA quick_check').fetchone()[0]!='ok':raise MPresError('Post-compaction integrity check failed: '+name)
                done.append(name)
        after=inspect(task)
        result={'version':1,'state':'completed','databases':done,'before_bytes':before['database_bytes'],'after_bytes':after['database_bytes'],'reclaimed_database_bytes':before['database_bytes']-after['database_bytes'],'model_calls':0,'archives_created':0}
        _audit(task,'compact-'+uuid.uuid4().hex,'compact',by,utc_now(),result)
        return result

def retention_policy(path: Path | None = None):
    value={'version':1,'success_days':7,'resolved_failure_days':30}
    if path:
        if path.is_symlink() or not path.is_file() or path.stat().st_size>32768:raise MPresError('Unsafe or oversized retention policy')
        value=json.loads(path.read_text(encoding='utf-8'))
    from jsonschema import Draft202012Validator
    schema=json.loads(Path(__file__).with_name('schemas').joinpath('retention-policy.json').read_text())
    errors=list(Draft202012Validator(schema).iter_errors(value))
    if errors:raise MPresError('Invalid retention policy: '+errors[0].message)
    return value
