"""Explicit delivery partition over immutable teaching plans.

A chapter/content scope is not a PDF identifier. Confirmed, ordered unit
allocations replace only dispatch views, never historical plans, releases,
runtime or source revisions. Cutting within a unit is a semantic replan, not an
automatic page-100 cut. This module does not invoke a model.
"""
from __future__ import annotations

import copy
import json

from mpres.util import MPresError, utc_now
from .store import encode, event


def ancestors(conn, presentation):
    chain=[]; current=presentation
    while current not in chain:
        chain.append(current)
        row=conn.execute('SELECT parent FROM delivery_parts WHERE presentation=?',(current,)).fetchone()
        if not row or row[0]==current:return chain
        current=row[0]
    raise MPresError('Cyclic delivery partition; do not guess runtime or source lineage')


def runtime_origin(conn, presentation):
    return ancestors(conn,presentation)[-1]


def leaves(conn, presentation):
    def expand(pid, seen):
        if pid in seen:raise MPresError('Cyclic delivery partition')
        rows=conn.execute('SELECT presentation FROM delivery_parts WHERE parent=? AND presentation<>parent ORDER BY ordinal',(pid,)).fetchall()
        if not rows:return [pid]
        return [leaf for r in rows for leaf in expand(r[0],seen|{pid})]
    return expand(presentation,set())


def superseded(conn, presentation):
    return bool(conn.execute('SELECT 1 FROM delivery_parts WHERE parent=? AND presentation<>parent',(presentation,)).fetchone())


def effective_config(conn, config):
    """Only call after original documents and explicit policy have been checked."""
    result=dict(config);settings=json.loads(result['settings_json']);output=[]
    for deck in settings['presentations']:
        for pid in leaves(conn,deck['id']):
            part=conn.execute('SELECT * FROM delivery_parts WHERE presentation=?',(pid,)).fetchone()
            if not part:
                output.append(deck);continue
            item=copy.deepcopy(deck)
            item.update(id=pid,title=part['title'],estimated_pages=part['estimated_pages'])
            plans=conn.execute('SELECT * FROM plan_items WHERE config_id=? AND presentation=? ORDER BY ordinal',(config['id'],pid)).fetchall()
            item['units']=[{'id':p['unit'],'title':p['title'],'brief':p['brief'],'sources':json.loads(p['sources_json'])} for p in plans]
            output.append(item)
    settings['presentations']=output;result['settings_json']=encode(settings)
    result['plan_sources']=[r[0] for r in conn.execute("SELECT id FROM plan_changes WHERE config_id=? AND state='confirmed' ORDER BY confirmed_at,rowid",(config['id'],))]
    return result


def fresh_source_cutoff(conn, presentation):
    scope=set(ancestors(conn,presentation))
    for row in conn.execute("SELECT proposal_json,baseline_json FROM plan_changes WHERE state='confirmed' ORDER BY rowid DESC"):
        proposal=json.loads(row['proposal_json'])
        fresh={p['presentation'] for p in proposal['parents'] if p.get('source_mode')=='fresh'}
        if scope & fresh:
            baseline=json.loads(row['baseline_json'])
            return max(p['artifact_cutoff'] for p in baseline['parents'] if p['deck']['presentation'] in scope & fresh)
    return None


def source_artifact(conn, plan):
    cutoff=fresh_source_cutoff(conn,plan['presentation'])
    if cutoff is not None:
        row=conn.execute("SELECT r.* FROM artifacts r JOIN attempts a ON a.id=r.attempt_id JOIN jobs j ON j.id=a.job_id WHERE j.plan_item_id=? AND a.state='succeeded' AND r.rowid>? ORDER BY r.rowid DESC LIMIT 1",(plan['id'],cutoff)).fetchone()
        return dict(row) if row else None
    # Prefer current accepted unit work, then an explicitly recorded baseline,
    # then a legacy import. Existence does not confer current gate approval.
    row=conn.execute("SELECT r.* FROM artifacts r JOIN attempts a ON a.id=r.attempt_id JOIN jobs j ON j.id=a.job_id WHERE j.plan_item_id=? AND a.state='succeeded' ORDER BY r.created_at DESC,r.rowid DESC LIMIT 1",(plan['id'],)).fetchone()
    if row:return dict(row)
    row=conn.execute('SELECT r.* FROM artifacts r JOIN plan_item_origins o ON o.baseline_artifact_id=r.id WHERE o.plan_item_id=?',(plan['id'],)).fetchone()
    if row:return dict(row)
    row=conn.execute("SELECT * FROM artifacts WHERE presentation=? AND unit=? AND origin='import' ORDER BY created_at DESC,rowid DESC LIMIT 1",(plan['presentation'],plan['unit'])).fetchone()
    return dict(row) if row else None


def inherited_history(conn, handle, presentation):
    scope=ancestors(conn,presentation)
    return conn.execute('SELECT * FROM participation WHERE session_id=? AND presentation IN ('+','.join('?' for _ in scope)+')',(handle,*scope)).fetchall()


class Planning:
    def __init__(self, task):
        from .service import Service
        self.service=Service(task);self.store=self.service.store

    def _validate(self, conn, proposal):
        from .service import safe_id, require_text
        from .policy import quiescent
        from .batches import active
        quiescent(conn)
        cfg=self.service.confirmed(conn)
        if json.loads(cfg['settings_json']).get('workflow')!='full':raise MPresError('Delivery partition requires full workflow')
        if active(conn):raise MPresError('Finish the active batch before changing its membership')
        if conn.execute("SELECT 1 FROM repair_cases WHERE state NOT IN ('completed','cancelled')").fetchone():raise MPresError('Finish or cancel active repair before splitting delivery scope')
        if not isinstance(proposal,dict) or set(proposal)!={'parents'} or not isinstance(proposal['parents'],list) or not proposal['parents']:
            raise MPresError('Proposal requires a nonempty parents list only')
        effective=json.loads(cfg['settings_json'])['presentations'];order={d['id']:i for i,d in enumerate(effective)}
        old={r['presentation']:dict(r) for r in conn.execute('SELECT * FROM decks')}
        selected=set();new_ids=set();normalized=[];baseline=[]
        for allocation in proposal['parents']:
            if not isinstance(allocation,dict) or set(allocation) not in ({'presentation','parts'},{'presentation','parts','source_mode'}):raise MPresError('Allocation requires presentation, parts and optional source_mode')
            source_mode=allocation.get('source_mode','reuse')
            if source_mode not in ('reuse','fresh'):raise MPresError('Source mode must be reuse or fresh')
            parent=allocation['presentation']
            if not isinstance(parent,str):raise MPresError('Parent ID must be text')
            safe_id(parent,label='parent presentation')
            if parent not in order or parent in selected:raise MPresError('Select each existing effective parent exactly once')
            selected.add(parent)
            d=old.get(parent)
            if not d or d['phase']!='units' or d['candidate_id'] or d['active_job_id'] or conn.execute('SELECT 1 FROM releases WHERE presentation=?',(parent,)).fetchone():
                raise MPresError('Only unassembled, unpublished content may be partitioned; delivered p01 is not a new plan')
            if conn.execute('SELECT 1 FROM delivery_parts WHERE parent=? AND presentation<>parent',(parent,)).fetchone():raise MPresError('Parent has already been replaced by its delivery parts')
            plans=[dict(r) for r in conn.execute('SELECT * FROM plan_items WHERE config_id=? AND presentation=? ORDER BY ordinal',(cfg['id'],parent))]
            if not plans:raise MPresError('Parent has no approved units')
            parts=allocation['parts']
            if not isinstance(parts,list) or not parts:raise MPresError('Every parent requires nonempty parts')
            normalized_parts=[];assigned=[]
            for p in parts:
                if not isinstance(p,dict) or set(p)!={'id','title','estimated_pages','units'}:raise MPresError('Part requires only id, title, estimated_pages and units; no runtime overrides')
                if not isinstance(p['id'],str):raise MPresError('Delivery ID must be text')
                pid=safe_id(p['id'],label='delivery part');title=require_text(p['title'],'delivery title');pages=p['estimated_pages']
                if type(pages) is not int or not 1<=pages<=100:raise MPresError('Every planned part must estimate 1..100 pages; estimate is not a final page count')
                if pid in new_ids or (pid in old and not (len(parts)==1 and pid==parent)):raise MPresError('Delivery ID already exists or is duplicated')
                if pid==parent and len(parts)>1:raise MPresError('A split parent must not also be its own child')
                units=p['units']
                if not isinstance(units,list) or not units or any(not isinstance(u,str) for u in units):raise MPresError('Each part must explicitly allocate nonempty approved units')
                assigned.extend(units);new_ids.add(pid)
                normalized_parts.append({'id':pid,'title':title,'estimated_pages':pages,'units':units})
            if assigned!=[p['unit'] for p in plans]:raise MPresError('Units must form a complete ordered partition; no loss, duplication, new unit or unapproved reordering')
            normalized.append({'presentation':parent,'parts':normalized_parts,**({'source_mode':source_mode} if 'source_mode' in allocation else {})})
            baseline.append({'deck':d,'plans':plans,
                **({'artifact_cutoff':conn.execute('SELECT COALESCE(MAX(rowid),0) FROM artifacts').fetchone()[0]} if source_mode=='fresh' else {}),
                'prior_allocation':[dict(r) for r in conn.execute('SELECT * FROM delivery_parts WHERE presentation=? OR parent=? ORDER BY rowid',(parent,parent))],
                'sources':{str(p['id']):source_artifact(conn,p) for p in plans},
                'jobs':[dict(r) for r in conn.execute('SELECT * FROM jobs WHERE presentation=? ORDER BY id',(parent,))]})
        normalized.sort(key=lambda a:order[a['presentation']]);baseline.sort(key=lambda a:order[a['deck']['presentation']])
        return {'parents':normalized},{'config_id':cfg['id'],'policy_sources':cfg.get('policy_sources',{}),'plan_sources':cfg.get('plan_sources',[]),'parents':baseline}

    def present(self, proposal):
        from .workflow import Workflow
        from .service import uid
        Workflow(self.service.task).ensure()
        with self.store.transaction() as conn:
            proposal,baseline=self._validate(conn,proposal);ident=uid('plan')
            conn.execute("INSERT INTO plan_changes(id,config_id,state,proposal_json,baseline_json,created_at) VALUES(?,?,'presented',?,?,?)",(ident,baseline['config_id'],encode(proposal),encode(baseline),utc_now()))
            event(conn,'plan.partition_presented',{'plan_change_id':ident,'proposal':proposal})
        return {'plan_change_id':ident,'proposal':proposal,'baseline':baseline,
                'instruction':'Show these exact teaching boundaries, estimates and source reuse to the user. No writing is authorized by presentation alone.'}

    def confirm(self, ident, actor):
        from .service import require_text
        actor=require_text(actor,'explicit user confirmation attribution')
        with self.store.transaction() as conn:
            row=conn.execute('SELECT * FROM plan_changes WHERE id=?',(ident,)).fetchone()
            if not row:raise MPresError('Unknown plan change')
            if row['state']=='confirmed':
                if row['confirmed_by']!=actor:raise MPresError('Conflicting confirmation attribution')
                return {'plan_change_id':ident,'already_confirmed':True}
            if row['state']!='presented':raise MPresError('Cancelled plan cannot be confirmed')
            proposal,baseline=self._validate(conn,json.loads(row['proposal_json']))
            if encode(baseline)!=row['baseline_json']:raise MPresError('Plan, source work or policy changed since presentation; present the new scope again')
            next_deck=conn.execute('SELECT COALESCE(MAX(ordinal),-1)+1 FROM decks').fetchone()[0]
            next_unit=conn.execute('SELECT COALESCE(MAX(ordinal),0)+1 FROM plan_items').fetchone()[0]
            snapshots={p['deck']['presentation']:p for p in baseline['parents']}
            for allocation in proposal['parents']:
                parent=allocation['presentation'];snapshot=snapshots[parent];plans={p['unit']:p for p in snapshot['plans']}
                if len(allocation['parts'])>1:
                    # Replace only the current estimate-only projection. Its exact
                    # confirmed proposal remains in plan_changes as immutable history.
                    conn.execute('DELETE FROM delivery_parts WHERE presentation=? AND parent=?',(parent,parent))
                for index,part in enumerate(allocation['parts']):
                    pid=part['id']
                    if pid!=parent:
                        conn.execute("INSERT INTO decks(presentation,config_id,ordinal,phase) VALUES(?,?,?,'units')",(pid,baseline['config_id'],next_deck));next_deck+=1
                        for unit in part['units']:
                            old=plans[unit]
                            cur=conn.execute('INSERT INTO plan_items(config_id,presentation,unit,deck_title,title,ordinal,brief,sources_json) VALUES(?,?,?,?,?,?,?,?)',(baseline['config_id'],pid,unit,part['title'],old['title'],next_unit,old['brief'],old['sources_json']));next_unit+=1
                            source=snapshot['sources'][str(old['id'])]
                            conn.execute('INSERT INTO plan_item_origins VALUES(?,?,?)',(cur.lastrowid,old['id'],source['id'] if source else None))
                    existing=conn.execute('SELECT * FROM delivery_parts WHERE presentation=?',(pid,)).fetchone()
                    if existing:
                        # Estimate/title refinement preserves the existing root lineage.
                        conn.execute('UPDATE delivery_parts SET title=?,estimated_pages=?,change_id=? WHERE presentation=?',(part['title'],part['estimated_pages'],ident,pid))
                    else:
                        conn.execute('INSERT INTO delivery_parts VALUES(?,?,?,?,?,?)',(pid,parent,index,part['title'],part['estimated_pages'],ident))
            conn.execute("UPDATE plan_changes SET state='confirmed',confirmed_at=?,confirmed_by=? WHERE id=?",(utc_now(),actor,ident))
            event(conn,'plan.partition_confirmed',{'plan_change_id':ident,'actor':actor,'proposal':proposal})
        return {'plan_change_id':ident,'already_confirmed':False,'production_started':False,'parents':proposal['parents']}

    def cancel(self, ident, actor):
        from .service import require_text
        actor=require_text(actor,'cancellation attribution')
        with self.store.transaction() as conn:
            row=conn.execute('SELECT state FROM plan_changes WHERE id=?',(ident,)).fetchone()
            if not row or row[0]!='presented':raise MPresError('Only unconfirmed proposals may be cancelled')
            conn.execute("UPDATE plan_changes SET state='cancelled' WHERE id=?",(ident,))
            event(conn,'plan.partition_cancelled',{'plan_change_id':ident,'actor':actor})
        return {'plan_change_id':ident,'state':'cancelled'}

    def show(self):
        with self.store.transaction() as conn:
            cfg=self.service.confirmed(conn)
            return {'presentations':json.loads(cfg['settings_json'])['presentations'],
                    'allocations':[dict(r) for r in conn.execute('SELECT * FROM delivery_parts ORDER BY rowid')],
                    'proposals':[dict(r) for r in conn.execute('SELECT id,state,created_at,confirmed_at,confirmed_by FROM plan_changes ORDER BY rowid')],
                    'original_configuration_unchanged':True,'production_started':False}
