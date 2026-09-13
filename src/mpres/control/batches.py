"""Confirmed bounded continuation; identifiers are explicit, never prefix-matched."""
from __future__ import annotations
import json
from mpres.util import MPresError, utc_now
from .store import encode, event
from .service import Service, uid
from .policy import quiescent


def active(conn):
    row=conn.execute("SELECT * FROM production_batches WHERE state='running'").fetchone()
    return dict(row) if row else None


def targets(conn, batch_id):
    return [r[0] for r in conn.execute('SELECT presentation FROM production_batch_targets WHERE batch_id=? ORDER BY ordinal',(batch_id,))]


class Batches:
    def __init__(self,task):self.service=Service(task);self.store=self.service.store

    def _snapshot(self,conn,selected):
        quiescent(conn)
        cfg=self.service.confirmed(conn)
        if json.loads(cfg['settings_json']).get('workflow')!='full':raise MPresError('Selected delivery batches require full workflow')
        if conn.execute("SELECT 1 FROM repair_cases WHERE state NOT IN ('completed','cancelled')").fetchone():
            raise MPresError('Finish or cancel the active repair before continuing course production')
        if active(conn):raise MPresError('An existing batch already owns production scope')
        if not selected or len(selected)!=len(set(selected)):raise MPresError('Select distinct presentation IDs')
        decks={r['presentation']:dict(r) for r in conn.execute('SELECT * FROM decks')}
        if any(p not in decks for p in selected):raise MPresError('Unknown presentation; select an approved ID, not a prefix')
        if any(decks[p]['phase']=='delivered' for p in selected):raise MPresError('Do not include delivered decks; use repair instead')
        selected=sorted(selected,key=lambda p:decks[p]['ordinal'])
        from .inspection import plan_checks
        settings=json.loads(cfg['settings_json']);checks=plan_checks(settings)
        if any(not checks[p]['success'] for p in selected):raise MPresError('Selected planned deck exceeds 100 pages; replan before writing')
        return {'config_id':cfg['id'],'policy_sources':cfg.get('policy_sources',{}),'presentations':selected,
                'decks':[decks[p] for p in selected],'page_estimates':{p:checks[p] for p in selected},
                'units':[dict(r) for r in conn.execute('SELECT * FROM plan_items WHERE config_id=? ORDER BY ordinal',(cfg['id'],)) if r['presentation'] in selected],
                'stop_after':'all_selected_delivered','unselected_work':'not_admitted'}

    def present(self,selected):
        from .workflow import Workflow
        Workflow(self.service.task).ensure()
        with self.store.transaction() as conn:
            snapshot=self._snapshot(conn,selected);bid=uid('batch')
            conn.execute("INSERT INTO production_batches(id,config_id,state,snapshot_json,created_at) VALUES(?,?,'presented',?,?)",(bid,snapshot['config_id'],encode(snapshot),utc_now()))
            for i,p in enumerate(snapshot['presentations']):conn.execute('INSERT INTO production_batch_targets VALUES(?,?,?)',(bid,p,i))
            event(conn,'batch.presented',{'batch_id':bid,'presentations':snapshot['presentations']})
        return {'batch_id':bid,**snapshot,'instruction':'Present this exact scope and obtain real user confirmation before confirming.'}

    def confirm(self,batch_id,actor):
        if not isinstance(actor,str) or not actor.strip():raise MPresError('Explicit user confirmation attribution required')
        with self.store.transaction() as conn:
            row=conn.execute('SELECT * FROM production_batches WHERE id=?',(batch_id,)).fetchone()
            if not row:raise MPresError('Unknown batch')
            if row['state']=='running':
                if row['confirmed_by'] != actor:
                    raise MPresError('Conflicting batch confirmation attribution')
                return {'batch_id':batch_id,'already_confirmed':True}
            if row['state']!='presented':raise MPresError('Batch cannot be reopened')
            snapshot=json.loads(row['snapshot_json'])
            if self._snapshot(conn,snapshot['presentations'])!=snapshot:raise MPresError('Batch or policy changed after presentation; present it again')
            conn.execute("UPDATE production_batches SET state='running',confirmed_at=?,confirmed_by=? WHERE id=?",(utc_now(),actor,batch_id))
            conn.execute("UPDATE task SET status='running'")
            # Resolve delivery feedback only: independent semantic issues remain.
            for d in conn.execute("SELECT id FROM decisions WHERE kind='delivery-feedback' AND resolved_at IS NULL"):
                conn.execute('UPDATE decisions SET resolved_at=?,answer=? WHERE id=?',(utc_now(),encode({'actor':actor,'batch_id':batch_id}),d['id']))
            event(conn,'batch.confirmed',{'batch_id':batch_id,'actor':actor,'presentations':snapshot['presentations']})
        return {'batch_id':batch_id,'already_confirmed':False,'scope':snapshot['presentations']}

    def status(self):
        return [{**r,'presentations':[t['presentation'] for t in self.store.rows('SELECT presentation FROM production_batch_targets WHERE batch_id=? ORDER BY ordinal',(r['id'],))]} for r in self.store.rows('SELECT id,state,created_at,confirmed_at,confirmed_by FROM production_batches ORDER BY created_at')]


def completed(conn,presentation):
    batch=active(conn)
    if not batch:return False
    selected=targets(conn,batch['id'])
    if presentation not in selected:raise MPresError('Publication is outside the active batch')
    pending=conn.execute("SELECT 1 FROM production_batch_targets t JOIN decks d ON d.presentation=t.presentation WHERE t.batch_id=? AND d.phase<>'delivered'",(batch['id'],)).fetchone()
    if not pending:
        conn.execute("UPDATE production_batches SET state='completed' WHERE id=?",(batch['id'],))
        conn.execute("UPDATE task SET status='paused'")
        event(conn,'batch.completed',{'batch_id':batch['id'],'presentations':selected,'next_action':'pause'})
    return True
