from __future__ import annotations

import json
from pathlib import Path

import pytest

from mpres.control.feedback import Feedback
from mpres.control.runner import Runner
from mpres.control.service import Service
from mpres.control.workflow import Workflow
from mpres.marp_source import parse_deck
from mpres.util import MPresError
from test_relational_control import compact_root, prepare, register, source_for
from test_job_runner import host, attach_requests
from test_deck_workflow import full_task, Host, native_double, run_host
from feedback_fixtures import teaching_policy, readback, checks


def ready(root):
    s=prepare(root,count=1);f=teaching_policy(s);register(s)
    a=s.bind(s.jobs()[0]['id'],'h1')
    return s,f,a


def acknowledge(s,f,a):
    b=f.briefing(a['id']);f.acknowledge(a['id'],readback(b['feedback']),'fixture-readback')
    s.started(a['id'],'fixture-content-execution')
    return b


def result(s,b):
    src=source_for(s)
    return {'summary':'A structural fixture, not assessed mathematics.',
            'feedback_checks':checks(b['feedback'],'p01-l01-s1','# Example')},src


def test_new_task_seeds_exact_user_concerns_without_more_documents(compact_root):
    s=Service.create(compact_root,'quality','Algebra')
    rules=Feedback(s.task).list()
    assert {r['id'] for r in rules}=={'standard-terminology','recent-real-world-examples','explicit-geometric-intuition','student-learning-value'}
    assert all(r['report'] and r['possible_forms'] and r['acceptance'] for r in rules)
    assert sorted(p.name for p in s.task.iterdir() if p.is_file())==['TASK-RUNTIME-PROFILE.yaml','TASK.md','task.yaml']


def test_source_execution_cannot_precede_readback(compact_root):
    s,f,a=ready(compact_root)
    with pytest.raises(MPresError,match='acknowledged'):s.started(a['id'],'too-early')
    assert s.attempt(a['id'])['state']=='reserved'
    acknowledge(s,f,a)
    assert s.attempt(a['id'])['state']=='running'


def test_incomplete_or_wrong_version_readback_fails(compact_root):
    s,f,a=ready(compact_root);rows=readback(f.briefing(a['id'])['feedback'])
    with pytest.raises(MPresError):f.acknowledge(a['id'],rows[:-1],'receipt')
    rows[0]['version']+=1
    with pytest.raises(MPresError):f.acknowledge(a['id'],rows,'receipt')


def test_readback_idempotent_and_immutable(compact_root):
    s,f,a=ready(compact_root);rows=readback(f.briefing(a['id'])['feedback'])
    f.acknowledge(a['id'],rows,'receipt')
    assert f.acknowledge(a['id'],rows,'receipt')['already_acknowledged']
    rows[0]['approach']='Different interpretation'
    with pytest.raises(MPresError,match='immutable'):f.acknowledge(a['id'],rows,'receipt')


def test_missing_or_invented_feedback_evidence_is_rejected(compact_root):
    s,f,a=ready(compact_root);b=acknowledge(s,f,a);r,src=result(s,b)
    with pytest.raises(MPresError,match='feedback_checks'):s.submit(a['id'],{'summary':'Done'},source=src)
    r['feedback_checks'][0]['evidence'][0]['quote']='Invented content never written'
    with pytest.raises(MPresError,match='not in'):s.submit(a['id'],r,source=src)
    assert not s.store.rows('SELECT * FROM artifacts')


def test_feedback_snapshot_and_result_survive_service_restart(compact_root):
    s,f,a=ready(compact_root);b=acknowledge(s,f,a);r,src=result(s,b)
    s=Service(s.task);s.submit(a['id'],r,source=src)
    assert Feedback(s.task).briefing(a['id'])['feedback']==b['feedback']
    assert s.submit(a['id'],r,source=src)['already_submitted']


def test_task_runtime_unchanged_by_feedback(compact_root):
    s,f,a=ready(compact_root);before=s.store.rows('SELECT * FROM configs')
    r=f.list()[0];r.pop('version');r['expectation']+=' Additional explicit user wording.'
    f.record(r,'user')
    assert s.store.rows('SELECT * FROM configs')==before
    assert len(f.list(True))>len(f.list())
    assert f.briefing(a['id'])['feedback'][0]['version']<f.list()[0]['version']


def test_scope_only_applies_to_selected_presentation(compact_root):
    s,f,a=ready(compact_root)
    r={'id':'local-issue','report':'Local report','expectation':'Explain the condition',
       'possible_forms':['Missing condition'],'acceptance':'Cite the condition',
       'presentations':['p01'],'enabled':True}
    f.record(r,'user')
    with s.store.transaction() as conn:
        assert any(x['id']=='local-issue' for x in f.effective(conn,'p01'))
        assert all(x['id']!='local-issue' for x in f.effective(conn,'p02'))


class FeedbackHost(Host):
    def __call__(self,req):
        if req['operation']=='brief':
            return {'runtime':req['runtime'],'receipt':'brief:'+req['attempt_id'],
                    'readback':readback(req['packet']['historical_feedback']),
                    'usage':[{'call_id':'brief','counters':{'input_tokens':30,'cached_input_tokens':0,'output_tokens':8,'reasoning_tokens':0,'total_tokens':38}}]}
        response=super().__call__(req)
        if req['operation']=='run':
            packet=req['packet'];rules=packet['historical_feedback']
            path=Path(packet['frozen_source_directory']) if packet['kind']=='review' else Path(packet['writable_directory'])
            slide=parse_deck(path/'presentation.md').slides[0]
            response['result']['feedback_checks']=checks(rules,slide.slide_id,slide.title)
        return response


def test_full_workflow_readbacks_all_authors_editors_reviewers(compact_root,native_double):
    s=full_task(compact_root,decks=1,units=2);teaching_policy(s);h=FeedbackHost()
    run_host(s,h)
    assert s.status()['status']=='completed'
    live=s.store.rows('SELECT * FROM attempts WHERE session_id IS NOT NULL')
    brief=s.store.rows('SELECT * FROM attempt_briefings')
    assert len(brief)==len(live)==8
    assert all(r['acknowledgement_json'] and r['run_dispatched'] for r in brief)
    assert s.metrics()['calls_observed']==18  # readback/work plus two bounded audience reading steps
    assert all(c['packet']['historical_feedback'] for c in h.calls if c['operation']=='run')
    assert s.store.rows("SELECT * FROM events WHERE kind='feedback.readback'")


def test_runner_emits_brief_then_run_never_both_before_ack(compact_root):
    s=prepare(compact_root,count=1);teaching_policy(s);runner=Runner(s.task)
    runner.observe_host(host());attach_requests(runner,runner.tick())
    tick=runner.tick();req=tick['requests'][0]
    assert req['operation']=='brief' and req['packet']['writable_directory'] is None
    assert runner.tick()['requests']==[]
    runner.accept(req,FeedbackHost()(req))
    req2=runner.tick()['requests'][0]
    assert req2['operation']=='run' and req2['packet']['historical_feedback']
    assert runner.tick()['requests']==[]


def test_changed_feedback_prevents_old_review_release_proof(compact_root,native_double):
    s=full_task(compact_root,decks=1,units=2);f=teaching_policy(s);run_host(s,FeedbackHost())
    r=f.list()[0];r.pop('version');r['expectation']+=' User now requires an explicit diagram.'
    f.record(r,'user')
    with pytest.raises(MPresError,match='changed'):
        Workflow(s.task)._review_proof(s.store.rows('SELECT * FROM decks')[0])


def test_reviewer_issue_must_be_a_routed_finding(compact_root):
    s,f,a=ready(compact_root);b=acknowledge(s,f,a);r,src=result(s,b)
    aid=s.submit(a['id'],r,source=src)['artifact_id']
    with s.store.transaction() as conn:
        j=s.ensure_job(conn,key='review-fixture',presentation='p01',kind='review',channel='language',round=1,artifact=aid)
    register(s,'r1','reviewer','low');ra=s.bind(j,'r1');rb=acknowledge(s,f,ra)
    r={'summary':'Terminology is inadequate','findings':[], 'feedback_checks':checks(rb['feedback'],'p01-l01-s1','# Example')}
    r['feedback_checks'][0]['status']='issue'
    with pytest.raises(MPresError,match='routed finding'):s.submit(ra['id'],r)


def test_feedback_is_visible_at_task_presentation(compact_root):
    s=prepare(compact_root,count=1);teaching_policy(s)
    doc=s.present()
    assert len(doc['historical_feedback'])==4
    assert all(r['report'] and r['expectation'] for r in doc['historical_feedback'])
    assert s.confirm('user')['already_confirmed']


def test_bare_read_tick_and_boolean_version_are_not_a_readback(compact_root):
    s,f,a=ready(compact_root);rows=readback(f.briefing(a['id'])['feedback'])
    rows[0]['approach']='已阅读。'
    with pytest.raises(MPresError,match='concrete'):f.acknowledge(a['id'],rows,'receipt')
    rows=readback(f.briefing(a['id'])['feedback']);rows[0]['version']=True
    with pytest.raises(MPresError,match='types'):f.acknowledge(a['id'],rows,'receipt')
