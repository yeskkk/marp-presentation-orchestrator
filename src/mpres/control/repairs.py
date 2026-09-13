"""User-confirmed repair campaigns: expand first, edit only after exact approval.

One/batch targets are pinned committed releases. They re-enter the existing deck
workflow; history and original PDFs stay immutable. No new model coordinator.
"""
from __future__ import annotations

import json
from pathlib import Path

from jsonschema import Draft202012Validator

from mpres.marp_source import parse_deck
from mpres.util import MPresError, safe_id, utc_now
from .delivery import Delivery
from .feedback import Feedback
from .files import inside
from .service import Service, require_text, uid
from .store import encode, event


class Repairs:
    def __init__(self, task: Path):
        self.service=Service(task)
        self.task=self.service.task
        self.store=self.service.store

    def case(self, case_id: str) -> dict:
        rows=self.store.rows('SELECT * FROM repair_cases WHERE id=?',(case_id,))
        if not rows: raise MPresError('Unknown repair case')
        return rows[0]

    def open(self, report: str, presentations: list[str], actor: str, *,
             mode: str = 'edit-first', allow_slide_changes: bool = False) -> dict:
        require_text(report,'Verbatim user problem'); require_text(actor,'User request attribution')
        if mode not in {'edit-first','review-first'} or type(allow_slide_changes) is not bool:
            raise MPresError('Invalid repair mode or slide-change authorization')
        if not presentations or len(set(presentations))!=len(presentations):
            raise MPresError('Select one or more distinct delivered presentation IDs explicitly')
        for p in presentations: safe_id(p)
        case_id=uid('repair')
        with self.store.transaction() as conn:
            self.service.confirmed(conn)
            if conn.execute('SELECT status FROM task').fetchone()[0] not in {'paused','completed'}:
                raise MPresError('Open repair mode at a delivery pause or after completion, not over live production')
            targets=[]
            for p in presentations:
                row=conn.execute("SELECT r.*,d.phase FROM releases r JOIN decks d ON d.presentation=r.presentation WHERE r.presentation=? AND r.state='committed'",(p,)).fetchone()
                if not row or row['phase']!='delivered':
                    raise MPresError('Repair targets must be committed, currently delivered presentations')
                revision=conn.execute('SELECT coalesce(max(revision),0)+1 FROM release_versions WHERE presentation=?',(p,)).fetchone()[0]
                targets.append((p,row['artifact_id'],row['pdf_path'],max(2,revision)))
            conn.execute("INSERT INTO repair_cases(id,report,requested_by,created_at,state,mode,allow_slide_changes) VALUES(?,?,?,?,'diagnosing',?,?)",
                         (case_id,report,actor,utc_now(),mode,int(allow_slide_changes)))
            for p,artifact,pdf,revision in targets:
                conn.execute('INSERT INTO repair_targets(case_id,presentation,baseline_artifact_id,baseline_pdf_path,release_revision) VALUES(?,?,?,?,?)',
                             (case_id,p,artifact,pdf,revision))
            first=targets[0]
            job=self.service.ensure_job(conn,key='repair-proposal:'+case_id,presentation=first[0],kind='diagnose',artifact=first[1])
            conn.execute('INSERT INTO repair_jobs VALUES(?,?,?)',(job,case_id,'proposal'))
            event(conn,'repair.requested',{'case_id':case_id,'presentations':presentations,'actor':actor},job)
        return {**self.describe(case_id),'proposal_job_id':job,'source_edits_authorized':False}

    @staticmethod
    def proposal_job(conn, job_id: str) -> bool:
        return conn.execute("SELECT 1 FROM repair_jobs j JOIN repair_cases c ON c.id=j.case_id WHERE j.job_id=? AND j.stage='proposal' AND c.state='diagnosing'",(job_id,)).fetchone() is not None

    def pending_presentations(self) -> set[str]:
        return {r['presentation'] for r in self.store.rows("SELECT j.presentation FROM jobs j JOIN repair_jobs r ON r.job_id=j.id JOIN repair_cases c ON c.id=r.case_id WHERE r.stage='proposal' AND c.state='diagnosing' AND j.state IN ('queued','running')")}

    def active(self) -> dict | None:
        rows=self.store.rows("SELECT * FROM repair_cases WHERE state='running' ORDER BY created_at")
        return rows[0] if rows else None

    def describe(self, case_id: str) -> dict:
        case=self.case(case_id)
        inspected=self.store.rows("SELECT j.presentation,j.input_artifact_id FROM jobs j JOIN repair_jobs r ON r.job_id=j.id WHERE r.case_id=? AND r.stage='proposal'",(case_id,))
        return {'case_id':case_id,'state':case['state'],'report':case['report'],
                'mode':case['mode'],'allow_slide_changes':bool(case['allow_slide_changes']),
                'proposal_version':case['proposal_version'],
                'targets':self.store.rows('SELECT presentation,baseline_artifact_id,baseline_pdf_path,release_revision FROM repair_targets WHERE case_id=? ORDER BY presentation',(case_id,)),
                'expansion':json.loads(case['proposal_json']) if case['proposal_json'] else None,
                'inspection_boundary':{'actually_inspected':inspected, 'note':'Only this source is inspected during expansion. Other targets remain uninspected until approval; possible forms are hypotheses, not established findings.'},
                'source_edits_authorized':case['state'] in {'running','completed'}}

    def validate_expansion(self, expansion: dict, first_artifact: str) -> None:
        from .semantic import schema
        errors=list(Draft202012Validator(schema('diagnosis-result')['properties']['expansion']).iter_errors(expansion))
        if errors: raise MPresError('Repair expansion: '+errors[0].message)
        artifact=self.store.rows('SELECT path FROM artifacts WHERE id=?',(first_artifact,))[0]
        ids={s.slide_id for s in parse_deck(self.task/artifact['path']/'presentation.md').slides}
        seen=set()
        for form in expansion['variants']+expansion['related_problems']:
            safe_id(form['id'])
            if form['id'] in seen: raise MPresError('Repair problem-form IDs must be distinct')
            seen.add(form['id'])
            if set(form['slide_ids'])-ids: raise MPresError('Observed proposal evidence must belong to the actually inspected source')
            if form['evidence_status']=='observed' and not form['slide_ids']:
                raise MPresError('An observed problem needs actual slide evidence; mark uninspected possibilities possible')

    def accept_proposal(self, conn, job: dict, result: dict) -> None:
        linked=conn.execute("SELECT * FROM repair_jobs WHERE job_id=? AND stage='proposal'",(job['id'],)).fetchone()
        if not linked: return
        case=conn.execute('SELECT * FROM repair_cases WHERE id=?',(linked['case_id'],)).fetchone()
        if case['state']!='diagnosing': raise MPresError('Repair proposal is no longer awaiting this diagnosis')
        conn.execute("UPDATE repair_cases SET proposal_json=?,proposal_version=proposal_version+1,state='proposed',presented_json=NULL WHERE id=?",(encode(result['expansion']),case['id']))
        event(conn,'repair.proposed',{'case_id':case['id']},job['id'])

    def amend(self, case_id: str, expansion: dict, actor: str) -> dict:
        require_text(actor,'Proposal editor attribution')
        case=self.case(case_id)
        if case['state'] not in {'proposed','presented'}: raise MPresError('Only an unconfirmed proposal may be amended')
        job=self.store.rows("SELECT j.* FROM jobs j JOIN repair_jobs r ON r.job_id=j.id WHERE r.case_id=? AND r.stage='proposal'",(case_id,))[0]
        self.validate_expansion(expansion,job['input_artifact_id'])
        with self.store.transaction() as conn:
            row=conn.execute('SELECT * FROM repair_cases WHERE id=?',(case_id,)).fetchone()
            if row['state'] not in {'proposed','presented'} or row['proposal_version']!=case['proposal_version']:
                raise MPresError('Repair proposal changed concurrently')
            conn.execute("UPDATE repair_cases SET proposal_json=?,proposal_version=proposal_version+1,state='proposed',presented_json=NULL WHERE id=?",(encode(expansion),case_id))
            event(conn,'repair.proposal_amended',{'case_id':case_id,'actor':actor})
        return self.describe(case_id)

    def present(self, case_id: str) -> dict:
        doc=self.describe(case_id)
        if doc['state'] not in {'proposed','presented'}: raise MPresError('Finish problem expansion before presenting a repair scope')
        # State and authorization are output labels, not content in the approval snapshot.
        exact={k:v for k,v in doc.items() if k not in {'state','source_edits_authorized'}}
        with self.store.transaction() as conn:
            row=conn.execute('SELECT * FROM repair_cases WHERE id=?',(case_id,)).fetchone()
            if row['proposal_version']!=doc['proposal_version'] or row['state'] not in {'proposed','presented'}:
                raise MPresError('Repair proposal changed while presenting')
            conn.execute("UPDATE repair_cases SET state='presented',presented_json=? WHERE id=?",(encode(exact),case_id))
        return {**exact,'requires_explicit_user_confirmation':True,'source_edits_authorized':False}

    def _release_evidence(self, target: dict, conn=None) -> dict:
        query = """SELECT a.path,r.gate_id FROM release_versions r JOIN artifacts a
                   ON a.id=r.artifact_id WHERE r.presentation=? AND r.artifact_id=?
                   AND r.pdf_path=? AND r.state='committed'"""
        args=(target['presentation'],target['baseline_artifact_id'],target['baseline_pdf_path'])
        rows=[dict(row) for row in conn.execute(query,args)] if conn else self.store.rows(query,args)
        if not rows: raise MPresError('Historical review requires exact committed release evidence')
        source=inside(self.task,rows[0]['path'])
        markdown=inside(source,'presentation.md');pdf=inside(self.task,target['baseline_pdf_path'])
        if not markdown.is_file() or not pdf.is_file():
            raise MPresError('Historical review source or PDF evidence is missing')
        with pdf.open('rb') as stream:
            if stream.read(5)!=b'%PDF-': raise MPresError('Historical PDF evidence is invalid')
        return {'artifact_id':target['baseline_artifact_id'],'source_directory':str(source),
                'pdf':str(pdf),'historical_release':True,'historical_gate_id':rows[0]['gate_id'],
                'current_gate_approval':False,'new_revision_must_pass_current_gates':True}

    def historical_review(self, deck: dict) -> dict | None:
        if not deck.get('repair_case'): return None
        case=self.case(deck['repair_case'])
        if case['mode']!='review-first' or case['state'] not in {'running','completed'}: return None
        targets=self.store.rows('SELECT * FROM repair_targets WHERE case_id=? AND presentation=?',
                                (case['id'],deck['presentation']))
        if not targets or targets[0]['baseline_artifact_id']!=deck['frozen_id']: return None
        return self._release_evidence(targets[0])

    def confirm(self, case_id: str, version: int, actor: str) -> dict:
        require_text(actor,'Explicit user confirmation attribution')
        if type(version) is not int or version<1: raise MPresError('Proposal version must be a positive integer')
        doc=self.describe(case_id)
        exact={k:v for k,v in doc.items() if k not in {'state','source_edits_authorized'}}
        with self.store.transaction() as conn:
            self.service.confirmed(conn)
            case=conn.execute('SELECT * FROM repair_cases WHERE id=?',(case_id,)).fetchone()
            if case['state'] in {'running','completed'} and version==case['proposal_version']:
                return {'case_id':case_id,'already_confirmed':True}
            if case['state']!='presented' or version!=case['proposal_version'] or case['presented_json']!=encode(exact):
                raise MPresError('The exact expanded problem, version and target revisions must be presented and confirmed')
            if conn.execute("SELECT 1 FROM repair_cases WHERE state='running'").fetchone():
                raise MPresError('Another repair campaign is still running')
            state=conn.execute('SELECT status FROM task').fetchone()[0]
            if state not in {'paused','completed'}: raise MPresError('Do not switch live production into repair mode')
            targets=conn.execute('SELECT * FROM repair_targets WHERE case_id=? ORDER BY presentation',(case_id,)).fetchall()
            for target in targets:
                old=conn.execute('SELECT * FROM releases WHERE presentation=?',(target['presentation'],)).fetchone()
                d=conn.execute('SELECT * FROM decks WHERE presentation=?',(target['presentation'],)).fetchone()
                if old['state']!='committed' or old['artifact_id']!=target['baseline_artifact_id'] or old['pdf_path']!=target['baseline_pdf_path'] or d['phase']!='delivered':
                    raise MPresError('A selected release changed since the proposal; open a new case')
                if conn.execute("SELECT 1 FROM attempts a JOIN jobs j ON j.id=a.job_id WHERE j.presentation=? AND a.state IN ('reserved','running','uncertain')",(target['presentation'],)).fetchone():
                    raise MPresError('A selected deck still has an outstanding execution')
            if case['mode']=='review-first':
                for target in targets: self._release_evidence(dict(target),conn)
            expansion=json.loads(case['proposal_json'])
            rule={'id':case_id,'report':case['report'],'expectation':expansion['problem_definition'],
                  'possible_forms':[f['description'] for f in expansion['variants']+expansion['related_problems']],
                  'acceptance':'\n'.join(expansion['acceptance_criteria']),
                  'presentations':[t['presentation'] for t in targets],'enabled':True}
            conn.execute('INSERT INTO feedback_rules VALUES(?,1,?,?,?)',(case_id,encode(rule),actor,utc_now()))
            for target in targets:
                p=target['presentation']
                if case['mode']=='review-first':
                    round_no=conn.execute('SELECT review_round FROM decks WHERE presentation=?',(p,)).fetchone()[0]+1
                    from .service import CHANNELS
                    for channel in CHANNELS:
                        self.service.ensure_job(conn,key=f'repair-review:{case_id}:{p}:{channel}',
                            presentation=p,kind='review',round=round_no,channel=channel,
                            artifact=target['baseline_artifact_id'])
                    conn.execute("UPDATE decks SET phase='reviewing',candidate_id=?,frozen_id=?,active_job_id=NULL,repair_count=0,blocked_from=NULL,block_reason=NULL,delivered_at=NULL,repair_case=?,review_round=? WHERE presentation=?",
                                 (target['baseline_artifact_id'],target['baseline_artifact_id'],case_id,round_no,p))
                else:
                    job=self.service.ensure_job(conn,key=f'repair-edit:{case_id}:{p}',presentation=p,kind='edit',artifact=target['baseline_artifact_id'])
                    conn.execute('INSERT INTO repair_jobs VALUES(?,?,?)',(job,case_id,'edit'))
                    conn.execute("UPDATE decks SET phase='editing',candidate_id=?,frozen_id=NULL,active_job_id=?,repair_count=0,blocked_from=NULL,block_reason=NULL,delivered_at=NULL,repair_case=?,review_round=review_round+1 WHERE presentation=?",(target['baseline_artifact_id'],job,case_id,p))
            conn.execute("UPDATE repair_cases SET state='running',confirmed_by=?,confirmed_at=?,previous_task_status=? WHERE id=?",(actor,utc_now(),state,case_id))
            conn.execute("UPDATE task SET status='running'")
            event(conn,'repair.confirmed',{'case_id':case_id,'proposal_version':version,'actor':actor})
        return {**self.describe(case_id),'already_confirmed':False}

    def cancel(self, case_id: str, actor: str, note: str) -> dict:
        require_text(actor,'User cancellation');require_text(note,'Cancellation note')
        with self.store.transaction() as conn:
            row=conn.execute('SELECT * FROM repair_cases WHERE id=?',(case_id,)).fetchone()
            if not row or row['state'] not in {'diagnosing','proposed','presented'}:
                raise MPresError('Only an unconfirmed case may be cancelled here')
            if conn.execute("SELECT 1 FROM attempts a JOIN repair_jobs r ON r.job_id=a.job_id WHERE r.case_id=? AND a.state IN ('reserved','running','uncertain')",(case_id,)).fetchone():
                raise MPresError('Reconcile the outstanding diagnostic execution before cancellation')
            conn.execute("UPDATE jobs SET state='blocked' WHERE id IN (SELECT job_id FROM repair_jobs WHERE case_id=?) AND state='queued'",(case_id,))
            conn.execute("UPDATE repair_cases SET state='cancelled' WHERE id=?",(case_id,))
            event(conn,'repair.cancelled',{'case_id':case_id,'actor':actor,'note':note})
        return self.describe(case_id)

    def context(self, job: dict) -> dict | None:
        linked=self.store.rows('SELECT * FROM repair_jobs WHERE job_id=?',(job['id'],))
        if linked:
            return self.describe(linked[0]['case_id'])
        rows=self.store.rows('SELECT repair_case FROM decks WHERE presentation=?',(job['presentation'],))
        if rows and rows[0]['repair_case']:
            case=self.case(rows[0]['repair_case'])
            if case['state']=='running': return self.describe(case['id'])
        return None

    def validate_result(self, job: dict, result: dict, source: Path | None) -> None:
        context=self.context(job)
        if not context: return
        if job['kind']=='diagnose':
            self.validate_expansion(result.get('expansion'),job['input_artifact_id'])
            return
        if not context['source_edits_authorized']:
            raise MPresError('Repair scope is not confirmed')
        forms=context['expansion']['variants']+context['expansion']['related_problems']
        expected={r['id'] for r in forms};seen=set()
        checks=result.get('repair_checks')
        if not isinstance(checks,list): raise MPresError('Repair must address every confirmed problem form in repair_checks')
        target=next(t for t in context['targets'] if t['presentation']==job['presentation'])
        original=self.store.rows('SELECT path FROM artifacts WHERE id=?',(target['baseline_artifact_id'],))[0]
        baseline={s.slide_id for s in parse_deck(self.task/original['path']/'presentation.md').slides}
        if source:
            parsed=parse_deck(source/'presentation.md')
            ids={s.slide_id for s in parsed.slides}
            self.validate_slide_changes(context,baseline,ids,result.get('slide_changes',[]))
        else:
            a=self.store.rows('SELECT path FROM artifacts WHERE id=?',(job['input_artifact_id'],))[0]
            ids={s.slide_id for s in parse_deck(self.task/a['path']/'presentation.md').slides}
        finding_ids={i for f in result.get('findings',[]) for i in f.get('slide_ids',[])}
        for row in checks:
            if not isinstance(row,dict) or set(row)-{'problem_id','status','explanation','slide_ids','finding_refs'} or not {'problem_id','status','explanation','slide_ids'}<=set(row): raise MPresError('Invalid repair check')
            if row['problem_id'] not in expected or row['problem_id'] in seen: raise MPresError('Unknown or repeated confirmed problem form')
            seen.add(row['problem_id']);require_text(row['explanation'],'Specific repair disposition')
            if row['status'] not in {'addressed','not_found','needs_decision'} or not isinstance(row['slide_ids'],list): raise MPresError('Invalid repair check status/evidence')
            if set(row['slide_ids'])-ids: raise MPresError('Repair evidence must cite this exact source')
            linked=[]
            if row.get('finding_refs'):
                from .review_data import referenced_findings
                if job['kind']!='review' or row['status']!='needs_decision':
                    raise MPresError('Finding links require a real review problem')
                linked=[sid for f in referenced_findings(job,result,row['finding_refs']) for sid in f['slide_ids']]
            if row['status'] in {'addressed','needs_decision'} and not (row['slide_ids'] or linked): raise MPresError('Repair action/issue needs concrete slide evidence')
            if job['kind']=='review' and row['status']=='needs_decision' and not set(row['slide_ids']+linked)&finding_ids: raise MPresError('Unresolved repair issue must be a routed finding')
        if seen!=expected: raise MPresError('Repair result omitted confirmed possible/similar problem forms')

    @staticmethod
    def validate_slide_changes(context: dict, baseline: set[str], current: set[str], changes: list) -> None:
        missing=baseline-current
        if not context.get('allow_slide_changes'):
            if missing or changes:
                raise MPresError('Repair must preserve original slide IDs; deletion/merge needs explicit user scope')
            return
        if not isinstance(changes,list): raise MPresError('slide_changes must be a list')
        if not baseline & current:
            raise MPresError('Repair cannot remove or rename every original slide; retain stable IDs')
        seen=set()
        for row in changes:
            if not isinstance(row,dict) or set(row)!={'slide_id','action','target_slide_id','reason'}:
                raise MPresError('Each slide change requires slide_id, action, target_slide_id, reason')
            sid=row['slide_id']
            if not isinstance(sid,str) or sid not in missing or sid in seen:
                raise MPresError('Slide change must identify each missing original slide exactly once')
            seen.add(sid);require_text(row['reason'],'Specific slide-change reason')
            if row['action']=='delete':
                if row['target_slide_id'] is not None: raise MPresError('Deleted slide has no merge target')
            elif row['action']=='merge':
                if not isinstance(row['target_slide_id'],str) or row['target_slide_id'] not in baseline & current:
                    raise MPresError('Merge target must be a retained original slide')
            else: raise MPresError('Slide-change action must be delete or merge')
        if seen!=missing: raise MPresError('Every missing original slide needs a cumulative deletion/merge mapping')

    def require_clear(self, artifact: str) -> None:
        rows=self.store.rows('SELECT a.result_json FROM artifacts r JOIN attempts a ON a.id=r.attempt_id WHERE r.id=?',(artifact,))
        if rows and rows[0]['result_json']:
            r=json.loads(rows[0]['result_json'])
            if any(x['status']=='needs_decision' for x in r.get('repair_checks',[])):
                raise MPresError('Repair author needs a semantic decision; do not publish unresolved repairs')

    def status(self) -> dict:
        cases=[self.describe(r['id']) for r in self.store.rows('SELECT id FROM repair_cases ORDER BY created_at,rowid')]
        for c in cases:
            if c['state']=='completed': c['delivery_package']=RepairDelivery(self.task,c['case_id']).status()
        return {'cases':cases,'awaiting_confirmation':[c for c in cases if c['state'] in {'proposed','presented'}],
                'active':[c for c in cases if c['state']=='running']}


class RepairDelivery(Delivery):
    """A selected view, not a second set of generated files or a repair ZIP."""
    def __init__(self, task: Path, case_id: str):
        super().__init__(task)
        self.case_id=safe_id(case_id)

    def _releases(self, conn=None) -> list[dict]:
        query="""SELECT r.presentation,r.artifact_id,r.gate_id,r.pdf_path,
                 a.path AS source_path,g.pdf_path AS checked_pdf_path
                 FROM release_versions r JOIN artifacts a ON a.id=r.artifact_id
                 JOIN gate_runs g ON g.id=r.gate_id
                 WHERE r.state='committed' AND r.case_id=? ORDER BY r.presentation"""
        return [dict(r) for r in conn.execute(query,(self.case_id,))] if conn else self.store.rows(query,(self.case_id,))

    def status(self) -> dict:
        selected=self._releases()
        current={r['presentation']:r for r in Delivery(self.task)._releases()}
        if any(current.get(r['presentation'])!=r for r in selected):
            return {'state':'superseded','format':'directory','case_id':self.case_id,
                    'presentations':[r['presentation'] for r in selected],
                    'history':[{'presentation':r['presentation'],'pdf':str(self.task/r['pdf_path']),
                                'source':str(self.task/r['source_path'])} for r in selected]}
        return super().status()

    def materialize(self) -> dict:
        current=self.status()
        if current['state']=='superseded':
            return current
        return super().materialize()
