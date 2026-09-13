"""Versioned user feedback and mandatory, bounded pre-work readbacks.

Stored only in SQLite. A receipt proves delivery/acknowledgement, not thought or
mathematical quality; exact slide excerpts and independent review supply evidence.
"""
from __future__ import annotations

import json
from pathlib import Path

from mpres.marp_source import parse_deck
from mpres.util import MPresError, safe_id, utc_now
from .store import Store, encode, event

BOILERPLATE = {'已阅读','已回顾','已检查','已完成','已解决','同上','不适用','不涉及','无','ok','done','read','reviewed','n/a','na'}


class Feedback:
    def __init__(self, task: Path):
        self.task = task.resolve()
        self.store = Store(self.task)

    def seed(self) -> None:
        """User-reported project defaults; no extra task document or model decision."""
        with self.store.transaction() as conn:
            for rule in json.loads(Path(__file__).with_name('teaching_feedback.json').read_text()):
                payload = {**rule, 'presentations': [], 'enabled': True}
                conn.execute('INSERT OR IGNORE INTO feedback_rules VALUES(?,1,?,?,?)',
                             (rule['id'], encode(payload), 'project-user-feedback', utc_now()))

    @staticmethod
    def effective(conn, presentation: str | None = None) -> list[dict]:
        rows = conn.execute('SELECT r.* FROM feedback_rules r WHERE version=(SELECT max(version) FROM feedback_rules WHERE id=r.id) ORDER BY r.id').fetchall()
        result = []
        for row in rows:
            data = json.loads(row['payload_json'])
            if not data['enabled']:
                continue
            from .planning import ancestors
            if presentation is not None and data['presentations'] and not set(ancestors(conn,presentation)).intersection(data['presentations']):
                continue
            result.append({**data, 'version': row['version']})
        return result

    def list(self, history: bool = False) -> list[dict]:
        self.seed()
        with self.store.transaction() as conn:
            if history:
                return [{**json.loads(r['payload_json']), 'version': r['version'], 'actor': r['actor'],
                         'created_at': r['created_at']} for r in conn.execute('SELECT * FROM feedback_rules ORDER BY id,version')]
            return self.effective(conn)

    def record(self, rule: dict, actor: str) -> dict:
        from .service import require_text
        self.seed()
        expected = {'id','report','expectation','possible_forms','acceptance','presentations','enabled'}
        if not isinstance(rule, dict) or set(rule) != expected:
            raise MPresError('Feedback requires id, report, expectation, possible_forms, acceptance, presentations, enabled')
        safe_id(require_text(rule['id'],'Feedback ID')); require_text(actor, 'User feedback attribution')
        for key in ('report','expectation','acceptance'):
            require_text(rule[key], key)
        if not isinstance(rule['possible_forms'], list) or not rule['possible_forms']:
            raise MPresError('Describe concrete possible forms of the problem')
        for form in rule['possible_forms']: require_text(form, 'Problem form')
        if type(rule['enabled']) is not bool or not isinstance(rule['presentations'], list):
            raise MPresError('Invalid feedback scope or enabled flag')
        for p in rule['presentations']: safe_id(p)
        with self.store.transaction() as conn:
            for p in rule['presentations']:
                if not conn.execute('SELECT 1 FROM plan_items WHERE presentation=?',(p,)).fetchone():
                    raise MPresError('Feedback presentation is outside the confirmed plan')
            old = conn.execute('SELECT * FROM feedback_rules WHERE id=? ORDER BY version DESC LIMIT 1',(rule['id'],)).fetchone()
            if old and old['payload_json'] == encode(rule):
                return {'id': rule['id'], 'version': old['version'], 'already_recorded': True}
            version = old['version'] + 1 if old else 1
            conn.execute('INSERT INTO feedback_rules VALUES(?,?,?,?,?)',(rule['id'],version,encode(rule),actor,utc_now()))
            event(conn,'feedback.recorded',{'id':rule['id'],'version':version,'actor':actor})
        return {'id':rule['id'],'version':version,'already_recorded':False}

    @staticmethod
    def reserve(conn, attempt: str, presentation: str) -> None:
        conn.execute('INSERT OR IGNORE INTO attempt_briefings(attempt_id,snapshot_json,created_at) VALUES(?,?,?)',
                     (attempt,encode(Feedback.effective(conn,presentation)),utc_now()))

    def briefing(self, attempt: str) -> dict:
        self.seed()
        with self.store.transaction() as conn:
            job=conn.execute('SELECT j.* FROM jobs j JOIN attempts a ON a.job_id=j.id WHERE a.id=?',(attempt,)).fetchone()
            if not job: raise MPresError('Unknown attempt')
            self.reserve(conn,attempt,job['presentation'])
            row=conn.execute('SELECT * FROM attempt_briefings WHERE attempt_id=?',(attempt,)).fetchone()
            return {**dict(row),'feedback':json.loads(row['snapshot_json']),
                    'acknowledged':row['acknowledgement_json'] is not None or json.loads(row['snapshot_json'])==[]}

    def acknowledge(self, attempt: str, readback: list, receipt: str) -> dict:
        from .service import require_text
        require_text(receipt,'Pre-work provider receipt')
        brief=self.briefing(attempt)
        if not isinstance(readback,list): raise MPresError('Pre-work readback must be a list')
        expected={(r['id'],r['version']) for r in brief['feedback']}; seen=set()
        for row in readback:
            if not isinstance(row,dict) or set(row)!={'id','version','approach'}:
                raise MPresError('Each readback requires id, version, approach')
            if type(row['version']) is not int or not isinstance(row['id'],str): raise MPresError('Readback identity/version types are invalid')
            key=(row['id'],row['version'])
            if key not in expected or key in seen: raise MPresError('Missing, duplicate or stale feedback readback')
            approach=require_text(row['approach'],'How this job will apply/check the feedback')
            if approach.strip(' .。！!').lower() in BOILERPLATE:
                raise MPresError('A read/done tick is not a concrete feedback approach')
            seen.add(key)
        if seen!=expected: raise MPresError('Read every historical feedback item before working')
        payload=encode(readback)
        with self.store.transaction() as conn:
            a=conn.execute('SELECT * FROM attempts WHERE id=?',(attempt,)).fetchone()
            row=conn.execute('SELECT * FROM attempt_briefings WHERE attempt_id=?',(attempt,)).fetchone()
            if row['acknowledgement_json'] is not None:
                if (row['acknowledgement_json'],row['receipt'])!=(payload,receipt):
                    raise MPresError('Pre-work readback is immutable')
                return {'acknowledged':True,'already_acknowledged':True}
            if a['state'] not in {'reserved','uncertain'} or a['provider_receipt']:
                raise MPresError('Readback must precede content execution; no retroactive acknowledgement')
            conn.execute('UPDATE attempt_briefings SET acknowledgement_json=?,receipt=? WHERE attempt_id=?',(payload,receipt,attempt))
            event(conn,'feedback.readback',{'attempt_id':attempt,'receipt':receipt},a['job_id'])
        return {'acknowledged':True,'already_acknowledged':False}

    @staticmethod
    def require_readback(conn, attempt: str) -> None:
        row=conn.execute('SELECT * FROM attempt_briefings WHERE attempt_id=?',(attempt,)).fetchone()
        if not row or (json.loads(row['snapshot_json']) and not row['acknowledgement_json']):
            raise MPresError('Historical feedback has not been acknowledged before execution')

    def validate_result(self, attempt: str, job: dict, result: dict, source: Path | None) -> None:
        brief=self.briefing(attempt)
        if not brief['acknowledged']: raise MPresError('Historical feedback must be acknowledged first')
        expected={(r['id'],r['version']) for r in brief['feedback']}
        if not expected: return
        checks=result.get('feedback_checks')
        if not isinstance(checks,list): raise MPresError('Result must address all historical feedback in feedback_checks')
        path=source/'presentation.md' if source else None
        if path is None and job['input_artifact_id']:
            artifact=self.store.rows('SELECT path FROM artifacts WHERE id=?',(job['input_artifact_id'],))[0]
            path=self.task/artifact['path']/'presentation.md'
        slides={s.slide_id:s.source for s in parse_deck(path).slides} if path else {}
        seen=set()
        from .service import require_text
        for check in checks:
            if not isinstance(check,dict) or set(check)-{'id','version','status','explanation','evidence','finding_refs'} or not {'id','version','status','explanation','evidence'}<=set(check):
                raise MPresError('Feedback check requires id, version, status, explanation, evidence')
            key=(check['id'],check['version'])
            if key not in expected or key in seen: raise MPresError('Unknown, duplicate or stale feedback check')
            seen.add(key)
            if check['status'] not in {'satisfied','issue','not_applicable'}: raise MPresError('Invalid feedback disposition')
            explanation=require_text(check['explanation'],'Concrete feedback disposition, not just read/done')
            if explanation.strip(' .。！!').lower() in BOILERPLATE:
                raise MPresError('Feedback requires a concrete disposition, not a completion tick')
            evidence=check['evidence']
            if not isinstance(evidence,list): raise MPresError('Feedback evidence must be a list')
            if check['status']=='satisfied' and not evidence:
                raise MPresError('Satisfied feedback needs actual slide excerpts')
            cited=set()
            if check.get('finding_refs'):
                from .review_data import referenced_findings
                if job['kind']!='review' or check['status']!='issue':
                    raise MPresError('Finding links are review-issue evidence only')
                cited.update(sid for f in referenced_findings(job,result,check['finding_refs']) for sid in f['slide_ids'])
            for e in evidence:
                if not isinstance(e,dict) or set(e)!={'slide_id','quote'}: raise MPresError('Evidence requires slide_id and quote')
                require_text(e['quote'],'Exact source excerpt')
                if e['slide_id'] not in slides or ' '.join(e['quote'].split()) not in ' '.join(slides[e['slide_id']].split()):
                    raise MPresError('Feedback evidence is not in the submitted/frozen source')
                cited.add(e['slide_id'])
            if job['kind']=='review' and check['status']=='issue':
                ids={i for f in result.get('findings',[]) for i in f.get('slide_ids',[])}
                if not cited or not cited & ids: raise MPresError('Feedback issue must also be a routed finding with matching slide evidence')
        if seen!=expected: raise MPresError('Feedback check omitted a historical user concern')

    def require_author_clear(self, artifact: str) -> None:
        rows=self.store.rows('SELECT a.result_json FROM attempts a JOIN artifacts r ON r.attempt_id=a.id WHERE r.id=?',(artifact,))
        if rows and rows[0]['result_json']:
            result=json.loads(rows[0]['result_json'])
            if any(c['status']=='issue' for c in result.get('feedback_checks',[])):
                raise MPresError('Author reports an unresolved historical-feedback issue; resolve evidence/semantics before freezing')

    def require_current_reviews(self, artifact: str, *, round_no: int | None = None) -> None:
        with self.store.transaction() as conn:
            p=conn.execute('SELECT presentation FROM artifacts WHERE id=?',(artifact,)).fetchone()
            expected=self.effective(conn,p['presentation'])
            rows=conn.execute("SELECT b.snapshot_json FROM jobs j JOIN attempts a ON a.job_id=j.id LEFT JOIN attempt_briefings b ON b.attempt_id=a.id WHERE j.kind='review' AND j.input_artifact_id=? AND a.state='succeeded' AND (? IS NULL OR j.round=?)",(artifact,round_no,round_no)).fetchall()
            if any(r['snapshot_json'] is None or json.loads(r['snapshot_json'])!=expected for r in rows):
                raise MPresError('User feedback changed after this review; start a newly confirmed rework/review cycle')
