"""Current-release-centred collection of managed files and settled logs.

Not an mtime-based recursive delete. A reviewed plan pins the current sources,
known managed paths and database identity. Renames are journalled before any
removal; recovery resumes the same finite plan. Canonical usage/configuration,
authorizations and unfinished work are never garbage. No permanent full backup
is manufactured. The current release stays protected until its successor exists.
"""
from __future__ import annotations
import hashlib
import json
import os
import shutil
import sqlite3
import uuid
from contextlib import closing
from pathlib import Path
from mpres.util import MPresError,utc_now
from .files import inside,remove_tree
from .maintenance_lock import Lease,readonly_connection
from .store import Store,encode,event
from .compatibility import current_state
from . import storage

VERSION=1


def _hash(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda:f.read(1024*1024),b''):h.update(chunk)
    return h.hexdigest()


def tree(task,relative):
    root=inside(task,relative)
    if not root.exists():return None
    items=[root] if root.is_file() else sorted(root.rglob('*'))
    rows=[]
    for p in items:
        inside(task,p.relative_to(task).as_posix())
        if p.is_dir():continue
        if not p.is_file():raise MPresError('Only regular managed files may be collected: '+str(p))
        rows.append({'path':'.' if p==root else p.relative_to(root).as_posix(), 'bytes':p.stat().st_size,'sha256':_hash(p)})
    return {'path':relative,'bytes':sum(r['bytes'] for r in rows),'files':len(rows),
        'sha256':hashlib.sha256(encode(rows).encode()).hexdigest(),'file_entries':rows}


def _brief(value):return {k:v for k,v in value.items() if k!='file_entries'}


def directory_usage(task):
    total=count=0;groups={}
    for p in task.rglob('*'):
        # Never follow symlinks, including links into this task.
        if p.is_symlink():continue
        if not p.is_file():continue
        rel=p.relative_to(task);parts=rel.parts
        key='/'.join(parts[:2]) if parts[0]=='.mpres' else parts[0]
        n=p.stat().st_size;total+=n;count+=1
        g=groups.setdefault(key,{'bytes':0,'files':0});g['bytes']+=n;g['files']+=1
    return {'bytes':total,'files':count,'by_directory':dict(sorted(groups.items(),key=lambda x:-x[1]['bytes'])),
        'includes_backups_and_staging':True}


def _rows(c,table):return [dict(r) for r in c.execute('SELECT * FROM '+table)]


def facts(task):
    with closing(readonly_connection(task/'.mpres/task.sqlite3')) as c:
        if c.execute('PRAGMA user_version').fetchone()[0]!=Store.SCHEMA_VERSION:
            raise MPresError('Open/migrate the task, then make a new checkpoint plan')
        result={t:_rows(c,t) for t in ('attempts','jobs','host_requests','sessions','gate_runs','checks','usage','artifacts','pool_slots','decks','releases','release_versions','repair_cases','repair_targets')}
        result['parents']=[r[0] for r in c.execute('SELECT DISTINCT parent FROM delivery_parts WHERE presentation<>parent')]
        result['retired']={json.loads(r[0])['attempt_id'] for r in c.execute("SELECT detail_json FROM events WHERE kind='attempt.out_of_scope_retired'")}
        result['pending']=[dict(r) for r in c.execute("SELECT id,state FROM current_checkpoints WHERE state<>'completed'")]
    return result


def _settled(task,b):
    """True only with positive business/terminal evidence, not legacy accepted=0."""
    attempts={r['id']:r for r in b['attempts']};accepted={r['request_id'] for r in b['host_requests'] if r['state']=='accepted'}
    sessions={r['id'] for r in b['sessions']};bad=[];bridge=task/'.mpres/codex-bridge.sqlite3'
    if not bridge.is_file():return {'available':False,'ready':True,'unresolved_requests':[]}
    with closing(readonly_connection(bridge)) as c:
        for row in c.execute('SELECT id,request,response,sent FROM requests'):
            q=json.loads(row['request']);v=json.loads(row['response']) if row['response'] else {}
            a=attempts.get(q.get('attempt_id'));thread=q.get('session_id') or v.get('handle')
            terminal=row['id'] in accepted
            if a:
                terminal=terminal or a['state']=='succeeded' or a['id'] in b['retired'] or (
                    a['state']=='failed' and any(x['job_id']==a['job_id'] and x['state']=='succeeded' and x['sequence']>a['sequence'] for x in attempts.values()))
            terminal=terminal or (q.get('operation')=='create' and thread in sessions)
            if not terminal or not row['sent'] or not v:bad.append(row['id'])
    return {'available':True,'ready':not bad,'unresolved_requests':bad}


def _blocked(b):
    errors=[]
    try:storage._quiescent(b)
    except MPresError as e:errors.append(str(e))
    if any(r['state'] not in {'completed','cancelled'} for r in b['repair_cases']):
        errors.append('A repair case is still open; preserve its baseline and work until it closes')
    if any(d['phase'] not in {'units','delivered'} for d in b['decks']):
        errors.append('A deck is not at a delivery boundary')
    return errors


def _db_identity(task):
    return {p.name:{'bytes':p.stat().st_size,'mtime_ns':p.stat().st_mtime_ns}
        for name in storage.DATABASES for p in [task/'.mpres'/name] if p.is_file()}


def _valid_old_delivery(task,pid,artifact,b):
    """Protect edited/unmanaged old public files rather than deleting user work."""
    source=inside(task,artifact['path']);target=inside(task,'deliverables/'+pid)
    if not target.exists():return True
    expected={}
    if source.is_dir():
        for p in source.rglob('*'):
            if p.is_file():
                rel=p.relative_to(source).as_posix();expected[pid+'.md' if rel=='presentation.md' else rel]=p
    release=next((r for r in b['releases'] if r['presentation']==pid),None)
    if release:
        gate=next((g for g in b['gate_runs'] if g['id']==release['gate_id']),{})
        if gate.get('pdf_path'):expected[pid+'.pdf']=inside(task,gate['pdf_path'])
        detail=json.loads(gate.get('detail_json') or '{}');warning=detail.get('warning_report') or {}
        for name,key in [('WARNINGS.md','markdown_path'),('WARNINGS.json','json_path')]:
            if warning.get(key):expected[name]=inside(task,warning[key])
    for p in target.rglob('*'):
        inside(task,p.relative_to(task).as_posix())
        if p.is_dir():continue
        rel=p.relative_to(target).as_posix();q=expected.get(rel)
        if q is None or not q.is_file() or _hash(p)!=_hash(q):return False
    return True


def _plan(task,*,allow_missing_pdf=False):
    task=task.resolve();b=facts(task);state=current_state(task);blocked=_blocked(b)
    if b['pending']:blocked.append('An interrupted checkpoint must be resumed before starting another')
    current=state['current_releases'];leaf={r['presentation'] for r in current}
    if not current:blocked.append('No current committed leaf releases; nothing may replace the baseline')
    if state['warnings'] and not allow_missing_pdf:blocked.append('Current PDF missing; restore/rerender it first (archive validation requires explicit --allow-missing-pdf)')
    archived=leaf|set(b['parents']);ids={r['artifact_id'] for r in current}
    current_gates={r['gate_id'] for r in b['releases'] if r['presentation'] in leaf}
    assets={r['id']:r for r in b['artifacts']};preserve=[];candidates=[];protected=[]
    def protect(relative,kind):
        value=tree(task,relative)
        if value:preserve.append({**_brief(value),'kind':kind})
    def offer(relative,kind):
        value=tree(task,relative)
        if value:candidates.append({**value,'kind':kind})
    # Current canonical source and associated checked/rendered PDF/report remain
    # protected even when a newer candidate is being prepared elsewhere.
    for r in current:
        protect(r['source_directory'],'current_source')
        protect(r['pdf'],'current_pdf')
        protect('deliverables/'+r['presentation'],'current_delivery')
        gate=next(g for g in b['gate_runs'] if g['id'] in current_gates and g['artifact_id']==r['artifact_id'])
        protect('.mpres/gates/'+gate['id'],'current_gate')
        if gate['state']!='passed':blocked.append('Current release lacks a passed gate: '+r['presentation'])
        if not allow_missing_pdf:
            checked=inside(task,gate['pdf_path']) if gate.get('pdf_path') else None
            pdf=inside(task,r['pdf'])
            if checked is None or not checked.is_file() or not pdf.is_file() or _hash(checked)!=_hash(pdf):
                blocked.append('Current canonical/checked PDF pair missing or changed: '+r['presentation'])
        # An existing current public Markdown must be the same source. Extra
        # public files are preserved, never silently treated as authoritative.
        public=inside(task,f"deliverables/{r['presentation']}/{r['presentation']}.md")
        if public.is_file() and _hash(public)!=r['markdown_sha256']:
            blocked.append('Public current Markdown differs from canonical release: '+r['presentation'])
    for a in b['artifacts']:
        if a['presentation'] in archived and a['id'] not in ids:offer(a['path'],'obsolete_artifact')
    jobs={r['id']:r for r in b['jobs']}
    for a in b['attempts']:
        if a['state'] in {'succeeded','failed'} and jobs[a['job_id']]['presentation'] in archived:
            offer('.mpres/work/'+a['id'],'closed_work')
    for g in b['gate_runs']:
        if g['id'] not in current_gates and g['state']!='running' and assets.get(g['artifact_id'],{}).get('presentation') in archived:
            offer('.mpres/gates/'+g['id'],'obsolete_gate')
    live_pdfs={r['pdf'] for r in current}
    for r in b['release_versions']:
        if r['presentation'] in archived and r['pdf_path'] not in live_pdfs:
            rel=r['pdf_path']
            if rel.startswith('.mpres/releases/'):
                offer(str(Path(rel).parent).replace('\\','/'),'obsolete_release')
    for pid in b['parents']:
        r=next((r for r in b['releases'] if r['presentation']==pid),None)
        if r and _valid_old_delivery(task,pid,assets[r['artifact_id']],b):offer('deliverables/'+pid,'superseded_parent_delivery')
        elif inside(task,'deliverables/'+pid).exists():protected.append({'path':'deliverables/'+pid,'reason':'modified/unverifiable public files'})
    backups=inside(task,'.mpres/maintenance-backups')
    if backups.is_dir():
        for folder in sorted(backups.iterdir()):
            if folder.is_symlink():raise MPresError('Symlink in managed backup area')
            if folder.is_dir() and {p.name for p in folder.iterdir()} <= set(storage.DATABASES):offer(folder.relative_to(task).as_posix(),'obsolete_maintenance_backup')
            else:protected.append({'path':folder.relative_to(task).as_posix(),'reason':'unrecognized backup content'})
    # Keep source documents and resource-cache objects: cache is shared with
    # not-yet-produced decks. Closed per-attempt textbook copies are collected.
    unique={r['path']:r for r in candidates};candidates=[]
    for path,r in sorted(unique.items()):
        if any(path==p['path'] or path.startswith(p['path']+'/') or p['path'].startswith(path+'/') for p in preserve):
            protected.append({'path':path,'reason':'current release dependency'});continue
        if not any(path.startswith(x['path']+'/') for x in candidates):candidates.append(r)
    wire=_settled(task,b)
    if not wire['ready']:blocked.append('Unsettled provider requests require reconciliation, not age-based deletion')
    base={'version':VERSION,'task':str(task),'allow_missing_pdf':allow_missing_pdf,
        'safe_to_apply':not blocked,'blocked_reasons':blocked,'current_releases':current,
        'preserve':preserve,'candidates':candidates,'protected_exceptions':protected,
        'managed_file_bytes_to_remove':sum(r['bytes'] for r in candidates),'wire':wire,
        'database_identity':_db_identity(task),'directory_usage':directory_usage(task),
        'usage_sha256':hashlib.sha256(encode(sorted(b['usage'],key=lambda r:(r['attempt_id'],r['call_id']))).encode()).hexdigest(),
        'archives_created':0,'semantic_revalidation':False,'model_calls':0}
    base['plan_id']=hashlib.sha256(encode(base).encode()).hexdigest()
    return base,b


def plan(task,*,allow_missing_pdf=False):return _plan(task,allow_missing_pdf=allow_missing_pdf)[0]


def _raw(task):
    c=sqlite3.connect(task/'.mpres/task.sqlite3',isolation_level=None,timeout=1);c.row_factory=sqlite3.Row;c.execute('PRAGMA foreign_keys=ON');return c


def _verify_preserved(task,p):
    for old in p['preserve']:
        actual=tree(task,old['path'])
        if not actual or any(actual[k]!=old[k] for k in ('sha256','bytes','files')):
            raise MPresError('Protected current release changed; stop checkpoint recovery: '+old['path'])


def _prune_business(task,p,checkpoint_id):
    """Keep IDs, metrics and summaries; remove duplicate obsolete prose reports."""
    from .wire_checkpoint import compact_envelope
    keep={r['artifact_id'] for r in p['current_releases']}
    obsolete={r['path'] for r in p['candidates'] if r['kind']=='obsolete_artifact'}
    with closing(_raw(task)) as c:
        c.execute('BEGIN IMMEDIATE')
        try:
            oldids={r[0] for r in c.execute('SELECT id,path FROM artifacts') if r[1] in obsolete}
            for table in ('gate_runs','checks'):
                for r in c.execute('SELECT id,artifact_id,detail_json FROM '+table).fetchall():
                    if r['artifact_id'] not in oldids or not r['detail_json']:continue
                    d=json.loads(r['detail_json'])
                    if d.get('storage_schema')=='current-checkpoint-reference-v1':continue
                    brief={'storage_schema':'current-checkpoint-reference-v1','checkpoint_id':checkpoint_id,
                        'sha256':hashlib.sha256(r['detail_json'].encode()).hexdigest(),
                        **{k:v for k,v in d.items() if k in {'success','seconds','gate_id','level','source_policy_version','inspection_version'}}}
                    c.execute('UPDATE '+table+' SET detail_json=? WHERE id=?',(encode(brief),r['id']))
            # All provider records were checked settled before collection. Their
            # individual acceptance facts remain in host_requests and events.
            for r in c.execute("SELECT request_id,request_json FROM host_requests WHERE state='accepted'").fetchall():
                c.execute('UPDATE host_requests SET request_json=? WHERE request_id=?',(compact_envelope(r['request_json'],checkpoint_id),r['request_id']))
                for v in c.execute('SELECT rowid,response_json FROM host_responses WHERE request_id=?',(r['request_id'],)).fetchall():
                    c.execute('UPDATE host_responses SET response_json=? WHERE rowid=?',(compact_envelope(v['response_json'],checkpoint_id,response=True),v['rowid']))
            c.commit()
        except Exception:c.rollback();raise


def _compact(task):
    # The exclusive maintenance lease is already held; do not recursively acquire.
    done=[]
    for name in storage.DATABASES:
        path=inside(task,'.mpres/'+name)
        if not path.is_file():continue
        if shutil.disk_usage(path.parent).free<2*path.stat().st_size:raise MPresError('Insufficient temporary disk for VACUUM: '+name)
        with closing(sqlite3.connect(path,timeout=1,isolation_level=None)) as c:
            if c.execute('PRAGMA quick_check').fetchone()[0]!='ok':raise MPresError('Database integrity failed: '+name)
            row=c.execute('PRAGMA wal_checkpoint(TRUNCATE)').fetchone()
            if row and row[0]:raise MPresError('WAL is busy: '+name)
            c.execute('VACUUM')
            if c.execute('PRAGMA quick_check').fetchone()[0]!='ok':raise MPresError('Post-VACUUM integrity failed: '+name)
        done.append(name)
    return done


def _resume_locked(task,rid,by,*,fault=None):
    with closing(_raw(task)) as c:
        row=c.execute('SELECT * FROM current_checkpoints WHERE id=?',(rid,)).fetchone()
        if not row:raise MPresError('Unknown checkpoint')
        if row['state']=='completed':return json.loads(row['result_json'])
        p=json.loads(row['plan_json']);state=row['state']
    _verify_preserved(task,p)
    b=facts(task)
    if _blocked(b) or not _settled(task,b)['ready']:raise MPresError('New/unsettled work blocks checkpoint recovery')
    stage=inside(task,'.mpres/checkpoint-staging/'+rid);stage.mkdir(parents=True,exist_ok=True)
    if state=='preparing':
        for i,item in enumerate(p['candidates']):
            src=inside(task,item['path']);dst=inside(stage,str(i))
            if dst.exists():
                if src.exists():raise MPresError('Both original and staged item exist; preserve both and investigate')
                actual=tree(task,dst.relative_to(task).as_posix())
            else:
                actual=tree(task,item['path'])
                if actual and actual['sha256']==item['sha256']:
                    os.replace(src,dst)
            if actual is None or actual['sha256']!=item['sha256']:raise MPresError('Managed item changed during checkpoint: '+item['path'])
            if fault:fault('after_rename',i)
        _verify_preserved(task,p)
        with closing(_raw(task)) as c:
            c.execute('BEGIN IMMEDIATE')
            for item in p['candidates']:
                c.execute('INSERT OR REPLACE INTO retention_tombstones VALUES(?,?,?,?,?,?)',
                    (item['path'],item['kind'],item['sha256'],item['bytes'],rid,utc_now()))
            c.execute("UPDATE current_checkpoints SET state='files_committed' WHERE id=?",(rid,));c.commit()
        state='files_committed'
    if fault:fault('after_files_committed',None)
    # Once tombstones commit, stage is garbage. Deleting it BEFORE VACUUM bounds
    # peak disk and frees room formerly occupied by maintenance backups.
    # Recovery may see a partially purged stage. Missing planned files are fine;
    # extra/modified files are not silently deleted. Symlinks are always refused.
    expected={str(i):r for i,r in enumerate(p['candidates'])}
    for entry in stage.iterdir():
        if entry.name not in expected:raise MPresError('Unmanaged file in checkpoint staging; preserve it before recovery')
        row=expected[entry.name];known={f['path']:f for f in row.get('file_entries',[])}
        values=[entry] if entry.is_file() else list(entry.rglob('*'))
        for f in values:
            inside(task,f.relative_to(task).as_posix())
            if f.is_dir():continue
            rel='.' if f==entry else f.relative_to(entry).as_posix()
            if rel not in known or _hash(f)!=known[rel]['sha256']:
                raise MPresError('Modified/unmanaged staged file; preserve it before recovery: '+str(f))
    import stat
    for folder in [stage,*[d for d in stage.rglob('*') if d.is_dir()]]:
        folder.chmod(folder.stat().st_mode | stat.S_IWUSR | stat.S_IXUSR)
    def readonly_retry(fn,path,exc):
        target=Path(path);target.chmod(target.stat().st_mode | stat.S_IWUSR);fn(path)
    shutil.rmtree(stage,onerror=readonly_retry)
    wire_result={}
    if p['wire']['available']:
        from .wire_checkpoint import prune
        wire_result=prune(task/'.mpres/codex-bridge.sqlite3',rid)
    _prune_business(task,p,rid)
    if fault:fault('after_logs_committed',None)
    _verify_preserved(task,p)
    with closing(readonly_connection(task/'.mpres/task.sqlite3')) as c:
        current_usage=sorted(_rows(c,'usage'),key=lambda r:(r['attempt_id'],r['call_id']))
    if hashlib.sha256(encode(current_usage).encode()).hexdigest()!=p['usage_sha256']:
        raise MPresError('Usage ledger changed; preserve checkpoint and investigate')
    compacted=_compact(task)
    # Rebuild the expendable sidecar from the seed with no nested shared lease.
    if p['wire']['available']:
        from .codex_index import _SCHEMA
        from .wire_checkpoint import read_seed,restore
        journal=task/'.mpres/codex-bridge.sqlite3';index=task/'.mpres/codex-index.sqlite3'
        with closing(readonly_connection(journal)) as src,closing(sqlite3.connect(index)) as dst:
            seed=read_seed(src);dst.executescript(_SCHEMA);restore(dst,seed)
            st=journal.stat();dst.execute('DELETE FROM source');dst.execute('INSERT INTO source VALUES(1,?,?,?,?)',(str(journal),st.st_dev,st.st_ino,seed['highwater']));dst.commit()
    result={'version':VERSION,'id':rid,'state':'completed','actor':by,'before_directory_bytes':p['directory_usage']['bytes'],
        'removed_managed_file_bytes':p['managed_file_bytes_to_remove'],'removed_managed_paths':len(p['candidates']),
        'compacted_databases':compacted,'wire':wire_result,'usage_unchanged':True,'current_sources_unchanged':True,
        'allow_missing_pdf':p['allow_missing_pdf'],'delivery_ready_claimed':False,'current_pdf_pair_verified':not p['allow_missing_pdf'],
        'archives_created':0,'model_calls':0,'current_presentations':[r['presentation'] for r in p['current_releases']]}
    with closing(_raw(task)) as c:
        c.execute('BEGIN IMMEDIATE')
        # Keep a small checkpoint summary, not the old directory contents or an
        # indefinitely growing copied manifest per revision.
        summary={k:v for k,v in p.items() if k not in {'candidates','preserve','database_identity','directory_usage'}}
        c.execute("UPDATE current_checkpoints SET state='completed',finished_at=?,plan_json=?,result_json=? WHERE id=?",(utc_now(),encode(summary),encode(result),rid))
        event(c,'storage.current_checkpoint_completed',{'id':rid,'current_presentations':result['current_presentations'],'sources':[{'artifact_id':r['artifact_id'],'sha256':r['markdown_sha256']} for r in p['current_releases']]});c.commit()
    result['after_directory_bytes']=directory_usage(task)['bytes']
    result['net_reclaimed_bytes']=result['before_directory_bytes']-result['after_directory_bytes']
    with closing(_raw(task)) as c:c.execute('UPDATE current_checkpoints SET result_json=? WHERE id=?',(encode(result),rid))
    return result


def apply(task,plan_id,*,by,allow_missing_pdf=False,fault=None):
    if not isinstance(by,str) or not by.strip():raise MPresError('Explicit checkpoint actor required')
    with Lease(task,exclusive=True):
        p,b=_plan(task,allow_missing_pdf=allow_missing_pdf)
        if p['plan_id']!=plan_id:raise MPresError('Checkpoint plan changed; review a new dry run')
        if not p['safe_to_apply']:raise MPresError('; '.join(p['blocked_reasons']))
        rid='checkpoint-'+uuid.uuid4().hex
        with closing(_raw(task)) as c:
            c.execute('INSERT INTO current_checkpoints VALUES(?,?,?,?,?,?,?)',(rid,'preparing',utc_now(),None,by,encode(p),None))
        return _resume_locked(task,rid,by,fault=fault)


def resume(task,rid,*,by,fault=None):
    if not by or not by.strip():raise MPresError('Explicit recovery actor required')
    with Lease(task,exclusive=True):return _resume_locked(task,rid,by,fault=fault)


def status(task):
    with closing(readonly_connection(task/'.mpres/task.sqlite3')) as c:
        return {'version':VERSION,'checkpoints':[{'id':r['id'],'state':r['state'],'created_at':r['created_at'],'finished_at':r['finished_at'],'result':json.loads(r['result_json']) if r['result_json'] else None} for r in c.execute('SELECT * FROM current_checkpoints ORDER BY created_at')],
            'policy':dict(c.execute('SELECT * FROM current_retention_policy').fetchone() or {}),'read_only':True}


def policy(task,enabled,*,by):
    if type(enabled) is not bool or not by or not by.strip():raise MPresError('Explicit retention policy and actor required')
    with Store(task).transaction() as c:
        c.execute('INSERT OR REPLACE INTO current_retention_policy VALUES(1,?,?,?,1)',(int(enabled),by,utc_now()))
        event(c,'storage.current_policy_confirmed',{'enabled':enabled,'actor':by,'mode':'current-only' if enabled else 'manual-only'})
    return {'version':VERSION,'enabled':enabled,'mode':'current-only' if enabled else 'manual-only','automatic_safe_boundary':enabled,
        'deleted_now':False,'model_calls':0}


def maybe_run(task):
    """Once per committed baseline, only after adapter close / on a safe open."""
    with closing(readonly_connection(task/'.mpres/task.sqlite3')) as c:
        policy_row=c.execute('SELECT enabled FROM current_retention_policy').fetchone()
        if not policy_row or not policy_row[0]:return {'state':'manual_only'}
        if c.execute("SELECT 1 FROM current_checkpoints WHERE state<>'completed'").fetchone():return {'state':'recovery_required'}
        if c.execute('SELECT status FROM task').fetchone()[0] not in {'paused','completed'}:return {'state':'deferred','reason':'production not paused'}
        previous=c.execute("SELECT plan_json FROM current_checkpoints WHERE state='completed' ORDER BY created_at DESC LIMIT 1").fetchone()
        current=current_state(task,c)['current_releases']
        if previous and [r['artifact_id'] for r in json.loads(previous[0])['current_releases']]==[r['artifact_id'] for r in current]:return {'state':'current_baseline_already_collected'}
    try:
        p=plan(task)
        if not p['safe_to_apply']:return {'state':'deferred','reasons':p['blocked_reasons']}
        return apply(task,p['plan_id'],by='program:confirmed-current-retention')
    except (MPresError,OSError) as exc:return {'state':'deferred','reason':str(exc)}
