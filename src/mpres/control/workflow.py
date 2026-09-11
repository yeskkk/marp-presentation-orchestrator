"""Fixed deck workflow over relational facts; no model-based coordinators.

Small transactions publish a state transition. Parsing, rendering, model calls and
file staging occur outside writer transactions. An unresolved attempt or gate is
never automatically declared dead. A source revision is not a published deck.
"""
from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

import yaml

from mpres.marp_source import parse_deck
from mpres.util import MPresError, utc_now
from .delivery import Delivery
from .files import inside, remove_tree, snapshot
from .quality import Quality
from .service import CHANNELS, Service, require_text, uid
from .store import encode, event


def validate_result(service: Service, job: dict, result: dict, source: Path | None) -> None:
    """Evidence validation, not a claim that code can judge semantic correctness."""
    decks = service.store.rows('SELECT * FROM decks WHERE presentation=?', (job['presentation'],))
    if not decks:
        return  # Draft-only v0.6.8/9 API remains explicitly separate.
    deck = decks[0]
    if job['kind'] == 'review':
        if deck['frozen_id'] != job['input_artifact_id']:
            raise MPresError('Reviewer must read the exact current frozen revision')
        gate = Quality(service.task).require_pass(deck['frozen_id'])
        artifact = service.store.rows('SELECT * FROM artifacts WHERE id=?', (deck['frozen_id'],))[0]
        ids = {s.slide_id for s in parse_deck(service.task/artifact['path']/'presentation.md').slides}
        findings = result.get('findings')
        if not isinstance(findings, list):
            raise MPresError('Review result requires findings, including [] when none')
        for finding in findings:
            if not isinstance(finding, dict) or set(finding) != {'message', 'slide_ids', 'severity'}:
                raise MPresError('Each review finding requires exactly message, slide_ids, severity')
            require_text(finding['message'], 'Finding message')
            if finding['severity'] not in {'minor', 'major', 'critical'}:
                raise MPresError('Invalid finding severity')
            cited = finding['slide_ids']
            if not isinstance(cited, list) or not cited or any(not isinstance(x,str) or x not in ids for x in cited):
                raise MPresError('Finding evidence must cite frozen canonical slide IDs')
    if job['kind'] == 'revise' and deck['frozen_id']:
        expected = {r['id'] for r in service.store.rows('SELECT id FROM findings WHERE artifact_id=?', (deck['frozen_id'],))}
        rows = result.get('resolutions')
        if not isinstance(rows, list):
            raise MPresError('Revision must account for every finding in resolutions')
        seen = set()
        for row in rows:
            if not isinstance(row,dict) or set(row) != {'finding_id','status','explanation'}:
                raise MPresError('Resolution requires finding_id, status, explanation')
            if row['finding_id'] not in expected or row['finding_id'] in seen:
                raise MPresError('Unknown or duplicate finding resolution')
            if row['status'] not in {'addressed','needs_decision'}:
                raise MPresError('Resolution status must be addressed or needs_decision')
            require_text(row['explanation'], 'Concrete revision explanation')
            seen.add(row['finding_id'])
        if seen != expected:
            raise MPresError('Revision omitted finding resolutions')
        if source:
            frozen = service.store.rows('SELECT * FROM artifacts WHERE id=?', (deck['frozen_id'],))[0]
            previous = {s.slide_id for s in parse_deck(service.task/frozen['path']/'presentation.md').slides}
            now = {s.slide_id for s in parse_deck(source/'presentation.md').slides}
            if not previous <= now:
                raise MPresError('Post-review revision must retain frozen slide IDs; scope changes require a new task/review')


class Workflow:
    def __init__(self, task: Path):
        self.service = Service(task)
        self.task = self.service.task
        self.store = self.service.store
        self.quality = Quality(self.task)

    def enabled(self) -> bool:
        with self.store.transaction() as conn:
            return json.loads(self.service.confirmed(conn)['settings_json']).get('workflow', 'authoring') == 'full'

    def ensure(self) -> None:
        with self.store.transaction() as conn:
            cfg = self.service.confirmed(conn)
            settings = json.loads(cfg['settings_json'])
            if settings.get('workflow', 'authoring') != 'full':
                return
            for i, deck in enumerate(settings['presentations']):
                conn.execute("INSERT OR IGNORE INTO decks(presentation,config_id,ordinal,phase) VALUES(?,?,?,'units')", (deck['id'], cfg['id'], i))

    def status(self) -> dict:
        return {'enabled': self.enabled(), 'decks': self.store.rows('SELECT * FROM decks ORDER BY ordinal'),
                'decisions': self.store.rows('SELECT * FROM decisions WHERE resolved_at IS NULL'),
                'releases': self.store.rows('SELECT * FROM releases ORDER BY created_at'),
                'delivery_package': Delivery(self.task).status()}

    def allowed(self) -> set[str]:
        """One current + one future writing lane, subject to feedback and shared pool."""
        with self.store.transaction() as conn:
            cfg = self.service.confirmed(conn)
            task = conn.execute('SELECT status FROM task').fetchone()
            if task['status'] != 'running':
                return set()
            settings = json.loads(cfg['settings_json'])
            case=conn.execute("SELECT id FROM repair_cases WHERE state='running'").fetchone()
            if case:
                return {r['presentation'] for r in conn.execute("SELECT d.presentation FROM decks d JOIN repair_targets t ON t.presentation=d.presentation WHERE t.case_id=? AND d.phase NOT IN ('delivered','blocked') ORDER BY d.ordinal LIMIT 2",(case['id'],))}
            decks = conn.execute("SELECT * FROM decks WHERE phase<>'delivered' ORDER BY ordinal").fetchall()
            # Failed/uncertain current work does not speculate more downstream work.
            if not decks or decks[0]['phase'] == 'blocked':
                return set()
            window = 2 if settings['delivery'] == 'all' or (settings['delivery']=='pilot' and conn.execute("SELECT 1 FROM decisions WHERE kind='delivery-feedback' AND resolved_at IS NOT NULL").fetchone()) else 1
            return {d['presentation'] for d in decks[:window]}

    def _deck(self, presentation: str) -> dict:
        rows = self.store.rows('SELECT * FROM decks WHERE presentation=?', (presentation,))
        if not rows:
            raise MPresError('No lifecycle for this presentation')
        return rows[0]

    def _set(self, deck: dict, phase: str, **fields) -> bool:
        if set(fields)-{'candidate_id','frozen_id','active_job_id','repair_count','blocked_from','block_reason','delivered_at'}:
            raise MPresError('Unknown internal deck field')
        with self.store.transaction() as conn:
            self.service.confirmed(conn)
            current = conn.execute('SELECT * FROM decks WHERE presentation=?', (deck['presentation'],)).fetchone()
            if any(current[k] != deck[k] for k in ('phase','candidate_id','active_job_id','repair_count')):
                return False
            values = {'phase': phase, **fields}
            conn.execute('UPDATE decks SET '+','.join(k+'=?' for k in values)+' WHERE presentation=?', (*values.values(), deck['presentation']))
            event(conn, 'deck.transition', {'presentation': deck['presentation'], 'from': deck['phase'], 'to': phase})
            return True

    def block(self, deck: dict, reason: str) -> None:
        with self.store.transaction() as conn:
            current = conn.execute('SELECT phase FROM decks WHERE presentation=?', (deck['presentation'],)).fetchone()
            if current['phase'] == 'blocked':
                return
            conn.execute("UPDATE decks SET phase='blocked',blocked_from=?,block_reason=? WHERE presentation=?", (current['phase'], reason, deck['presentation']))
            conn.execute('INSERT INTO decisions(kind,presentation,detail_json) VALUES(?,?,?)', ('workflow-blocked', deck['presentation'], encode({'reason':reason,'resume_phase':current['phase']})))
            event(conn, 'deck.blocked', {'presentation': deck['presentation'], 'reason': reason})

    def retry_checks(self, presentation: str, note: str) -> dict:
        """Retry a completed mechanical failure after environmental correction.

        Never rewrites content, runtime, findings, or an outstanding AI attempt.
        """
        require_text(note, 'Operator correction note')
        deck = self._deck(presentation)
        if deck['phase'] != 'blocked' or deck['blocked_from'] not in {'preflight','postflight'}:
            raise MPresError('Only a blocked full-gate phase supports this recovery')
        gate = self.quality.latest(deck['candidate_id'], 'full')
        if not gate or gate['state'] not in {'failed','interrupted'}:
            raise MPresError('No completed failed gate to retry; a running checker must first be reconciled')
        report = self.quality.inspect(deck['candidate_id'], 'full', retry=True)
        from .recovery import CONTENT_FAILURES
        content_failure=report['state']=='failed' and json.loads(report.get('detail_json') or '{}').get('failure_kind') in CONTENT_FAILURES
        if report['state']=='passed' or content_failure:
            if self._set(deck, deck['blocked_from'], blocked_from=None, block_reason=None):
                with self.store.transaction() as conn:
                    # Resolve only the specific blocking reason/phase we resumed.
                    candidates=conn.execute("SELECT id,detail_json FROM decisions WHERE presentation=? AND kind='workflow-blocked' AND resolved_at IS NULL ORDER BY id DESC",(presentation,)).fetchall()
                    for decision in candidates:
                        detail=json.loads(decision['detail_json'])
                        if (detail.get('reason'),detail.get('resume_phase'))==(deck['block_reason'],deck['blocked_from']):
                            conn.execute('UPDATE decisions SET resolved_at=?,answer=? WHERE id=?',(utc_now(),note,decision['id']))
                            break
        return report

    def continue_delivery(self, actor: str, note: str) -> dict:
        require_text(actor, 'User confirmation attribution');require_text(note, 'Feedback/continuation note')
        with self.store.transaction() as conn:
            self.service.confirmed(conn)
            row = conn.execute("SELECT * FROM decisions WHERE kind='delivery-feedback' AND resolved_at IS NULL ORDER BY id LIMIT 1").fetchone()
            if not row or conn.execute('SELECT status FROM task').fetchone()[0] != 'paused':
                raise MPresError('No delivery feedback pause to continue')
            conn.execute('UPDATE decisions SET resolved_at=?,answer=? WHERE id=?', (utc_now(), encode({'actor':actor,'note':note}), row['id']))
            conn.execute("UPDATE task SET status='running'")
            event(conn, 'task.delivery_continued', {'actor':actor,'presentation':row['presentation']})
        return {'continued': True}

    def recover_assembly(self, job_id: str, note: str) -> dict:
        require_text(note, 'Verified stopped-process note')
        with self.store.transaction() as conn:
            self.service.confirmed(conn)
            job=conn.execute('SELECT * FROM jobs WHERE id=?',(job_id,)).fetchone()
            if not job or job['kind']!='assemble' or job['state'] not in {'running','failed'}:
                raise MPresError('Only a stopped local assembly may be retried here')
            conn.execute("UPDATE attempts SET state='failed',error=?,finished_at=? WHERE job_id=? AND session_id IS NULL AND state='running'",(note,utc_now(),job_id))
            conn.execute("UPDATE jobs SET state='queued' WHERE id=?",(job_id,))
            conn.execute("UPDATE decks SET phase='units',block_reason=NULL,blocked_from=NULL WHERE presentation=? AND phase='blocked' AND blocked_from='units'",(job['presentation'],))
            event(conn,'assembly.recovered',{'job_id':job_id,'note':note},job_id)
        return {'retry_queued':job_id}

    def retry_publish(self, presentation: str, note: str) -> dict:
        require_text(note,'Operator publication-recovery note')
        deck=self._deck(presentation)
        if deck['phase']!='blocked' or deck['blocked_from']!='releasing':
            raise MPresError('Only a blocked publication can be reconciled here')
        self._review_proof(deck)
        self.quality.require_pass(deck['candidate_id'])
        self._set(deck,'releasing',blocked_from=None,block_reason=None)
        with self.store.transaction() as conn:
            event(conn,'publication.retry_requested',{'presentation':presentation,'note':note})
        return self.advance()

    def _output(self, job_id: str) -> dict | None:
        rows = self.store.rows("SELECT r.* FROM artifacts r JOIN attempts a ON a.id=r.attempt_id WHERE a.job_id=? AND a.state='succeeded' ORDER BY r.rowid DESC LIMIT 1", (job_id,))
        return rows[0] if rows else None

    def _editor(self, deck: dict, artifact: str, *, kind: str, key: str, plan_item=None) -> str:
        with self.store.transaction() as conn:
            return self.service.ensure_job(conn, key=key, presentation=deck['presentation'], kind=kind,
                                           artifact=artifact, plan_item_id=plan_item)

    def advance(self) -> dict:
        if not self.enabled():
            return {'enabled': False, 'changed': False}
        self.service.materialize();self.ensure()
        before = self.store.rows('SELECT * FROM decks ORDER BY ordinal')
        # Multiple cheap transitions can converge in one tick. Expensive gates
        # are each claimed once in Quality; no loop re-renders an existing pass.
        for _ in range(12):
            changed = False
            for deck in self.store.rows('SELECT * FROM decks ORDER BY ordinal'):
                if deck['presentation'] not in self.allowed():
                    continue
                try:
                    changed = self._advance_deck(deck) or changed
                except (MPresError, OSError, ValueError) as exc:
                    self.block(self._deck(deck['presentation']), f'{type(exc).__name__}: {exc}')
                    changed = True
            if not changed:
                break
        package = Delivery(self.task).ensure()
        from .repairs import RepairDelivery
        repair_packages=[{'case_id':c['id'],**RepairDelivery(self.task,c['id']).ensure()} for c in self.store.rows("SELECT id FROM repair_cases WHERE state='completed' ORDER BY created_at")]
        return {**self.status(), 'delivery_package': package, 'repair_packages':repair_packages,
                'changed': before != self.store.rows('SELECT * FROM decks ORDER BY ordinal')}

    def _advance_deck(self, deck: dict) -> bool:
        phase = deck['phase']
        if phase == 'units':
            plans = self.store.rows('SELECT * FROM plan_items WHERE presentation=? ORDER BY ordinal', (deck['presentation'],))
            artifacts=[]
            for plan in plans:
                rows = self.store.rows("SELECT r.* FROM artifacts r JOIN attempts a ON a.id=r.attempt_id JOIN jobs j ON j.id=a.job_id WHERE j.plan_item_id=? AND a.state='succeeded' ORDER BY r.rowid DESC LIMIT 1", (plan['id'],))
                if not rows:
                    failed=self.store.rows("SELECT id FROM jobs WHERE plan_item_id=? AND state IN ('blocked','failed')",(plan['id'],))
                    if failed:
                        raise MPresError('A unit job is blocked or failed; inspect its exact attempt/decision')
                    return False
                artifact=rows[0];gate=self.quality.inspect_recovering(artifact['id'])
                if gate['state'] == 'running':
                    return False
                if gate['state'] != 'passed':
                    from .recovery import CONTENT_FAILURES
                    if json.loads(gate.get('detail_json') or '{}').get('failure_kind') not in CONTENT_FAILURES:
                        raise MPresError('Unit checker environment failed; do not ask an author to change correct source')
                    with self.store.transaction() as conn:
                        cfg=json.loads(self.service.confirmed(conn)['settings_json'])
                        count=conn.execute("SELECT count(*) FROM jobs WHERE plan_item_id=? AND kind='edit'", (plan['id'],)).fetchone()[0]
                    existing=self.store.rows('SELECT * FROM jobs WHERE key=?', (f"unit-repair:{artifact['id']}",))
                    if existing and existing[0]['state'] in {'failed','blocked'}:
                        raise MPresError('Unit repair job cannot proceed; inspect its exact attempt/decision')
                    if not existing and count >= cfg['max_attempts']:
                        raise MPresError('Unit source repair budget exhausted; semantic/environment decision required')
                    self._editor(deck, artifact['id'], kind='edit', key=f"unit-repair:{artifact['id']}", plan_item=plan['id'])
                    return False
                artifacts.append(artifact)
            combined=self.assemble(deck, artifacts)
            if not combined:
                return False
            job=self._editor(deck, combined, kind='edit', key=f'edit-deck:{combined}')
            return self._set(deck, 'editing', candidate_id=combined, active_job_id=job)
        if phase in {'editing','revising'}:
            output=self._output(deck['active_job_id'])
            if not output:
                job=self.service.job(deck['active_job_id'])
                if job['state'] in {'failed','blocked'}:
                    raise MPresError('Editor job is blocked or failed; inspect its exact attempt/decision')
                return False
            if phase == 'revising':
                pending=self.store.rows('SELECT * FROM findings WHERE artifact_id=?', (deck['frozen_id'],))
                if any(not f['resolution_json'] or json.loads(f['resolution_json']).get('status')!='addressed' for f in pending):
                    raise MPresError('Author requested a semantic decision; unresolved findings cannot be released')
            return self._set(deck, 'preflight' if phase=='editing' else 'postflight', candidate_id=output['id'], active_job_id=None)
        if phase in {'preflight','postflight'}:
            from .feedback import Feedback
            Feedback(self.task).require_author_clear(deck['candidate_id'])
            from .repairs import Repairs
            Repairs(self.task).require_clear(deck['candidate_id'])
            gate=self.quality.inspect_recovering(deck['candidate_id'], 'full')
            if gate['state']=='running':
                return False
            if gate['state']!='passed':
                detail=json.loads(gate['detail_json'] or '{}')
                with self.store.transaction() as conn:
                    limit=json.loads(self.service.confirmed(conn)['settings_json'])['max_attempts']
                if detail.get('failure_kind') in {'content','layout_or_renderer','pdf'} and deck['repair_count']<limit:
                    kind='edit' if phase=='preflight' else 'revise'
                    job=self._editor(deck, deck['candidate_id'], kind=kind, key=f"gate-repair:{deck['candidate_id']}:{gate['id']}")
                    return self._set(deck, 'editing' if kind=='edit' else 'revising', active_job_id=job, repair_count=deck['repair_count']+1)
                raise MPresError('Full gate failed; correct environment or resolve bounded repair failure before retry')
            if phase=='postflight':
                return self._set(deck,'releasing')
            with self.store.transaction() as conn:
                current=conn.execute('SELECT * FROM decks WHERE presentation=?',(deck['presentation'],)).fetchone()
                if current['phase']!='preflight' or current['candidate_id']!=deck['candidate_id']:
                    return False
                for channel in CHANNELS:
                    self.service.ensure_job(conn,key=f"review:{deck['candidate_id']}:{channel}",presentation=deck['presentation'],kind='review',round=deck['review_round'],channel=channel,artifact=deck['candidate_id'])
                conn.execute("UPDATE decks SET phase='reviewing',frozen_id=candidate_id,repair_count=0 WHERE presentation=?",(deck['presentation'],))
                event(conn,'deck.frozen',{'presentation':deck['presentation'],'artifact_id':deck['candidate_id'],'gate_id':gate['id']})
            return True
        if phase=='reviewing':
            jobs=self.store.rows("SELECT * FROM jobs WHERE kind='review' AND input_artifact_id=? AND round=?", (deck['frozen_id'],deck['review_round']))
            if len(jobs)!=5 or any(j['state']!='succeeded' for j in jobs):
                return False
            self._review_proof(deck)
            if not self.store.rows('SELECT id FROM findings WHERE artifact_id=?', (deck['frozen_id'],)):
                return self._set(deck, 'releasing')
            job=self._editor(deck, deck['candidate_id'], kind='revise', key=f"revise:{deck['frozen_id']}")
            return self._set(deck, 'revising', active_job_id=job)
        if phase=='releasing':
            self.publish(deck)
            return True
        return False

    def assemble(self, deck: dict, artifacts: list[dict]) -> str | None:
        """Claim once, stage outside DB, atomically register the immutable revision."""
        key='assemble:'+deck['presentation']+':'+','.join(a['id'] for a in artifacts)
        with self.store.transaction() as conn:
            job=self.service.ensure_job(conn,key=key,presentation=deck['presentation'],kind='assemble')
            row=conn.execute('SELECT state FROM jobs WHERE id=?',(job,)).fetchone()
            if row['state']=='succeeded':
                found=conn.execute('SELECT r.id FROM artifacts r JOIN attempts a ON a.id=r.attempt_id WHERE a.job_id=?',(job,)).fetchone()
                return found['id']
            if row['state']!='queued':
                return None
            attempt=uid('a')
            sequence=conn.execute('SELECT COALESCE(max(sequence),0)+1 FROM attempts WHERE job_id=?',(job,)).fetchone()[0]
            conn.execute("INSERT INTO attempts(id,job_id,sequence,state,started_at) VALUES(?,?,?,'running',?)",(attempt,job,sequence,utc_now()))
            conn.execute("UPDATE jobs SET state='running' WHERE id=?",(job,))
        work=self.task/'.mpres'/'work'/attempt/'output'
        created=None
        try:
            work.mkdir(parents=True)
            slides=[];ids=set();front=None
            for artifact in artifacts:
                self.quality.require_pass(artifact['id'],'source')
                source=inside(self.task,artifact['path']);parsed=parse_deck(source/'presentation.md')
                if front is not None and front!=parsed.frontmatter:
                    raise MPresError('Unit frontmatter conflicts; assembly cannot decide presentation semantics')
                front=parsed.frontmatter
                for slide in parsed.slides:
                    if slide.slide_id in ids:
                        raise MPresError(f'Duplicate slide ID across units: {slide.slide_id}')
                    ids.add(slide.slide_id);slides.append(slide.source.strip())
                for src in source.rglob('*'):
                    if not src.is_file() or src.name in {'presentation.md','theme.css'}:
                        continue
                    dst=work/src.relative_to(source)
                    if dst.exists():
                        if dst.read_bytes()!=src.read_bytes():
                            raise MPresError(f'Conflicting unit asset: {src.relative_to(source)}; use unit-namespaced assets')
                    else:
                        dst.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(src,dst)
            (work/'presentation.md').write_text('---\n'+yaml.safe_dump(front,allow_unicode=True,sort_keys=False)+'---\n'+'\n\n---\n\n'.join(slides)+'\n',encoding='utf-8')
            created=snapshot(self.task,work,fixed_theme=True)
            with self.store.transaction() as conn:
                self.service.confirmed(conn)
                conn.execute("INSERT INTO artifacts(id,attempt_id,presentation,path,created_at,origin) VALUES(?,?,?,?,?,'assembly')",(created[0],attempt,deck['presentation'],created[1],utc_now()))
                conn.execute("UPDATE attempts SET state='succeeded',finished_at=?,result_json=? WHERE id=?",(utc_now(),encode({'source_revisions':[a['id'] for a in artifacts]}),attempt))
                conn.execute("UPDATE jobs SET state='succeeded' WHERE id=?",(job,))
                event(conn,'deck.assembled',{'artifact_id':created[0],'inputs':[a['id'] for a in artifacts]},job)
            return created[0]
        except Exception as exc:
            if created:remove_tree(self.task/created[1])
            with self.store.transaction() as conn:
                conn.execute("UPDATE attempts SET state='failed',finished_at=?,error=? WHERE id=?",(utc_now(),str(exc),attempt))
                conn.execute("UPDATE jobs SET state='failed' WHERE id=?",(job,))
            raise

    def _review_proof(self, deck: dict) -> None:
        rows=self.store.rows("SELECT j.channel,a.session_id FROM jobs j JOIN attempts a ON a.job_id=j.id WHERE j.kind='review' AND j.input_artifact_id=? AND j.round=? AND j.state='succeeded' AND a.state='succeeded'", (deck['frozen_id'],deck['review_round']))
        if len(rows)!=5 or {r['channel'] for r in rows}!=set(CHANNELS) or len({r['session_id'] for r in rows})!=5:
            raise MPresError('Release requires five distinct successful full-deck reviewer sessions')
        for row in rows:
            conflicts=self.store.rows("SELECT 1 FROM participation WHERE session_id=? AND presentation=? AND kind IN ('write','edit','revise')",(row['session_id'],deck['presentation']))
            if conflicts:
                raise MPresError('Reviewer independence was violated')
        self.quality.require_pass(deck['frozen_id'])
        from .feedback import Feedback
        Feedback(self.task).require_current_reviews(deck['frozen_id'])

    def publish(self, deck: dict) -> dict:
        """Publish exact revisions; a repair never overwrites a historical PDF."""
        from .feedback import Feedback
        from .repairs import Repairs
        self._review_proof(deck)
        Feedback(self.task).require_author_clear(deck['candidate_id'])
        Repairs(self.task).require_clear(deck['candidate_id'])
        gate=self.quality.require_pass(deck['candidate_id'])
        if not gate['pdf_path']: raise MPresError('Successful full gate did not retain a PDF')
        for finding in self.store.rows('SELECT * FROM findings WHERE artifact_id=?',(deck['frozen_id'],)):
            resolution=json.loads(finding['resolution_json'] or '{}')
            if resolution.get('status')!='addressed' or resolution.get('artifact_id')!=deck['candidate_id']:
                raise MPresError('Every finding needs an author response bound to the exact release revision')
        source=inside(self.task,gate['pdf_path'])
        if not source.is_file():raise MPresError('Full-gate PDF is missing')
        case_id=deck.get('repair_case')
        revision=1
        if case_id:
            target_row=self.store.rows('SELECT * FROM repair_targets WHERE case_id=? AND presentation=?',(case_id,deck['presentation']))
            if not target_row: raise MPresError('Repair target is outside the approved campaign')
            revision=target_row[0]['release_revision']
        relative=f"deliverables/{deck['presentation']}.pdf" if not case_id else f"deliverables/{deck['presentation']}-r{revision:03d}.pdf"
        target=inside(self.task,relative)
        with self.store.transaction() as conn:
            cfg=self.service.confirmed(conn)
            old=conn.execute('SELECT * FROM release_versions WHERE presentation=? AND revision=?',(deck['presentation'],revision)).fetchone()
            if old and (old['artifact_id'],old['gate_id'],old['case_id'])!=(deck['candidate_id'],gate['id'],case_id):
                raise MPresError('A different revision already owns this delivery path')
            if not old:
                conn.execute("INSERT INTO release_versions VALUES(?,?,?,?,?,'prepared',?,NULL,?)",(deck['presentation'],revision,deck['candidate_id'],gate['id'],relative,utc_now(),case_id))
            if not case_id:
                previous=conn.execute('SELECT * FROM releases WHERE presentation=?',(deck['presentation'],)).fetchone()
                if previous and (previous['artifact_id'],previous['gate_id'])!=(deck['candidate_id'],gate['id']):
                    raise MPresError('A different revision already owns this delivery path')
                if not previous:
                    conn.execute("INSERT INTO releases VALUES(?,?,?,?,'prepared',?,NULL)",(deck['presentation'],deck['candidate_id'],gate['id'],relative,utc_now()))
        if old and old['state']=='committed':
            if not target.is_file() or target.read_bytes()!=source.read_bytes():
                raise MPresError('Committed delivery is missing or changed; never silently recreate it')
            return {'presentation':deck['presentation'],'pdf':str(target),'artifact_id':deck['candidate_id'],'revision':revision,'already_published':True}
        pending=self.task/'.mpres'/'publish'/uid('p')
        pending.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(source,pending);pending.chmod(0o444)
        try:
            if target.exists() and target.read_bytes()!=source.read_bytes():
                raise MPresError('Delivery path already contains different bytes; never overwrite a release')
            with self.store.transaction() as conn:
                self.service.confirmed(conn)
                current=conn.execute('SELECT * FROM decks WHERE presentation=?',(deck['presentation'],)).fetchone()
                if current['candidate_id']!=deck['candidate_id'] or current['phase'] not in {'releasing','delivered'} or current['repair_case']!=case_id:
                    raise MPresError('Deck changed before publication')
                self.quality.require_pass(deck['candidate_id'],conn=conn)
                try:os.link(pending,target)
                except FileExistsError:
                    if target.read_bytes()!=source.read_bytes():raise MPresError('Conflicting concurrent delivery')
                now=utc_now()
                conn.execute("UPDATE release_versions SET state='committed',committed_at=COALESCE(committed_at,?) WHERE presentation=? AND revision=?",(now,deck['presentation'],revision))
                if case_id:
                    previous=conn.execute('SELECT * FROM releases WHERE presentation=?',(deck['presentation'],)).fetchone()
                    baseline=conn.execute('SELECT * FROM repair_targets WHERE case_id=? AND presentation=?',(case_id,deck['presentation'])).fetchone()
                    if previous['artifact_id'] not in {baseline['baseline_artifact_id'],deck['candidate_id']}:
                        raise MPresError('The baseline release changed before repair publication')
                    conn.execute("UPDATE releases SET artifact_id=?,gate_id=?,pdf_path=?,state='committed',created_at=?,committed_at=? WHERE presentation=?",(deck['candidate_id'],gate['id'],relative,now,now,deck['presentation']))
                else:
                    conn.execute("UPDATE releases SET state='committed',committed_at=COALESCE(committed_at,?) WHERE presentation=?",(now,deck['presentation']))
                conn.execute("UPDATE decks SET phase='delivered',delivered_at=COALESCE(delivered_at,?) WHERE presentation=?",(now,deck['presentation']))
                if case_id:
                    conn.execute('UPDATE repair_targets SET delivered_at=? WHERE case_id=? AND presentation=?',(now,case_id,deck['presentation']))
                    if not conn.execute('SELECT 1 FROM repair_targets WHERE case_id=? AND delivered_at IS NULL',(case_id,)).fetchone():
                        case=conn.execute('SELECT * FROM repair_cases WHERE id=?',(case_id,)).fetchone()
                        conn.execute("UPDATE repair_cases SET state='completed' WHERE id=?",(case_id,))
                        conn.execute('UPDATE task SET status=?',(case['previous_task_status'],))
                        event(conn,'repair.completed',{'case_id':case_id})
                else:
                    settings=json.loads(cfg['settings_json'])
                    remaining=conn.execute("SELECT count(*) FROM decks WHERE phase<>'delivered'").fetchone()[0]
                    delivered=conn.execute("SELECT count(*) FROM decks WHERE phase='delivered'").fetchone()[0]
                    if not remaining:conn.execute("UPDATE task SET status='completed'")
                    elif settings['delivery']=='each' or (settings['delivery']=='pilot' and delivered==1):
                        conn.execute("UPDATE task SET status='paused'")
                        if not conn.execute("SELECT 1 FROM decisions WHERE kind='delivery-feedback' AND presentation=?",(deck['presentation'],)).fetchone():
                            conn.execute('INSERT INTO decisions(kind,presentation,detail_json) VALUES(?,?,?)',('delivery-feedback',deck['presentation'],encode({'pdf':relative})))
                event(conn,'deck.delivered',{'presentation':deck['presentation'],'artifact_id':deck['candidate_id'],'pdf':relative,'revision':revision,'repair_case':case_id})
        finally:
            pending.unlink(missing_ok=True)
        return {'presentation':deck['presentation'],'pdf':str(target),'artifact_id':deck['candidate_id'],'revision':revision}
