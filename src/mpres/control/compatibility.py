"""Open existing compact tasks without re-initialization or semantic rewriting.

Schema migrations are serialized by Store. This application-level projection is
idempotent and deliberately leaves configurations, authorizations, pending
requests and historical review claims untouched. A projection is not approval.
"""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path
from contextlib import closing

from mpres import __version__
from mpres.util import MPresError
from .files import inside
from .store import Store, encode, event


def current_state(task: Path, conn=None) -> dict:
    """Read only. Select leaf releases relationally, never by filename or mtime."""
    if conn is None:
        with closing(Store(task).readonly()) as c:
            return current_state(task,c)
    tables={r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if 'delivery_parts' not in tables:
        raise MPresError('Open this older task to migrate its schema before reading current state')
    rows=conn.execute("""SELECT r.*,a.path,a.entrypoint,d.phase FROM releases r
        JOIN artifacts a ON a.id=r.artifact_id JOIN decks d ON d.presentation=r.presentation
        WHERE r.state='committed' AND NOT EXISTS
        (SELECT 1 FROM delivery_parts p WHERE p.parent=r.presentation AND p.presentation<>p.parent)
        ORDER BY COALESCE((SELECT pd.ordinal FROM delivery_parts dp JOIN decks pd ON pd.presentation=dp.parent WHERE dp.presentation=d.presentation LIMIT 1), d.ordinal), d.ordinal""").fetchall()
    from .planning import superseded
    expected={r[0] for r in conn.execute("SELECT presentation FROM releases WHERE state='committed'") if not superseded(conn,r[0])}
    if {r['presentation'] for r in rows}!=expected:
        raise MPresError('Committed release has a missing artifact/deck reference; restore it before continuing')
    releases=[]
    for row in rows:
        row=dict(row);source=inside(task,row['path'])
        md=inside(source,row['entrypoint'] or 'presentation.md')
        if not md.is_file():
            raise MPresError(f"Current source missing for {row['presentation']}; recover it, never restart old unit jobs")
        pdf=inside(task,row['pdf_path'])
        rv=conn.execute("SELECT revision FROM release_versions WHERE presentation=? AND artifact_id=? AND state='committed' ORDER BY revision DESC LIMIT 1",(row['presentation'],row['artifact_id'])).fetchone()
        releases.append({'presentation':row['presentation'],'artifact_id':row['artifact_id'],
            'source_directory':row['path'],'markdown':md.relative_to(task).as_posix(),
            'markdown_sha256':hashlib.sha256(md.read_bytes()).hexdigest(),
            'pdf':row['pdf_path'],'pdf_present':pdf.is_file(),
            'revision':rv[0] if rv else None,'phase':row['phase']})
    parents=[r[0] for r in conn.execute('SELECT DISTINCT parent FROM delivery_parts WHERE presentation<>parent ORDER BY parent')]
    task_row=conn.execute('SELECT status,config_id FROM task').fetchone()
    pending=[dict(r) for r in conn.execute("SELECT id,job_id,state FROM attempts WHERE state IN ('reserved','running','uncertain') ORDER BY started_at")]
    return {'version':1,'schema_version':conn.execute('PRAGMA user_version').fetchone()[0],
        'task_status':task_row['status'],'config_id':task_row['config_id'],
        'current_releases':releases,'superseded_parents':parents,'pending_attempts':pending,
        'semantic_revalidation':'not_performed','provider_calls':0,
        'warnings':[{'presentation':r['presentation'],'code':'current_pdf_missing',
            'action':'Regenerate the same current source with the native gate when needed; never invent a release receipt.'}
            for r in releases if not r['pdf_present']]}


def _write_if_changed(path: Path, value: dict) -> None:
    data=(encode(value)+'\n').encode()
    if path.is_file() and path.read_bytes()==data:return
    if path.is_symlink():raise MPresError('Unsafe current-state projection')
    fd,name=tempfile.mkstemp(prefix='.current-',dir=path.parent)
    try:
        with os.fdopen(fd,'wb') as f:f.write(data);f.flush();os.fsync(f.fileno())
        os.replace(name,path)
    finally:
        if os.path.exists(name):os.unlink(name)


def open_task(task: Path, *, actor: str = 'program:task-open') -> dict:
    """Migrate if necessary, then atomically record/provide the live baseline.

    The projection can be rebuilt after a crash. No permanent DB backup is
    manufactured for metadata-only transactional migrations. Files never become
    semantic approval and the original TASK is not silently overwritten.
    """
    task=task.resolve();store=Store(task)
    if not store.path.is_file():raise MPresError('No existing compact task; open never initializes a new task')
    store.migration_actor=actor
    with store.transaction() as conn:
        pending=conn.execute("SELECT id FROM current_checkpoints WHERE state<>'completed'").fetchone()
        if pending:raise MPresError('Checkpoint recovery required before production: storage checkpoint '+task.name+' --resume '+pending[0]+' --by main')
        state=current_state(task,conn)
        identity=hashlib.sha256(encode(state).encode()).hexdigest()
        old=conn.execute("SELECT detail_json FROM events WHERE kind='task.compatibility_opened' ORDER BY id DESC LIMIT 1").fetchone()
        previous=json.loads(old[0]) if old else {}
        changed=(previous.get('program_version'),previous.get('state_sha256'))!=(__version__,identity)
        if changed:
            event(conn,'task.compatibility_opened',{'program_version':__version__,'state_sha256':identity,
                'actor':actor,'schema_version':state['schema_version'],
                'current_presentations':[r['presentation'] for r in state['current_releases']],
                'semantic_revalidation':False,'authorization_changed':False})
        _write_if_changed(task/'.mpres'/'current-state.json',state)
    from .checkpoints import maybe_run
    maintenance=maybe_run(task)
    return {**state,'automatic_maintenance':maintenance,'program_version':__version__,'compatibility_changed':changed,
            'source_edited':False,'runtime_changed':False}
