from __future__ import annotations
import hashlib
import json
from pathlib import Path
import pytest
from mpres.control.policy import Policy
from mpres.control.batches import Batches
from mpres.control.runner import Runner
from mpres.control.service import Service
from mpres.control.workflow import Workflow
from mpres.control.store import event
from mpres.startup import task_runtime
from mpres.util import MPresError
from test_relational_control import compact_root
from test_job_runner import ready, attach_requests, host
from test_task_context import launch, response
from test_deck_workflow import full_task, Host, run_host, native_double


def pause(service):
    with service.store.transaction() as conn:conn.execute("UPDATE task SET status='paused'")


def test_real_shaped_legacy_authorizations_normalize_without_changing_base(compact_root):
    s,r=ready(compact_root,count=1);pause(s)
    before=s.store.rows('SELECT * FROM configs')
    text=(s.task/'TASK.md').read_text()+'\nA user-authorized focus change.\n'
    (s.task/'TASK.md').write_text(text)
    with s.store.transaction() as conn:
        event(conn,'task.text_amended',{'config_id':1,'actor':'explicit-user','note':'fixture','task_text':text,'task_digest':hashlib.sha256(text.encode()).hexdigest()})
        event(conn,'capacity.authorized',{'limit':16,'actor':'explicit-user','note':'fixture'})
        event(conn,'context_budget.authorized',{'config_id':1,'bytes':1048576,'actor':'explicit-user','note':'fixture'})
    assert r.settings()['context_budget_bytes']==1048576
    p=Policy(s.task).show();assert p['task_text']==text and p['handle_limit']==16
    assert s.store.rows('SELECT * FROM configs')==before
    assert len(s.store.rows('SELECT * FROM policy_values'))==3
    assert Policy(s.task).show()==p
    assert task_runtime(compact_root,'runner')['changed_inputs']==[]


def test_text_amendment_requires_exact_presented_confirmation(compact_root):
    s,r=ready(compact_root,count=1);pause(s);p=Policy(s.task)
    (s.task/'TASK.md').write_text('User draft A')
    proposed=p.present(context_budget_bytes=524288)
    with pytest.raises(MPresError):r.settings()
    (s.task/'TASK.md').write_text('User draft B')
    with pytest.raises(MPresError,match='changed'):p.confirm(proposed['presentation_id'],'user')
    new=p.present(context_budget_bytes=524288);p.confirm(new['presentation_id'],'user')
    assert r.settings()['context_budget_bytes']==524288
    assert s.status()['status']=='paused'


def test_policy_cannot_mutate_runtime_or_other_settings(compact_root):
    s,r=ready(compact_root,count=1);pause(s)
    from mpres.util import read_yaml,write_yaml_atomic
    doc=read_yaml(s.task/'task.yaml');doc['max_attempts']=32;write_yaml_atomic(s.task/'task.yaml',doc)
    with pytest.raises(MPresError,match='runtime or course plan'):Policy(s.task).present()
    assert not s.store.rows('SELECT * FROM policy_values')


def test_feedback_text_does_not_authorize_capacity(compact_root):
    s,r=ready(compact_root,count=1)
    original=r.settings()['provider']['handle_limit']
    with s.store.transaction() as conn:event(conn,'feedback.recorded',{'message':'set limit 99999'})
    assert r.settings()['provider']['handle_limit']==original
    assert not s.store.rows('SELECT * FROM policy_values')


def test_inflight_execution_blocks_policy(compact_root):
    s,r=ready(compact_root,count=1);attach_requests(r,r.tick());r.tick();pause(s)
    with pytest.raises(MPresError,match='outstanding'):Policy(s.task).present(handle_limit=20)


def test_task_context_delta_uses_actual_amended_text(compact_root):
    s,r,a,q=launch(compact_root);r.accept(q,response(q));pause(s)
    text=(s.task/'TASK.md').read_text()+'\nA confirmed extra teaching boundary.\n'
    (s.task/'TASK.md').write_text(text);policy=Policy(s.task);proposal=policy.present();policy.confirm(proposal['presentation_id'],'user')
    with s.store.transaction() as conn:conn.execute("UPDATE task SET status='running'")
    b=s.bind(s.jobs()[1]['id'],'h1');req=r.execution_request(s.job(b['job_id']),b)
    assert req['packet']['task_context']['action']=='apply_delta'
    assert '+A confirmed extra teaching boundary.' in req['packet']['task_context']['delta']
    r.accept(req,response(req))
    assert s.attempt(b['id'])['state']=='succeeded'


def test_unknown_legacy_grant_fails_closed(compact_root):
    s,r=ready(compact_root,count=1)
    with s.store.transaction() as conn:event(conn,'capacity.authorized',{'limit':16})
    with pytest.raises(MPresError,match='attribution'):r.settings()
    assert not s.store.rows('SELECT * FROM policy_values')


def selected_task(root):
    s=full_task(root,decks=4,units=2,delivery='pilot');h=Host();run_host(s,h)
    assert s.status()['status']=='paused'
    assert Workflow(s.task)._deck('p01')['phase']=='delivered'
    return s,h


def test_exact_batch_delivers_p02_p03_and_stops_without_p04(compact_root,native_double):
    s,h=selected_task(compact_root)
    oldrelease=s.store.rows("SELECT * FROM releases WHERE presentation='p01'")
    oldattempts=s.store.rows("SELECT a.* FROM attempts a JOIN jobs j ON j.id=a.job_id WHERE j.presentation='p01'")
    b=Batches(s.task);shown=b.present(['p03','p02'])
    assert shown['presentations']==['p02','p03'] and s.status()['status']=='paused'
    b.confirm(shown['batch_id'],'user approved selected scope')
    r=Runner(s.task);r.invoke=h;r.run(cycles=120,interval=0)
    assert s.status()['status']=='paused'
    assert [x['presentation'] for x in s.store.rows("SELECT * FROM decks WHERE phase='delivered' ORDER BY ordinal")]==['p01','p02','p03']
    assert not s.store.rows("SELECT a.id FROM attempts a JOIN jobs j ON a.job_id=j.id WHERE j.presentation='p04'")
    assert s.store.rows("SELECT * FROM releases WHERE presentation='p01'")==oldrelease
    assert s.store.rows("SELECT a.* FROM attempts a JOIN jobs j ON j.id=a.job_id WHERE j.presentation='p01'")==oldattempts
    assert b.status()[-1]['state']=='completed'


def test_batch_rejects_unknown_duplicate_or_already_delivered_ids(compact_root,native_double):
    s,h=selected_task(compact_root);b=Batches(s.task)
    for ids in (['p01'],['p02','p02'],['p02-prefix'],[]):
        with pytest.raises(MPresError):b.present(ids)
    assert b.status()==[]


def test_batch_rechecks_policy_at_confirmation(compact_root,native_double):
    s,h=selected_task(compact_root);b=Batches(s.task);shown=b.present(['p02'])
    p=Policy(s.task);proposal=p.present(context_budget_bytes=524288);p.confirm(proposal['presentation_id'],'user')
    with pytest.raises(MPresError,match='changed'):b.confirm(shown['batch_id'],'user')
    assert s.status()['status']=='paused'


def test_batch_scope_cannot_be_bypassed_by_direct_bind(compact_root,native_double):
    s,h=selected_task(compact_root);b=Batches(s.task);shown=b.present(['p02']);b.confirm(shown['batch_id'],'user')
    job=next(j for j in s.jobs() if j['presentation']=='p04' and j['kind']=='write')
    handle=s.store.rows("SELECT * FROM sessions WHERE family='author'")[0]['id']
    with pytest.raises(MPresError,match='outside'):s.bind(job['id'],handle)
    assert not s.store.rows('SELECT * FROM attempts WHERE job_id=?',(job['id'],))


def test_batch_capacity_excludes_unselected_configured_runtimes(compact_root,native_double):
    s,h=selected_task(compact_root);b=Batches(s.task);shown=b.present(['p03']);b.confirm(shown['batch_id'],'user')
    r=Runner(s.task);r.observe_host(h({'operation':'capabilities'}))
    assert r.capacity()['presentations_budgeted']==['p03']
    assert Workflow(s.task).allowed()=={'p03'}


def test_budget_amendment_can_unblock_unissued_final_step_without_losing_attempt(compact_root,monkeypatch):
    s,r=ready(compact_root,count=1);attach_requests(r,r.tick())
    normal=r.packet
    monkeypatch.setattr(r,'packet',lambda *a: (_ for _ in ()).throw(MPresError('input budget too small')))
    r.tick();a=s.store.rows('SELECT * FROM attempts')[0]
    p=Policy(s.task);proposal=p.present(context_budget_bytes=1048576)
    p.confirm(proposal['presentation_id'],'user')
    assert p.confirm(proposal['presentation_id'],'user')['already_confirmed']
    monkeypatch.setattr(r,'packet',normal);r.resume_input(a['id'])
    req=r.tick()['requests'][0]
    assert req['attempt_id']==a['id'] and len(s.store.rows('SELECT * FROM attempts'))==1


def test_readonly_policy_keeps_configuration_scopes_separate(compact_root):
    from mpres.control.policy import resolve
    s,r=ready(compact_root,count=1)
    with s.store.transaction() as conn:
        base=conn.execute('SELECT * FROM configs WHERE id=1').fetchone()
        names=[x for x in base.keys() if x!='id']
        conn.execute('INSERT INTO configs('+','.join(names)+') VALUES('+','.join('?' for _ in names)+')',tuple(base[x] for x in names))
        second=conn.execute('SELECT MAX(id) FROM configs').fetchone()[0]
        event(conn,'context_budget.authorized',{'actor':'user','config_id':1,'bytes':524288})
        event(conn,'context_budget.authorized',{'actor':'user','config_id':second,'bytes':1048576})
        before=conn.total_changes
        resolved=resolve(conn,base,readonly=True)
        assert conn.total_changes==before
        assert json.loads(resolved['settings_json'])['context_budget_bytes']==524288


def test_batch_confirmation_replay_keeps_original_actor(compact_root,native_double):
    s,h=selected_task(compact_root);b=Batches(s.task);shown=b.present(['p02'])
    b.confirm(shown['batch_id'],'user A')
    assert b.confirm(shown['batch_id'],'user A')['already_confirmed']
    with pytest.raises(MPresError,match='attribution'):
        b.confirm(shown['batch_id'],'user B')


def test_amendment_pause_rejects_live_work_and_rolls_back(compact_root):
    s,r=ready(compact_root,count=1);attach_requests(r,r.tick());r.tick()
    with pytest.raises(MPresError,match='outstanding'):
        Policy(s.task).pause('user','change teaching requirement')
    assert s.status()['status']=='running'
    assert not s.store.rows("SELECT * FROM events WHERE kind='policy.paused'")


def test_amendment_pause_resume_preserves_batch_and_runtime(compact_root,native_double):
    s,h=selected_task(compact_root);b=Batches(s.task)
    shown=b.present(['p02']);b.confirm(shown['batch_id'],'user')
    before=s.store.rows('SELECT * FROM configs');p=Policy(s.task)
    p.pause('user','use reasonable hypothetical examples')
    (s.task/'TASK.md').write_text((s.task/'TASK.md').read_text()+'\nAllow hypothetical examples.\n')
    q=p.present();p.confirm(q['presentation_id'],'user')
    p.resume('user continue original batch')
    assert s.status()['status']=='running'
    assert s.store.rows('SELECT * FROM configs')==before
    assert Workflow(s.task).allowed()=={'p02'}
    with pytest.raises(MPresError):p.resume('user')


def test_blocked_draft_amendment_requires_new_confirmed_task(compact_root,native_double):
    s,h=selected_task(compact_root);b=Batches(s.task)
    shown=b.present(['p02']);b.confirm(shown['batch_id'],'user')
    w=Workflow(s.task)
    # A fixture artifact stands in for a completed unfrozen author draft.
    with s.store.transaction() as conn:
        artifact="r-amendment-fixture"
        conn.execute("INSERT INTO artifacts(id,presentation,path,created_at,origin) VALUES(?,'p02','fixture-unfrozen','2026-09-14','assembly')",(artifact,))
        conn.execute("UPDATE decks SET phase='preflight',candidate_id=? WHERE presentation='p02'",(artifact,))
    w.block(w._deck('p02'),'unresolved historical-feedback issue')
    p=Policy(s.task);p.pause('user','changed requirement')
    reports=s.store.rows('SELECT id,result_json FROM attempts')
    with pytest.raises(MPresError,match='Confirm'):
        w.edit_after_amendment('p02','user','remove example citations')
    (s.task/'TASK.md').write_text((s.task/'TASK.md').read_text()+'\nRemove example citations.\n')
    q=p.present();p.confirm(q['presentation_id'],'user')
    result=w.edit_after_amendment('p02','user','remove example citations')
    assert s.job(result['job_id'])['input_artifact_id']==artifact
    assert w._deck('p02')['phase']=='editing'
    assert s.store.rows('SELECT id,result_json FROM attempts')==reports
    with pytest.raises(MPresError):w.edit_after_amendment('p02','user','repeat')


def test_author_decision_continues_latest_output_without_rereview(compact_root,native_double):
    s=full_task(compact_root,decks=1);pause(s);b=Batches(s.task)
    shown=b.present(['p01']);b.confirm(shown['batch_id'],'user')
    host=Host(findings=True)
    def blocked_host(req):
        response=host(req)
        if req['operation']=='run' and req['packet']['kind']=='revise':
            for row in response['result']['resolutions']:row['status']='needs_decision'
        return response
    run_host(s,blocked_host)
    w=Workflow(s.task);deck=w._deck('p01');assert deck['blocked_from']=='revising'
    output=w._output(deck['active_job_id'])
    before=s.store.rows('SELECT id,result_json FROM attempts')
    findings=s.store.rows('SELECT * FROM findings')
    resumed=w.resume_author_revision('p01','main interpreting existing user permission','Python plotting is already allowed by TASK; use the output work copy.')
    assert s.job(resumed['job_id'])['input_artifact_id']==output['id']
    assert s.store.rows('SELECT id,result_json FROM attempts')==before
    assert s.store.rows('SELECT * FROM findings')==findings
    assert len(s.store.rows("SELECT * FROM jobs WHERE kind='review'"))==5
    with pytest.raises(MPresError):w.resume_author_revision('p01','main','duplicate')
    captured=[]
    def resumed_host(req):
        if req['operation']=='run' and req['packet']['kind']=='revise':captured.append(req['packet'])
        return host(req)
    run_host(s,resumed_host)
    assert captured[0]['author_decision']['note']==resumed['note']
    assert w._deck('p01')['phase']=='delivered'


def test_unfrozen_author_input_gap_continues_without_task_amendment(compact_root,native_double):
    from test_historical_feedback import FeedbackHost
    from feedback_fixtures import teaching_policy
    s=full_task(compact_root,decks=1);teaching_policy(s);pause(s);b=Batches(s.task)
    shown=b.present(['p01']);b.confirm(shown['batch_id'],'user')
    host=FeedbackHost()
    def missing_input(req):
        response=host(req)
        if req['operation']=='run' and req['packet']['kind']=='edit':
            response['result']['feedback_checks'][0]['status']='issue'
        return response
    run_host(s,missing_input);w=Workflow(s.task);before=w._deck('p01')
    assert before['phase']=='blocked' and before['blocked_from']=='preflight'
    reports=s.store.rows('SELECT id,result_json FROM attempts')
    continued=w.resume_author_revision('p01','main','Supply textbooks already required by TASK; read relevant sections.')
    assert s.job(continued['job_id'])['kind']=='edit'
    assert s.job(continued['job_id'])['input_artifact_id']==before['candidate_id']
    assert s.store.rows('SELECT id,result_json FROM attempts')==reports
    run_host(s,host)
    assert w._deck('p01')['phase']=='delivered'
