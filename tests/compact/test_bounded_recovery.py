from __future__ import annotations
import json
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import pytest
from mpres.control.service import Service, settings_document
from mpres.control.runner import Runner
from mpres.control.quality import Quality
from mpres.control.workflow import Workflow
from mpres.control.recovery import transient
from mpres.util import MPresError, SubmissionRejected, TransientToolError, read_yaml, write_yaml_atomic
from test_relational_control import compact_root, prepare
from test_revision_quality import revision
from test_job_runner import ready, host, attach_requests
from test_deck_workflow import full_task, Host, native_double


def test_temporary_checker_failure_retries_same_revision(compact_root,monkeypatch):
    s=prepare(compact_root);aid=revision(s);q=Quality(s.task);old=q._run;calls=[]
    def flaky(*args):
        calls.append(args[0]['id'])
        if len(calls)<3:raise TransientToolError('Browser process closed (fixture)')
        return old(*args)
    monkeypatch.setattr(q,'_run',flaky)
    assert q.inspect_recovering(aid)['state']=='passed'
    assert calls==[aid]*3
    assert len(s.store.rows("SELECT * FROM events WHERE kind='gate.automatic_retry'"))==2
    assert len(s.store.rows('SELECT * FROM attempts'))==1


def test_exhausted_tool_retry_budget_does_not_reset_on_tick(compact_root,monkeypatch):
    s=prepare(compact_root);aid=revision(s);q=Quality(s.task)
    def fail(*args):raise subprocess.TimeoutExpired(['fixture-marp'],1)
    monkeypatch.setattr(q,'_run',fail)
    for _ in range(4):assert q.inspect_recovering(aid)['state']=='failed'
    assert len(s.store.rows('SELECT * FROM gate_runs'))==3


@pytest.mark.parametrize('error',[MPresError('Missing pinned Marp'),ValueError('Unknown checker bug')])
def test_environment_or_unknown_error_does_not_consume_author_jobs(compact_root,monkeypatch,error):
    s=prepare(compact_root);aid=revision(s);q=Quality(s.task)
    def fail(*args):raise error
    monkeypatch.setattr(q,'_run',fail)
    result=q.inspect_recovering(aid)
    assert result['state']=='failed' and json.loads(result['detail_json'])['failure_kind']=='tool_or_input'
    assert len(s.store.rows('SELECT * FROM gate_runs'))==1
    assert not s.store.rows("SELECT * FROM jobs WHERE kind='edit'")


def test_error_word_in_content_does_not_make_it_transient():
    assert not transient(MPresError('Student quoted TargetClosedError in example'))
    assert transient(TransientToolError('A real checker error'))


def test_bridge_requests_real_fresh_observation_not_user_permission(compact_root):
    s,r=ready(compact_root)
    with s.store.transaction() as c:c.execute("UPDATE runtime_host SET observed_at='2000-01-01T00:00:00Z'")
    request=r.tick()['requests'][0];assert request['operation']=='capabilities'
    assert not s.store.rows('SELECT * FROM pool_slots')
    assert r.accept(request,host())['observed']
    assert all(q['operation']=='create' for q in r.tick()['requests'])


def test_missing_live_handle_is_not_hidden_by_inventory_refresh(compact_root):
    s,r=ready(compact_root);attach_requests(r,r.tick());r.observe_host(host())
    result=r.tick()
    assert result['status']=='blocked' and not result['requests']
    assert result['capacity']['missing_sessions']


def test_pilot_capacity_does_not_reserve_unstarted_deck_runtimes(compact_root):
    s=Service.create(compact_root,'pilotpool','Pilot capacity')
    from feedback_fixtures import infrastructure_only
    infrastructure_only(s)
    cfg=read_yaml(s.task/'task.yaml');cfg['delivery']='pilot';cfg['provider']['handle_limit']=12
    cfg['presentations']=[{'id':f'p{i:02d}','title':'Course','units':[{'id':'l01','title':'Topic','brief':'Explain quantities with an example.','sources':[]}]} for i in range(1,4)]
    write_yaml_atomic(s.task/'task.yaml',cfg)
    rt=read_yaml(s.task/'TASK-RUNTIME-PROFILE.yaml')
    rt['presentation_overrides']={f'p{i:02d}':{'author':{'model':f'fixed-author-{i}'},'reviewer':{'model':f'fixed-reviewer-{i}'}} for i in range(1,4)}
    write_yaml_atomic(s.task/'TASK-RUNTIME-PROFILE.yaml',rt);s.present();s.confirm('user')
    r=Runner(s.task);r.observe_host(host(limit=12));Workflow(s.task).ensure()
    report=r.capacity()
    assert report['ok'] and report['presentations_budgeted']==['p01']
    assert report['reviewer_slots_reserved']==5
    before=s.store.rows('SELECT runtime_json FROM configs')
    with s.store.transaction() as c:
        from mpres.control.store import event
        event(c,'task.delivery_continued',{'actor':'fixture-user'})
    report=r.capacity();assert report['presentations_budgeted']==['p01','p02','p03'] and not report['ok']
    assert s.store.rows('SELECT runtime_json FROM configs')==before


def test_known_completed_bad_source_gets_new_attempt_not_unknown(compact_root,native_double):
    s=full_task(compact_root,decks=1);h=Host();seen=[]
    def adapter(req):
        res=h(req)
        if req['operation']=='run' and req['packet']['kind']=='write':
            seen.append(req)
            if len(seen)==1:
                with Path(req['packet']['writable_directory'],'presentation.md').open('a') as f:f.write('\n<div>forbidden content</div>\n')
        return res
    r=Runner(s.task);r.invoke=adapter;r.run(cycles=100,interval=0)
    assert Workflow(s.task).status()['decks'][0]['phase']=='delivered'
    failed=s.store.rows("SELECT * FROM attempts WHERE state='failed'");assert len(failed)==1
    following=[q for q in seen if 'submission_correction' in q['packet']]
    assert following and following[0]['attempt_id']!=failed[0]['id']
    assert following[0]['runtime']==seen[0]['runtime']
    assert not s.store.rows("SELECT * FROM sessions WHERE state='uncertain'")
    assert len(s.store.rows("SELECT * FROM jobs WHERE kind='review'"))==5


def test_content_rejections_have_hard_total_attempt_bound(compact_root,native_double):
    s=full_task(compact_root,decks=1);h=Host()
    def adapter(req):
        res=h(req)
        if req['operation']=='run' and req['packet']['kind']=='write':
            with Path(req['packet']['writable_directory'],'presentation.md').open('a') as f:f.write('\n<br>\n')
        return res
    r=Runner(s.task);r.invoke=adapter;r.run(cycles=100,interval=0)
    jobs=s.store.rows("SELECT * FROM jobs WHERE kind='write'")
    assert all(j['state']=='blocked' for j in jobs)
    assert len(s.store.rows('SELECT * FROM attempts'))==4  # 2 units x 2 fixed allowed attempts
    assert not s.store.rows('SELECT * FROM releases')
    assert not s.store.rows("SELECT * FROM attempts WHERE state='uncertain'")
    count=len(h.calls);r.run(cycles=10,interval=0);assert len(h.calls)==count


def test_rejected_receipt_replay_does_not_requeue_twice(compact_root):
    s,r=ready(compact_root,count=1);attach_requests(r,r.tick());req=r.tick()['requests'][0];h=Host()
    res=h(req);Path(req['packet']['writable_directory'],'presentation.md').write_text('<div>no</div>')
    first=r.accept(req,res);assert first['submission_rejected']
    assert r.accept(req,res)['already_recorded']
    assert len(s.store.rows("SELECT * FROM events WHERE kind='attempt.content_rejected'"))==1
    bad={**res,'runtime':{**res['runtime'],'model':'different'}}
    with pytest.raises(MPresError,match='runtime'):r.accept(req,bad)


def test_invalid_runtime_is_never_content_retry(compact_root,native_double):
    s=full_task(compact_root,decks=1);h=Host()
    def adapter(req):
        res=h(req)
        if req['operation']=='run':res['runtime']={**res['runtime'],'model':'not-confirmed'}
        return res
    r=Runner(s.task);r.invoke=adapter;last=r.run(cycles=20,interval=0)
    assert any(x['status']=='uncertain' for x in last['results'])
    assert not s.store.rows("SELECT * FROM events WHERE kind='attempt.content_rejected'")


def test_host_observation_read_only_retry_is_bounded(compact_root):
    s,r=ready(compact_root);calls=[]
    def unavailable(req):calls.append(req);raise OSError('fixture transport unavailable')
    r.invoke=unavailable
    result=r.run_once()
    assert result['status']=='blocked' and len(calls)==3
    assert all(c['operation']=='capabilities' for c in calls)
    assert not s.store.rows('SELECT * FROM attempts')


def test_host_read_only_retry_then_progress(compact_root):
    s,r=ready(compact_root);h=Host();count=0
    def adapter(req):
        nonlocal count
        if req['operation']=='capabilities':
            count+=1
            if count==1:raise OSError('temporary inventory transport')
        return h(req)
    r.invoke=adapter
    assert r.run_once()['status']=='requests_ready'
    assert count==2


def test_corrected_environment_routes_real_content_back_to_author(compact_root,native_double,monkeypatch):
    s=full_task(compact_root,decks=1);h=Host();normal=Quality._run
    def missing(self,a,g,level,settings):
        if level=='full':raise MPresError('fixture browser installation absent')
        return normal(self,a,g,level,settings)
    monkeypatch.setattr(Quality,'_run',missing)
    r=Runner(s.task);r.invoke=h;r.run(cycles=30,interval=0)
    w=Workflow(s.task);assert w._deck('p01')['phase']=='blocked'
    with s.store.transaction() as c:
        c.execute("INSERT INTO decisions(kind,presentation,detail_json) VALUES('workflow-blocked','p01',?)",(json.dumps({'reason':'unrelated','resume_phase':'units'}),))
    def overflow(self,a,g,level,settings):
        return {'success':False,'checks':{},'failure_kind':'content','errors':['fixture real content issue']}
    monkeypatch.setattr(Quality,'_run',overflow)
    assert w.retry_checks('p01','Installed browser; content now inspectable')['state']=='failed'
    assert w._deck('p01')['phase']=='preflight'
    w.advance();assert w._deck('p01')['phase']=='editing'
    assert any(json.loads(x['detail_json']).get('reason')=='unrelated' for x in s.store.rows('SELECT * FROM decisions WHERE resolved_at IS NULL'))
    assert not s.store.rows('SELECT * FROM releases')


@pytest.mark.parametrize('recovery',[{'host_observation_retries':-1},{'transient_tool_retries':True},{'transient_tool_retries':4},{'auto_change_model':True},None])
def test_invalid_recovery_policy_rejected(compact_root,recovery):
    s=Service.create(compact_root,'policy','Policy test');cfg=read_yaml(s.task/'task.yaml');cfg['recovery']=recovery
    with pytest.raises(MPresError,match='[Rr]ecovery|recovery'):settings_document(cfg)


def test_parallel_recovery_cannot_multiply_retry_budget(compact_root,monkeypatch):
    s=prepare(compact_root);aid=revision(s)
    def fail(self,*args):raise TransientToolError('fixture closed browser')
    monkeypatch.setattr(Quality,'_run',fail)
    with ThreadPoolExecutor(max_workers=6) as pool:
        list(pool.map(lambda _:Quality(s.task).inspect_recovering(aid),range(12)))
    assert len(s.store.rows('SELECT * FROM gate_runs'))==3
    assert not s.store.rows("SELECT * FROM gate_runs WHERE state='passed'")


def test_zero_retry_policy_retains_failure(compact_root,monkeypatch):
    s=Service.create(compact_root,'zero','No extra checker attempts')
    from feedback_fixtures import infrastructure_only
    infrastructure_only(s)
    cfg=read_yaml(s.task/'task.yaml');cfg['workflow']='authoring';cfg['recovery']={'transient_tool_retries':0,'host_observation_retries':0}
    cfg['presentations']=[{'id':'p01','title':'Topic','units':[{'id':'l01','title':'Lesson','brief':'Explain coordinates with units and an example.','sources':[]}]}]
    write_yaml_atomic(s.task/'task.yaml',cfg);s.present();s.confirm('user');s.materialize()
    aid=revision(s);q=Quality(s.task)
    def fail(*args):raise TransientToolError('fixture failure')
    monkeypatch.setattr(q,'_run',fail)
    assert q.inspect_recovering(aid)['state']=='failed'
    assert len(s.store.rows('SELECT * FROM gate_runs'))==1
