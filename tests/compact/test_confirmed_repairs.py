from __future__ import annotations

import json
from pathlib import Path

import pytest

from mpres.control.feedback import Feedback
from mpres.control.repairs import Repairs, RepairDelivery
from mpres.control.runner import Runner
from mpres.control.workflow import Workflow
from mpres.marp_source import parse_deck
from mpres.util import MPresError
from feedback_fixtures import teaching_policy
from test_relational_control import compact_root
from test_deck_workflow import full_task, native_double, run_host
from test_historical_feedback import FeedbackHost


class RepairHost(FeedbackHost):
    """Protocol fixture only. Never presented as actual mathematical quality."""
    def __call__(self,req):
        if req['operation']=='run' and req['packet']['kind']=='diagnose':
            packet=req['packet'];first=parse_deck(Path(packet['frozen_source_directory'])/'presentation.md').slides[0]
            from feedback_fixtures import checks
            self.calls.append(req)
            return {'runtime':req['runtime'],'receipt':'diagnostic:'+req['attempt_id'],
                    'result':{'summary':'Expand terminology drift and related omissions before any edit.',
                              'hypotheses':[],'confidence':'medium','affected_slide_ids':[],
                              'recommended_action':'full_review',
                              'expansion':{
                                  'problem_definition':'Restore precise terminology without removing useful explanations.',
                                  'variants':[{'id':'informal-renaming','description':'Informal nickname replaces the mathematical term.',
                                               'detection':'Compare names against definitions and notation.',
                                               'correction':'Restore the standard term; keep explanatory language as a labeled analogy.',
                                               'evidence_status':'possible','slide_ids':[]}],
                                  'related_problems':[{'id':'missing-conditions','description':'Omitted assumptions make the named concept ambiguous.',
                                                       'detection':'Check domain, dimensions and assumptions.',
                                                       'correction':'State assumptions next to the definition.',
                                                       'evidence_status':'possible','slide_ids':[]}],
                                  'non_goals':['Do not rewrite unrelated valid proofs or change course scope.'],
                                  'acceptance_criteria':['Terms and assumptions appear explicitly, with stable slide IDs.'],
                                  'source_needs':[]},
                              'feedback_checks':checks(packet['historical_feedback'],first.slide_id,first.title)},
                    'usage':[{'call_id':'diagnostic','counters':{'input_tokens':180,'cached_input_tokens':120,'output_tokens':80,'reasoning_tokens':0,'total_tokens':260}}]}
        response=super().__call__(req)
        if req['operation']=='run' and req['packet'].get('repair_scope'):
            packet=req['packet'];kind=packet['kind'];scope=packet['repair_scope']
            path=Path(packet['frozen_source_directory']) if kind=='review' else Path(packet['writable_directory'])
            if kind in {'edit','revise'}:
                md=path/'presentation.md'
                # Materialize a genuine changed source, not a self-declared repair.
                text=md.read_text()
                if 'Coordinate vector' not in text:
                    md.write_text(text+'\n\nCoordinate vector: an ordered list of coordinates in a specified basis.\n')
            first=parse_deck(path/'presentation.md').slides[0]
            response['result']['repair_checks']=[
                {'problem_id':f['id'],'status':'addressed','explanation':'Explicitly checked the confirmed form; fixture-specific edit is visible.',
                 'slide_ids':[first.slide_id]}
                for f in scope['expansion']['variants']+scope['expansion']['related_problems']]
        return response


def completed(root, *, decks=2, delivery='all'):
    s=full_task(root,decks=decks,units=2,delivery=delivery)
    teaching_policy(s);h=RepairHost();runner,last=run_host(s,h)
    assert s.status()['status'] in {'completed','paused'},last
    return s,h,runner


def propose(s,runner,targets):
    repair=Repairs(s.task)
    case=repair.open('数学概念被随意起名字，请修正规范术语及相关问题。',targets,'user')
    last=runner.run(cycles=80,interval=0)
    assert last['status']=='awaiting_confirmation',last
    assert repair.case(case['case_id'])['state']=='proposed'
    return repair,case['case_id']


def confirm(repair,cid):
    doc=repair.present(cid)
    return repair.confirm(cid,doc['proposal_version'],'user explicitly confirmed')


def test_expansion_precedes_confirmation_and_never_edits(compact_root,native_double):
    s,h,r=completed(compact_root,decks=1)
    old=s.store.rows('SELECT * FROM releases');before={p:p.read_bytes() for p in (s.task/'deliverables').glob('*.pdf')}
    artifacts=s.store.rows('SELECT * FROM artifacts');oldcalls=len(h.calls)
    repair,cid=propose(s,r,['p01'])
    doc=repair.describe(cid)
    assert doc['expansion']['variants'] and doc['expansion']['related_problems'] and doc['expansion']['non_goals']
    assert not doc['source_edits_authorized']
    assert s.store.rows('SELECT * FROM releases')==old
    assert s.store.rows('SELECT * FROM artifacts')==artifacts
    assert all(p.read_bytes()==data for p,data in before.items())
    assert all(c['packet']['kind']=='diagnose' for c in h.calls[oldcalls:])
    assert not s.store.rows("SELECT * FROM repair_jobs WHERE stage='edit'")


def test_cannot_confirm_before_presenting_or_wrong_version(compact_root,native_double):
    s,h,r=completed(compact_root,decks=1);repair,cid=propose(s,r,['p01'])
    with pytest.raises(MPresError,match='presented'):repair.confirm(cid,1,'user')
    repair.present(cid)
    with pytest.raises(MPresError):repair.confirm(cid,2,'user')
    assert not s.store.rows("SELECT * FROM repair_jobs WHERE stage='edit'")


def test_amending_invalidates_previous_confirmation_snapshot(compact_root,native_double):
    s,h,r=completed(compact_root,decks=1);repair,cid=propose(s,r,['p01'])
    doc=repair.present(cid);exp=doc['expansion'];exp['non_goals'].append('Do not rename the variable x.')
    repair.amend(cid,exp,'planner after user feedback')
    with pytest.raises(MPresError):repair.confirm(cid,doc['proposal_version'],'user')
    confirm(repair,cid)
    assert repair.case(cid)['proposal_version']==2


def test_single_repair_preserves_unselected_deck_and_original_pdf(compact_root,native_double):
    s,h,r=completed(compact_root,decks=2)
    original=s.store.rows('SELECT * FROM releases ORDER BY presentation')
    bytes_before={x['pdf_path']:(s.task/x['pdf_path']).read_bytes() for x in original}
    config=s.store.rows('SELECT * FROM configs');repair,cid=propose(s,r,['p01']);confirm(repair,cid)
    last=r.run(cycles=100,interval=0)
    assert repair.case(cid)['state']=='completed',last
    current=s.store.rows('SELECT * FROM releases ORDER BY presentation')
    assert current[0]['artifact_id']!=original[0]['artifact_id']
    assert current[0]['pdf_path']=='.mpres/releases/p01/r002/p01.pdf'
    assert current[1]==original[1]
    assert all((s.task/path).read_bytes()==data for path,data in bytes_before.items())
    assert s.store.rows('SELECT * FROM configs')==config
    assert len(s.store.rows("SELECT * FROM release_versions WHERE presentation='p01' AND state='committed'"))==2
    assert len(s.store.rows("SELECT * FROM jobs WHERE kind='review' AND presentation='p01' AND round=2 AND state='succeeded'"))==5
    assert s.status()['status']=='completed'


def test_batch_direct_view_selects_requested_pairs_without_extra_archive(compact_root,native_double):
    s,h,r=completed(compact_root,decks=3);repair,cid=propose(s,r,['p01','p03']);confirm(repair,cid)
    last=r.run(cycles=120,interval=0)
    assert repair.case(cid)['state']=='completed',last
    package=RepairDelivery(s.task,cid).materialize();path=Path(package['path'])
    assert package['presentations']==['p01','p03']
    assert [e['presentation'] for e in package['entries']]==['p01','p03']
    for p in ['p01','p03']:
        release=s.store.rows('SELECT r.*,a.path FROM releases r JOIN artifacts a ON a.id=r.artifact_id WHERE r.presentation=?',(p,))[0]
        assert (path/p/f'{p}.md').read_bytes()==(s.task/release['path']/'presentation.md').read_bytes()
        assert (path/p/f'{p}.pdf').is_file()
    assert (path/'p02/p02.md').is_file()  # Not a target: its existing directory is preserved.
    assert not list(path.rglob('*.zip'))
    count=len(h.calls);again=RepairDelivery(s.task,cid).materialize()
    assert again['already_materialized'] and len(h.calls)==count
    assert all(x['state']=='ready' for x in Workflow(s.task).advance()['repair_packages'])


def test_repeat_repair_creates_third_revision_not_overwrite(compact_root,native_double):
    s,h,r=completed(compact_root,decks=1)
    for revision in [2,3]:
        repair,cid=propose(s,r,['p01']);confirm(repair,cid);last=r.run(cycles=100,interval=0)
        assert repair.case(cid)['state']=='completed',last
        assert (s.task/f'.mpres/releases/p01/r{revision:03d}/p01.pdf').is_file()
    assert len(s.store.rows("SELECT * FROM release_versions WHERE presentation='p01'"))==3
    history=repair.status()['cases']
    assert history[0]['delivery_package']['state']=='superseded'
    assert history[-1]['delivery_package']['state']=='ready'
    assert (s.task/'.mpres/releases/p01/r001/p01.pdf').is_file()


def test_pilot_repair_restores_pause_does_not_start_next_deck(compact_root,native_double):
    s,h,r=completed(compact_root,decks=2,delivery='pilot')
    assert s.status()['status']=='paused'
    repair,cid=propose(s,r,['p01']);confirm(repair,cid);last=r.run(cycles=100,interval=0)
    assert repair.case(cid)['state']=='completed',last
    assert s.status()['status']=='paused'
    assert not any(c['packet']['presentation']=='p02' for c in h.calls)
    assert not (s.task/'deliverables/p02/p02.pdf').exists()


def test_missing_confirmed_form_is_rejected_before_acceptance(compact_root,native_double):
    s,h,r=completed(compact_root,decks=1);repair,cid=propose(s,r,['p01']);confirm(repair,cid)
    def incomplete(req):
        response=h(req)
        if req['operation']=='run' and req['packet']['kind']=='edit' and req['packet'].get('repair_scope'):
            response['result']['repair_checks']=response['result']['repair_checks'][:-1]
        return response
    r.invoke=incomplete;last=r.run(cycles=20,interval=0)
    assert any(x['status']=='response_rejected' for x in last.get('results',[]))
    assert s.store.rows('SELECT pdf_path FROM releases')[0]['pdf_path']=='.mpres/releases/p01/r001/p01.pdf'
    assert not s.store.rows("SELECT * FROM release_versions WHERE revision=2 AND state='committed'")


def test_unobserved_claim_or_scope_fields_cannot_be_smuggled(compact_root,native_double):
    s,h,r=completed(compact_root,decks=1);repair,cid=propose(s,r,['p01'])
    expansion=repair.describe(cid)['expansion']
    expansion['variants'][0]['evidence_status']='observed'
    with pytest.raises(MPresError,match='actual slide'):repair.amend(cid,expansion,'planner')
    expansion['variants'][0]['evidence_status']='possible';expansion['runtime']={'model':'different'}
    with pytest.raises(MPresError):repair.amend(cid,expansion,'planner')


def test_cancel_unconfirmed_case_never_starts_editor(compact_root,native_double):
    s,h,r=completed(compact_root,decks=1);repair,cid=propose(s,r,['p01']);count=len(h.calls)
    repair.cancel(cid,'user','Do not repair this deck now.')
    r.run(cycles=3,interval=0)
    assert len(h.calls)==count
    assert not s.store.rows("SELECT * FROM repair_jobs WHERE stage='edit'")


def test_unknown_or_undelivered_targets_are_rejected(compact_root,native_double):
    s,h,r=completed(compact_root,decks=2,delivery='pilot');repair=Repairs(s.task)
    for ids in [['p99'],['p02'],['p01','p01'],[]]:
        with pytest.raises(MPresError):repair.open('Explain the problem',ids,'user')
    assert not s.store.rows('SELECT * FROM repair_cases')


def test_confirm_is_idempotent_does_not_duplicate_jobs(compact_root,native_double):
    s,h,r=completed(compact_root,decks=1);repair,cid=propose(s,r,['p01']);confirm(repair,cid)
    before=s.store.rows('SELECT * FROM jobs')
    assert repair.confirm(cid,1,'user')['already_confirmed']
    assert s.store.rows('SELECT * FROM jobs')==before


def test_stale_baseline_proposal_cannot_replace_newer_release(compact_root,native_double):
    s,h,r=completed(compact_root,decks=1)
    repair,c1=propose(s,r,['p01']);_,c2=propose(s,r,['p01'])
    confirm(repair,c1);r.run(cycles=100,interval=0)
    assert repair.case(c1)['state']=='completed'
    repair.present(c2)
    with pytest.raises(MPresError,match='changed'):repair.confirm(c2,1,'user')
    assert repair.case(c2)['state']=='presented'


def test_reviewer_cannot_skip_a_confirmed_related_problem(compact_root,native_double):
    s,h,r=completed(compact_root,decks=1);repair,cid=propose(s,r,['p01']);confirm(repair,cid)
    def bad_review(req):
        out=h(req)
        if req['operation']=='run' and req['packet']['kind']=='review':out['result']['repair_checks']=[]
        return out
    r.invoke=bad_review;last=r.run(cycles=100,interval=0)
    assert any(x['status']=='response_rejected' for x in last.get('results',[]))
    assert s.store.rows('SELECT pdf_path FROM releases')[0]['pdf_path']=='.mpres/releases/p01/r001/p01.pdf'


def test_semantic_uncertainty_blocks_repair_not_falsely_delivered(compact_root,native_double):
    s,h,r=completed(compact_root,decks=1);repair,cid=propose(s,r,['p01']);confirm(repair,cid)
    def uncertain_edit(req):
        out=h(req)
        if req['operation']=='run' and req['packet']['kind']=='edit':
            out['result']['repair_checks'][0]['status']='needs_decision'
            out['result']['repair_checks'][0]['explanation']='Need an authoritative terminology source before changing the name.'
        return out
    r.invoke=uncertain_edit;last=r.run(cycles=100,interval=0)
    assert last['status']=='blocked'
    assert s.store.rows('SELECT pdf_path FROM releases')[0]['pdf_path']=='.mpres/releases/p01/r001/p01.pdf'
    assert s.store.rows('SELECT phase FROM decks')[0]['phase']=='blocked'


def test_repair_publish_failure_retains_original_and_can_retry(compact_root,native_double,monkeypatch):
    s,h,r=completed(compact_root,decks=1);repair,cid=propose(s,r,['p01']);confirm(repair,cid)
    import mpres.control.workflow as mod
    real=mod.os.link
    def broken(src,dst,*a,**kw):
        if str(dst).endswith('/r002/p01.pdf'):raise OSError('fixture disk publication failure')
        return real(src,dst,*a,**kw)
    monkeypatch.setattr(mod.os,'link',broken)
    last=r.run(cycles=100,interval=0)
    assert last['status']=='blocked'
    assert s.store.rows('SELECT pdf_path FROM releases')[0]['pdf_path']=='.mpres/releases/p01/r001/p01.pdf'
    assert s.store.rows('SELECT state FROM release_versions WHERE revision=2')[0]['state']=='prepared'
    monkeypatch.setattr(mod.os,'link',real)
    Workflow(s.task).retry_publish('p01','The local publication error is corrected.')
    assert repair.case(cid)['state']=='completed'
    assert (s.task/'.mpres/releases/p01/r001/p01.pdf').is_file()
    assert (s.task/'.mpres/releases/p01/r002/p01.pdf').is_file()


def test_repair_bundle_gitignore_does_not_hide_sources(compact_root,tmp_path):
    import subprocess
    root=Path(__file__).resolve().parents[2]
    (tmp_path/'.gitignore').write_bytes((root/'.gitignore').read_bytes())
    subprocess.run(['git','init','-q'],cwd=tmp_path,check=True)
    files=['tasks/x/deliverables/x-repair-123.zip','tasks/x/deliverables/x-delivery.zip','marp-presentation-orchestrator-v0.6.15-source.zip']
    result=subprocess.run(['git','check-ignore','--stdin'],input='\n'.join(files),cwd=tmp_path,text=True,capture_output=True)
    assert files[0] in result.stdout and files[1] in result.stdout and files[2] not in result.stdout
