from __future__ import annotations
import copy,json
from pathlib import Path
import pytest
from mpres.control.audience import Audience
from mpres.control.runner import Runner
from mpres.control.service import Service
from mpres.control.workflow import Workflow
from mpres.marp_source import parse_deck
from mpres.util import MPresError
from test_relational_control import compact_root
from test_deck_workflow import full_task, Host, native_double, run_host
from test_revision_quality import HEADER
from test_historical_feedback import FeedbackHost
from feedback_fixtures import teaching_policy


def audience_ready(root, *, pages=2):
    service=full_task(root,decks=1,units=1);host=Host();runner=Runner(service.task)
    def invoke(req):
        response=host(req)
        if req['operation']=='run' and req['packet']['kind']=='write':
            target=Path(req['packet']['writable_directory'])/'presentation.md'
            target.write_text(HEADER+'\n\n---\n\n'.join(
                f'<!-- slide-id: p01-l01-s{i} -->\n<!-- _class: core -->\n# Topic {i}\n\nA vector is an ordered pair.\n' for i in range(1,pages+1)))
        return response
    runner.invoke=invoke
    for _ in range(40):
        runner.observe_host(host({'operation':'capabilities'}))
        tick=runner.tick()
        for request in tick['requests']:
            if request['operation']=='audience_step':return service,runner,host,request
            runner.accept(request,invoke(request))
    raise AssertionError('Audience step not reached')


def finish_steps(runner,host,request):
    seen=[]
    while request['operation']=='audience_step':
        seen.append(request);runner.accept(request,host(request))
        next_requests=runner.tick()['requests']
        assert len(next_requests)==1
        request=next_requests[0]
    return seen,request


def test_two_narrow_passes_then_one_final_same_session(compact_root,native_double):
    s,r,h,req=audience_ready(compact_root,pages=27)
    seen,last=finish_steps(r,h,req)
    assert [x['packet']['phase'] for x in seen]==['student']*3+['production_language']*3
    assert len({x['session_id'] for x in seen+[last]})==1
    assert last['operation']=='run' and last['packet']['channel']=='audience'
    for phase in ('student','production_language'):
        ids=[sid for x in seen if x['packet']['phase']==phase for sid in x['packet']['read_slide_ids']]
        assert ids==[f'p01-l01-s{i}' for i in range(1,28)]
    assert not list(s.task.rglob('AUDIENCE-*.md'))
    assert len(s.store.rows('SELECT * FROM audience_steps'))==6
    assert len(s.store.rows("SELECT * FROM jobs WHERE channel='audience'"))==1


def test_student_packet_contains_no_producer_assertions(compact_root,native_double):
    s,r,h,req=audience_ready(compact_root)
    p=req['packet']
    assert 'frozen_source_directory' not in p and 'frozen_pdf' not in p
    assert 'historical_feedback' not in p and 'feedback_checks' not in p
    assert 'blind' in p['limitations']
    assert p['writable_directory'] is None
    assert 'not' in p['instructions'].lower() or 'Do not' in p['instructions']
    assert all('.sqlite' not in f and 'SELF-CHECK' not in f for f in p['input_files'])


def test_live_dispatched_step_not_duplicated_on_tick(compact_root,native_double):
    s,r,h,req=audience_ready(compact_root)
    assert r.tick()['requests']==[]
    assert len(s.store.rows("SELECT * FROM audience_steps WHERE state='dispatched'"))==1


def test_exact_replay_and_conflict(compact_root,native_double):
    s,r,h,req=audience_ready(compact_root);response=h(req)
    assert not r.accept(req,response)['already_recorded']
    assert r.accept(req,response)['already_recorded']
    changed=copy.deepcopy(response);changed['result']['summary']='A different claim'
    with pytest.raises(MPresError,match='Conflicting'):r.accept(req,changed)


@pytest.mark.parametrize('change',['coverage','quote','runtime','source','phase','usage'])
def test_reject_false_step_evidence(compact_root,native_double,change):
    s,r,h,req=audience_ready(compact_root);response=h(req)
    if change=='coverage':response['result']['read_slide_ids']=['invented']
    if change=='quote':response['result']['observations']=[{'slide_id':req['packet']['read_slide_ids'][0],'quote':'Never written','learning_impact':'Confusing'}]
    if change=='runtime':response['runtime']={**response['runtime'],'reasoning_effort':'max'}
    if change=='source':response['source_dir']='output'
    if change=='phase':response['result']['phase']='production_language'
    if change=='usage':response['usage']=[]
    with pytest.raises(MPresError):r.accept(req,response)
    assert s.store.rows('SELECT state FROM audience_steps ORDER BY sequence')[0]['state']=='dispatched'


def test_cannot_submit_final_before_reading(compact_root,native_double):
    s,r,h,req=audience_ready(compact_root)
    s.started(req['attempt_id'],'premature-final')
    with pytest.raises(MPresError,match='passes must finish'):
        s.submit(req['attempt_id'],{'summary':'Skipped reading','findings':[]})
    assert not s.store.rows("SELECT * FROM jobs WHERE channel='audience' AND state='succeeded'")


def test_late_step_receipt_reconciles_without_second_execution(compact_root,native_double):
    s,r,h,req=audience_ready(compact_root);response=h(req)
    s.uncertain(req['attempt_id'],'Lost step transport')
    assert r.tick()['requests']==[]
    r.accept(req,response)
    assert s.attempt(req['attempt_id'])['state']=='reserved'
    assert r.tick()['requests'][0]['packet']['phase']=='production_language'


def test_final_cannot_drop_student_finding(compact_root,native_double):
    s,r,h,req=audience_ready(compact_root)
    response=h(req);finding={'message':'Explain the meaning of the coordinates.','severity':'minor','slide_ids':[req['packet']['read_slide_ids'][0]]}
    response['result']['findings']=[finding];r.accept(req,response)
    req=r.tick()['requests'][0];r.accept(req,h(req));last=r.tick()['requests'][0]
    assert 'findings' not in last['packet']['audience_reading'][0]
    assert last['packet']['audience_reading'][0]['finding_refs'][0]['ref']=='step:0:1'
    response=h(last)
    assert not r.accept(last,response)['already_submitted']
    rows=s.store.rows('SELECT detail_json FROM findings WHERE job_id=?',(s.attempt(req['attempt_id'])['job_id'],))
    assert [json.loads(x['detail_json']) for x in rows]==[finding]


def test_historical_brief_precedes_steps_and_counts_usage(compact_root,native_double):
    s=full_task(compact_root,decks=1,units=2);teaching_policy(s);h=FeedbackHost();run_host(s,h)
    assert s.status()['status']=='completed'
    rows=s.store.rows("SELECT a.id FROM attempts a JOIN jobs j ON j.id=a.job_id WHERE j.channel='audience'")
    aid=rows[0]['id'];brief=s.store.rows('SELECT * FROM attempt_briefings WHERE attempt_id=?',(aid,))[0]
    assert brief['acknowledgement_json'] and brief['run_dispatched']
    assert len(s.store.rows('SELECT * FROM usage WHERE attempt_id=?',(aid,)))==4
    assert len(s.store.rows("SELECT * FROM participation WHERE kind='review'"))==5
