import json
from pathlib import Path
import pytest
from mpres.control.repairs import Repairs
from mpres.control.workflow import current_findings,validate_result
from mpres.control.service import Service
from mpres.util import MPresError
from test_relational_control import compact_root
from test_deck_workflow import native_double
from test_confirmed_repairs import completed,confirm


def proposal(s,r,targets=None,allow=False):
    repair=Repairs(s.task)
    opened=repair.open('Remove production narration within the confirmed teaching scope.',targets or ['p01'],
                       'user',mode='review-first',allow_slide_changes=allow)
    last=r.run(cycles=80,interval=0)
    assert last['status']=='awaiting_confirmation',last
    return repair,opened['case_id']


def test_review_original_first_then_author_without_second_review(compact_root,native_double):
    s,h,r=completed(compact_root,decks=2,delivery='pilot')
    old=s.store.rows("SELECT * FROM releases WHERE presentation='p01'")[0]
    src=s.store.rows('SELECT path FROM artifacts WHERE id=?',(old['artifact_id'],))[0]['path']
    before_pdf=(s.task/old['pdf_path']).read_bytes();before_md=(s.task/src/'presentation.md').read_bytes()
    repair,cid=proposal(s,r);confirm(repair,cid);start=len(h.calls)
    assert s.store.rows("SELECT phase FROM decks WHERE presentation='p01'")[0]['phase']=='reviewing'
    assert not s.store.rows("SELECT * FROM repair_jobs WHERE case_id=? AND stage='edit'",(cid,))
    last=r.run(cycles=100,interval=0)
    assert repair.case(cid)['state']=='completed',last
    packets=[c['packet'] for c in h.calls[start:] if c['operation']=='run']
    assert [p['kind'] for p in packets]==['review']*5+['revise']
    assert all(p['frozen_source_directory']==str(s.task/src) for p in packets[:5])
    assert all(not p['historical_release_evidence']['current_gate_approval'] for p in packets[:5])
    assert s.status()['status']=='paused'
    assert not any(c['packet']['presentation']=='p02' for c in h.calls)
    assert (s.task/old['pdf_path']).read_bytes()==before_pdf
    assert (s.task/src/'presentation.md').read_bytes()==before_md
    assert (s.task/'deliverables/p01/p01.md').is_file()


def test_historical_gate_not_confused_with_current_gate(compact_root,native_double,monkeypatch):
    s,h,r=completed(compact_root,decks=1);repair,cid=proposal(s,r);confirm(repair,cid)
    from mpres.control.quality import Quality
    baseline=repair.describe(cid)['targets'][0]['baseline_artifact_id'];real=Quality.require_pass
    def deny_old(self,aid,*a,**kw):
        if aid==baseline:raise MPresError('Old theme is not a new successful gate')
        return real(self,aid,*a,**kw)
    monkeypatch.setattr(Quality,'require_pass',deny_old)
    last=r.run(cycles=100,interval=0)
    assert repair.case(cid)['state']=='completed',last
    assert s.store.rows('SELECT artifact_id FROM releases')[0]['artifact_id']!=baseline


def test_missing_historical_pdf_rolls_back_entire_batch(compact_root,native_double):
    s,h,r=completed(compact_root,decks=2);repair,cid=proposal(s,r,['p01','p02']);repair.present(cid)
    before=s.store.rows('SELECT * FROM jobs')
    pdf=s.task/repair.describe(cid)['targets'][1]['baseline_pdf_path'];pdf.chmod(0o644);pdf.unlink()
    with pytest.raises(MPresError,match='missing'):repair.confirm(cid,1,'user')
    assert repair.case(cid)['state']=='presented'
    assert s.store.rows('SELECT * FROM jobs')==before
    assert not s.store.rows("SELECT * FROM decks WHERE phase<>'delivered'")


def test_changed_scope_requires_representing(compact_root,native_double):
    s,h,r=completed(compact_root,decks=1);repair,cid=proposal(s,r);repair.present(cid)
    with s.store.transaction() as c:c.execute('UPDATE repair_cases SET allow_slide_changes=1 WHERE id=?',(cid,))
    with pytest.raises(MPresError,match='exact expanded'):repair.confirm(cid,1,'user')
    confirm(repair,cid)
    assert repair.describe(cid)['allow_slide_changes']


def test_old_round_findings_do_not_contaminate_original_rescan(compact_root,native_double):
    s,h,r=completed(compact_root,decks=1);old=s.store.rows('SELECT * FROM decks')[0]
    j=s.store.rows("SELECT * FROM jobs WHERE kind='review' LIMIT 1")[0]
    with s.store.transaction() as c:
        c.execute('INSERT INTO findings(id,job_id,artifact_id,channel,detail_json) VALUES(?,?,?,?,?)',
                  ('old-finding',j['id'],old['candidate_id'],j['channel'],json.dumps({'message':'historical issue','slide_ids':['p01-l01-s1'],'severity':'minor'})))
    repair,cid=proposal(s,r);confirm(repair,cid)
    assert current_findings(s,s.store.rows('SELECT * FROM decks')[0])==[]
    last=r.run(cycles=100,interval=0)
    assert repair.case(cid)['state']=='completed',last
    assert s.store.rows("SELECT resolution_json FROM findings WHERE id='old-finding'")[0]['resolution_json'] is None


def test_late_review_cannot_submit_to_new_round(compact_root,native_double):
    s,h,r=completed(compact_root,decks=1)
    old=s.store.rows("SELECT * FROM jobs WHERE kind='review' LIMIT 1")[0]
    repair,cid=proposal(s,r);confirm(repair,cid)
    old['input_artifact_id']=s.store.rows('SELECT frozen_id FROM decks')[0]['frozen_id']
    with pytest.raises(MPresError,match='exact current frozen'):validate_result(s,old,{'findings':[]},None)


def change(sid,action='delete',target=None):
    return {'slide_id':sid,'action':action,'target_slide_id':target,'reason':'Remove duplicate explanation in confirmed scope.'}


@pytest.mark.parametrize('mapping,okay',[
    ([change('a')],True),([change('a','merge','b')],True),([],False),
    ([change('a'),change('a')],False),([change('b')],False),
    ([change('a','merge','missing')],False),([change('a','delete','b')],False),
    ([change('a','rename','b')],False)])
def test_exact_cumulative_deletion_map(mapping,okay):
    if okay:Repairs.validate_slide_changes({'allow_slide_changes':True},{'a','b'},{'b'},mapping)
    else:
        with pytest.raises(MPresError):Repairs.validate_slide_changes({'allow_slide_changes':True},{'a','b'},{'b'},mapping)


def test_no_silent_deletions_or_whole_deck_renaming():
    with pytest.raises(MPresError):Repairs.validate_slide_changes({}, {'a','b'},{'b'},[change('a')])
    with pytest.raises(MPresError):Repairs.validate_slide_changes({'allow_slide_changes':True},{'a','b'},{'c'},[change('a'),change('b')])
    Repairs.validate_slide_changes({'allow_slide_changes':True},{'a','b','c'},{'c'},[change('a','merge','c'),change('b')])


def test_schema_7_migration_preserves_existing_records(compact_root,native_double):
    s,h,r=completed(compact_root,decks=1)
    cfg=s.store.rows('SELECT * FROM configs');releases=s.store.rows('SELECT * FROM releases')
    c=s.store.connect();c.execute('ALTER TABLE repair_cases DROP COLUMN mode');c.execute('ALTER TABLE repair_cases DROP COLUMN allow_slide_changes');c.execute('PRAGMA user_version=7');c.close()
    s=Service(s.task);c=s.store.connect();assert c.execute('PRAGMA user_version').fetchone()[0]==8
    assert not c.execute('PRAGMA foreign_key_check').fetchall();c.close()
    assert s.store.rows('SELECT * FROM configs')==cfg
    assert s.store.rows('SELECT * FROM releases')==releases


def test_mode_and_scope_are_in_user_confirmation(compact_root,native_double):
    s,h,r=completed(compact_root,decks=1);repair,cid=proposal(s,r,allow=True)
    doc=repair.present(cid);assert doc['mode']=='review-first' and doc['allow_slide_changes']
    assert not doc['source_edits_authorized']
    for bad in ['auto',None]:
        with pytest.raises(MPresError):repair.open('Problem',['p01'],'user',mode=bad)


def test_author_merge_republishes_and_keeps_original_revision(compact_root,native_double):
    from mpres.marp_source import parse_deck
    from test_revision_quality import HEADER
    from test_deck_workflow import full_task,run_host
    from test_confirmed_repairs import RepairHost
    from feedback_fixtures import teaching_policy
    s=full_task(compact_root,decks=1,units=3);teaching_policy(s);h=RepairHost();r,last=run_host(s,h)
    assert s.status()['status']=='completed',last
    repair,cid=proposal(s,r,allow=True);confirm(repair,cid)
    def merge(req):
        out=h(req)
        if req['operation']=='run' and req['packet']['kind']=='revise':
            packet=req['packet'];source=Path(packet['writable_directory'])
            original=parse_deck(Path(packet['frozen_source_directory'])/'presentation.md');retained=original.slides[1]
            (source/'presentation.md').write_text(HEADER+'\n\n---\n\n'.join(slide.source for slide in original.slides[1:])+'\n')
            out['result']['slide_changes']=[change(original.slides[0].slide_id,'merge',retained.slide_id)]
            for row in out['result'].get('feedback_checks',[]):row['evidence']=[{'slide_id':retained.slide_id,'quote':retained.title}]
            for row in out['result'].get('repair_checks',[]):row['slide_ids']=[retained.slide_id]
        return out
    r.invoke=merge;last=r.run(cycles=100,interval=0)
    errors=s.store.rows("SELECT state,error FROM attempts WHERE state IN ('failed','uncertain')")
    assert repair.case(cid)['state']=='completed',(last,s.store.rows('SELECT * FROM decks'),errors)
    assert len(parse_deck(s.task/'deliverables/p01/p01.md').slides)==2
    assert len(s.store.rows("SELECT * FROM jobs WHERE kind='review' AND round=2"))==5
