"""Confirmed, lossless partition of a committed deck at whole-unit boundaries.

This is a mechanical derivative, not a new semantic review. Every slide and asset
must match the pinned publication; each child gets its own native full gate.
The original release stays immutable. Subsequent content changes use repair.
"""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path

import yaml

from mpres.marp_source import parse_deck
from mpres.util import MPresError, safe_id, utc_now
from .files import copy_tree, inside, remove_tree, snapshot
from .policy import quiescent
from .quality import Quality
from .service import Service, require_text, uid
from .store import encode, event

KIND = 'published-lossless-split-v1'


def inventory(folder):
    result = {}
    for item in sorted(folder.rglob('*')):
        rel = item.relative_to(folder).as_posix()
        path = inside(folder, rel)
        if path.is_file():
            result[rel] = hashlib.sha256(path.read_bytes()).hexdigest()
    return result


class PublishedSplit:
    def __init__(self, task):
        self.service = Service(task)
        self.task = self.service.task
        self.store = self.service.store

    def _validate(self, conn, proposal):
        from .batches import active
        quiescent(conn)
        cfg = self.service.confirmed(conn)
        if active(conn) or conn.execute("SELECT 1 FROM repair_cases WHERE state NOT IN ('completed','cancelled')").fetchone():
            raise MPresError('Finish active batch/repair before published splitting')
        if conn.execute("SELECT 1 FROM gate_runs WHERE state='running'").fetchone():
            raise MPresError('A mechanical gate is still running')
        if not isinstance(proposal, dict) or set(proposal) != {'parents'} or not isinstance(proposal['parents'],list) or len(proposal['parents']) != 1:
            raise MPresError('Published split requires exactly one parent')
        allocation = proposal['parents'][0]
        if not isinstance(allocation,dict) or set(allocation) != {'presentation', 'parts'}:
            raise MPresError('Published split only accepts presentation and parts')
        parent = safe_id(require_text(allocation['presentation'],'parent'))
        release = conn.execute("SELECT r.*,a.path FROM releases r JOIN artifacts a ON a.id=r.artifact_id JOIN decks d ON d.presentation=r.presentation WHERE r.presentation=? AND r.state='committed' AND d.phase='delivered'", (parent,)).fetchone()
        if not release:
            raise MPresError('Published split requires a currently committed delivered parent')
        if conn.execute('SELECT 1 FROM delivery_parts WHERE parent=? AND presentation<>parent', (parent,)).fetchone():
            raise MPresError('Parent already partitioned')
        source = inside(self.task, release['path'])
        parsed = parse_deck(source/'presentation.md')
        plans = [dict(r) for r in conn.execute('SELECT * FROM plan_items WHERE config_id=? AND presentation=? ORDER BY ordinal', (cfg['id'], parent))]
        units = [r['unit'] for r in plans]
        slide_units = []
        for slide in parsed.slides:
            matches = [u for u in units if slide.slide_id and slide.slide_id.startswith(parent+'-'+u+'-')]
            if len(matches) != 1:
                raise MPresError('Each published slide must identify exactly one approved unit')
            slide_units.append(matches[0])
        blocks = [u for i,u in enumerate(slide_units) if i == 0 or slide_units[i-1] != u]
        if blocks != units:
            raise MPresError('Published unit blocks must match the complete approved order')
        parts = allocation['parts']
        if not isinstance(parts, list) or len(parts) < 2:
            raise MPresError('Published split requires at least two parts')
        assigned, ids, normalized, mapping = [], set(), [], []
        for part in parts:
            if not isinstance(part,dict) or set(part) != {'id','title','estimated_pages','units'}:
                raise MPresError('Part requires id, title, estimated_pages and units only')
            pid = safe_id(require_text(part['id'],'child ID'))
            if pid in ids or conn.execute('SELECT 1 FROM decks WHERE presentation=?', (pid,)).fetchone():
                raise MPresError('Child ID already exists or is duplicated')
            chosen = part['units']
            if not isinstance(chosen,list) or not chosen or any(u not in units for u in chosen):
                raise MPresError('Select nonempty approved units')
            pages = [i+1 for i,u in enumerate(slide_units) if u in chosen]
            estimate = part['estimated_pages']
            if type(estimate) is not int or estimate != len(pages) or not 1 <= estimate <= 100:
                raise MPresError('Lossless split estimate must equal actual pages and be at most 100')
            normalized.append(dict(part, title=require_text(part['title'],'child title')))
            mapping.append({'presentation':pid,'pages':pages,'slide_ids':[parsed.slides[i-1].slide_id for i in pages]})
            assigned.extend(chosen); ids.add(pid)
        if assigned != units:
            raise MPresError('Units must form a complete ordered partition, without loss or duplication')
        for item in mapping:
            self._manifest(source,item)
        pdf = inside(self.task, release['pdf_path'])
        if not pdf.is_file():
            raise MPresError('Parent committed PDF is missing')
        baseline = {'kind':KIND,'config_id':cfg['id'],'policy_sources':cfg.get('policy_sources',{}),
                    'plan_sources':cfg.get('plan_sources',[]),'release':dict(release),'plans':plans,
                    'source_files':inventory(source),'pdf_sha256':hashlib.sha256(pdf.read_bytes()).hexdigest(),
                    'mapping':mapping}
        return {'parents':[{'presentation':parent,'parts':normalized}]}, baseline

    def _manifest(self, source, mapping):
        from .exercises import read_manifest
        manifest = read_manifest(source)
        if manifest is None:
            return None
        ids = set(mapping['slide_ids'])
        exercises = [r for r in manifest['exercises'] if r['question_slide_id'] in ids]
        if any(not set(r['answer_slide_ids']) <= ids for r in exercises):
            raise MPresError('Lossless split cannot separate an indexed question from its answer')
        result = dict(manifest, exercises=exercises)
        if 'non_exercises' in result:
            result['non_exercises'] = [r for r in result['non_exercises'] if r['slide_id'] in ids]
        return result

    def present(self, proposal):
        with self.store.transaction() as conn:
            proposal, baseline = self._validate(conn, proposal)
            ident = uid('split')
            conn.execute("INSERT INTO plan_changes(id,config_id,state,proposal_json,baseline_json,created_at) VALUES(?,?,'presented',?,?,?)",
                         (ident,baseline['config_id'],encode(proposal),encode(baseline),utc_now()))
            event(conn,'published_split.presented',{'plan_change_id':ident,'proposal':proposal,'baseline':baseline})
        return {'plan_change_id':ident,'proposal':proposal,'baseline':baseline,'production_started':False}

    def _row(self, conn, ident):
        row = conn.execute('SELECT * FROM plan_changes WHERE id=?',(ident,)).fetchone()
        if not row or json.loads(row['baseline_json']).get('kind') != KIND:
            raise MPresError('Unknown published split')
        return row

    def _check_baseline(self, conn, row):
        proposal, baseline = self._validate(conn,json.loads(row['proposal_json']))
        # This split itself is a confirmed plan, but has not changed allocation yet.
        baseline['plan_sources'] = [x for x in baseline['plan_sources'] if x != row['id']]
        if encode(baseline) != row['baseline_json']:
            raise MPresError('Published split baseline changed; present the exact scope again')
        return proposal, baseline

    def confirm(self, ident, actor):
        require_text(actor,'explicit user confirmation')
        with self.store.transaction() as conn:
            row = self._row(conn,ident)
            if row['state'] == 'confirmed':
                if row['confirmed_by'] != actor:
                    raise MPresError('Conflicting confirmation attribution')
                return {'plan_change_id':ident,'already_confirmed':True}
            if row['state'] != 'presented':
                raise MPresError('Split is no longer awaiting confirmation')
            self._check_baseline(conn,row)
            conn.execute("UPDATE plan_changes SET state='confirmed',confirmed_by=?,confirmed_at=? WHERE id=?",(actor,utc_now(),ident))
            event(conn,'published_split.confirmed',{'plan_change_id':ident,'actor':actor})
        return {'plan_change_id':ident,'already_confirmed':False,'production_started':False}

    def _event(self, conn, kind, ident, pid=None):
        query = "SELECT detail_json FROM events WHERE kind=? AND json_extract(detail_json,'$.plan_change_id')=?"
        args = [kind,ident]
        if pid:
            query += " AND json_extract(detail_json,'$.presentation')=?";args.append(pid)
        row = conn.execute(query+' ORDER BY id DESC LIMIT 1',args).fetchone()
        return json.loads(row[0]) if row else None

    def _verify_child(self, artifact, baseline, mapping):
        source = inside(self.task,baseline['release']['path'])
        child = inside(self.task,artifact['path'])
        original, derived = parse_deck(source/'presentation.md'), parse_deck(child/'presentation.md')
        expected = [original.slides[p-1].source.strip() for p in mapping['pages']]
        if derived.frontmatter != original.frontmatter or [s.source.strip() for s in derived.slides] != expected:
            raise MPresError('Derived content differs from the confirmed exact page partition')
        if {k:v for k,v in inventory(child).items() if k not in {'presentation.md','exercises.json'}} != {k:v for k,v in baseline['source_files'].items() if k not in {'presentation.md','exercises.json'}}:
            raise MPresError('Derived assets differ from the committed source')
        from .exercises import read_manifest
        if read_manifest(child) != self._manifest(source,mapping):
            raise MPresError('Derived exercise index differs from the exact partition')

    def run(self, ident, actor):
        require_text(actor,'split executor')
        from .delivery import Delivery
        with self.store.transaction() as conn:
            row = self._row(conn,ident)
            if row['state'] != 'confirmed':
                raise MPresError('Confirm exact split before executing')
            complete = self._event(conn,'published_split.committed',ident)
            if not complete:
                proposal, baseline = self._check_baseline(conn,row)
        if complete:
            return {**complete,'already_committed':True,'delivery_package':Delivery(self.task).ensure()}
        source = inside(self.task,baseline['release']['path'])
        parsed = parse_deck(source/'presentation.md')
        artifacts = []
        for mapping in baseline['mapping']:
            pid = mapping['presentation']
            with self.store.transaction() as conn:
                saved = self._event(conn,'published_split.derived',ident,pid)
            if saved:
                artifact = self.store.rows('SELECT * FROM artifacts WHERE id=?',(saved['artifact_id'],))[0]
            else:
                parent = self.task/'.mpres/work';parent.mkdir(parents=True,exist_ok=True)
                work = Path(tempfile.mkdtemp(prefix='split-',dir=parent))
                created = None
                try:
                    copy_tree(source,work/'source',read_only=False)
                    slides = [parsed.slides[p-1].source.strip() for p in mapping['pages']]
                    (work/'source/presentation.md').write_text('---\n'+yaml.safe_dump(parsed.frontmatter,allow_unicode=True,sort_keys=False)+'---\n'+'\n\n---\n\n'.join(slides)+'\n',encoding='utf-8')
                    manifest = self._manifest(source,mapping)
                    if manifest is not None:
                        (work/'source/exercises.json').write_text(encode(manifest),encoding='utf-8')
                    created = snapshot(self.task,work/'source')
                    with self.store.transaction() as conn:
                        self._check_baseline(conn,row)
                        if self._event(conn,'published_split.derived',ident,pid):
                            raise MPresError('Concurrent split derivation; rerun after it completes')
                        conn.execute("INSERT INTO artifacts(id,presentation,path,created_at,origin) VALUES(?,?,?,?,'assembly')",(created[0],pid,created[1],utc_now()))
                        event(conn,'published_split.derived',{'plan_change_id':ident,'presentation':pid,'artifact_id':created[0],'baseline_artifact_id':baseline['release']['artifact_id'],'mapping':mapping})
                    artifact = self.store.rows('SELECT * FROM artifacts WHERE id=?',(created[0],))[0]
                    created = None
                finally:
                    remove_tree(work)
                    if created:remove_tree(self.task/created[1])
            self._verify_child(artifact,baseline,mapping)
            gate = Quality(self.task).inspect_recovering(artifact['id'],'full')
            if gate['state'] != 'passed':
                return {'state':'blocked','plan_change_id':ident,'presentation':pid,'artifact_id':artifact['id'],'gate_id':gate['id'],'gate_state':gate['state'],'detail':json.loads(gate.get('detail_json') or '{}'),'model_calls':0}
            Quality(self.task).require_pass(artifact['id'])
            artifacts.append((artifact,gate,mapping))
        # Copy checked PDFs first. No committed DB rows become visible until all
        # children and their exact provenance are ready. Identical files recover
        # an interruption before the atomic publication transaction.
        for artifact,gate,mapping in artifacts:
            pid = mapping['presentation']
            target = inside(self.task,f'.mpres/releases/{pid}/r001/{pid}.pdf')
            checked = inside(self.task,gate['pdf_path'])
            target.parent.mkdir(parents=True,exist_ok=True)
            try:os.link(checked,target)
            except FileExistsError:
                if target.read_bytes() != checked.read_bytes():
                    raise MPresError('Conflicting existing split PDF; preserve and reconcile')
        with self.store.transaction() as conn:
            self._check_baseline(conn,row)
            next_deck = conn.execute('SELECT COALESCE(MAX(ordinal),-1)+1 FROM decks').fetchone()[0]
            next_plan = conn.execute('SELECT COALESCE(MAX(ordinal),0)+1 FROM plan_items').fetchone()[0]
            plans = {p['unit']:p for p in baseline['plans']}
            now = utc_now(); parent_id = baseline['release']['presentation']
            conn.execute('DELETE FROM delivery_parts WHERE presentation=? AND parent=?',(parent_id,parent_id))
            for i,(part,(artifact,gate,mapping)) in enumerate(zip(proposal['parents'][0]['parts'],artifacts)):
                self._verify_child(artifact,baseline,mapping)
                Quality(self.task).require_pass(artifact['id'],conn=conn)
                pid = part['id'];relative = f'.mpres/releases/{pid}/r001/{pid}.pdf'
                if inside(self.task,relative).read_bytes() != inside(self.task,gate['pdf_path']).read_bytes():
                    raise MPresError('Split PDF differs from the checked PDF')
                conn.execute("INSERT INTO decks(presentation,config_id,ordinal,phase,candidate_id,delivered_at) VALUES(?,?,?,'delivered',?,?)",(pid,baseline['config_id'],next_deck+i,artifact['id'],now))
                conn.execute('INSERT INTO delivery_parts VALUES(?,?,?,?,?,?)',(pid,parent_id,i,part['title'],part['estimated_pages'],ident))
                for unit in part['units']:
                    old = plans[unit]
                    cur = conn.execute('INSERT INTO plan_items(config_id,presentation,unit,deck_title,title,ordinal,brief,sources_json) VALUES(?,?,?,?,?,?,?,?)',(baseline['config_id'],pid,unit,part['title'],old['title'],next_plan,old['brief'],old['sources_json']));next_plan += 1
                    conn.execute('INSERT INTO plan_item_origins VALUES(?,?,?)',(cur.lastrowid,old['id'],baseline['release']['artifact_id']))
                conn.execute("INSERT INTO releases VALUES(?,?,?,?,'committed',?,?)",(pid,artifact['id'],gate['id'],relative,now,now))
                conn.execute("INSERT INTO release_versions VALUES(?,1,?,?,?,'committed',?,?,NULL)",(pid,artifact['id'],gate['id'],relative,now,now))
            record = {'plan_change_id':ident,'state':'completed','presentations':[p['id'] for p in proposal['parents'][0]['parts']],
                      'baseline_artifact_id':baseline['release']['artifact_id'],'actor':actor,'model_calls':0,
                      'semantic_review':'unchanged published pages; no new semantic review or exercise acceptance claimed',
                      'mapping':baseline['mapping']}
            event(conn,'published_split.committed',record)
        return {**record,'delivery_package':Delivery(self.task).ensure()}
