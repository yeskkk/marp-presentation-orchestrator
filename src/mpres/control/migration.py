from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from mpres.runtime_profile import normalize_runtime_profile
from mpres.util import MPresError, read_yaml, safe_id, utc_now, write_yaml_atomic
from .files import inside, remove_tree, snapshot
from .service import Service
from .store import encode, event


def legacy_state(task: Path) -> tuple[dict,str]:
    database = task/'state'/'mutable-state.sqlite3'
    if database.is_file():
        connection = sqlite3.connect(database.resolve().as_uri()+'?mode=ro',uri=True)
        try:
            row = connection.execute("SELECT payload_json FROM mutable_documents WHERE document_id='task-state'").fetchone()
            if row:
                return json.loads(row[0]), 'sqlite-read-only'
        finally:
            connection.close()
    source = task/'state'/'task.json'
    if not source.is_file():
        raise MPresError('No legacy canonical state/projection was found')
    return json.loads(source.read_text(encoding='utf-8')), 'json-projection-unverified'


def import_legacy(root: Path, old: Path, new_slug: str) -> dict:
    """Read-only import into a NEW task. No old statuses/sessions become approvals.

    The original TASK and plan are evidence. Missing semantic briefs remain empty
    so confirmation fails until a planner/user explicitly supplies them.
    """
    old = old.resolve()
    state, provenance = legacy_state(old)
    service = Service.create(root,new_slug,str(state.get('title') or new_slug))
    try:
        settings = read_yaml(service.task/'task.yaml')
        decks = []
        copied = []
        if (old/'TASK.md').is_file():
            target = service.task/'sources'/'legacy-task.md'
            target.write_bytes((old/'TASK.md').read_bytes())
        for deck in state.get('presentations',[]):
            safe_id(deck['id'])
            units = []
            for unit in deck.get('content_units',[]):
                safe_id(unit['id'])
                units.append({'id':unit['id'],'title':unit['title'],'brief':'','sources':['sources/legacy-task.md'] if (service.task/'sources'/'legacy-task.md').exists() else []})
                source = inside(old,f"workers/lesson-authors/{deck['id']}/{unit['id']}/source")
                entrypoint = 'section.md' if (source/'section.md').is_file() else 'presentation.md'
                if (source/entrypoint).is_file():
                    aid,relative = snapshot(service.task,source)
                    with service.store.transaction() as conn:
                        conn.execute('INSERT INTO artifacts(id,presentation,unit,path,entrypoint,created_at,origin,verified) VALUES(?,?,?,?,?,?,?,0)',
                                     (aid,deck['id'],unit['id'],relative,entrypoint,utc_now(),'import'))
                    copied.append({'presentation':deck['id'],'unit':unit['id'],'artifact_id':aid,'entrypoint':entrypoint,'verified':False})
            decks.append({'id':deck['id'],'title':deck['title'],'units':units})
        settings['presentations'] = decks
        write_yaml_atomic(service.task/'task.yaml',settings)
        runtime = state.get('confirmed_runtime_profile')
        if runtime is None and (old/'TASK-RUNTIME-PROFILE.yaml').is_file():
            runtime = read_yaml(old/'TASK-RUNTIME-PROFILE.yaml')
        if runtime is not None:
            write_yaml_atomic(service.task/'TASK-RUNTIME-PROFILE.yaml',normalize_runtime_profile(runtime))
        summary = {'legacy_root':str(old),'state_source':provenance,'presentations':len(decks),
                   'units':sum(len(d['units']) for d in decks),'imported_sources':copied,
                   'legacy_sessions_imported':0,'prior_gate_results_trusted':False,
                   'missing_briefs_require_user_or_planner':True}
        with service.store.transaction() as conn:
            event(conn,'legacy.imported',summary)
            conn.execute('INSERT INTO decisions(kind,detail_json) VALUES(?,?)',
                         ('migration-confirmation',encode({'message':'Fill missing briefs, verify references and capacity. Imported revisions are unverified; re-run gates and independent review.'})))
        return {'task':str(service.task),**summary}
    except Exception:
        remove_tree(service.task)
        raise
