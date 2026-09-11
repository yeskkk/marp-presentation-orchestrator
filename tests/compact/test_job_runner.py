from __future__ import annotations

import json
import sqlite3
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from mpres.control.runner import Runner
from mpres.control.service import Service
from mpres.util import MPresError, read_yaml, write_yaml_atomic
from test_relational_control import compact_root, prepare, register, completed, source_for


def host(handles=(),limit=16):
    return {'handle_limit':limit,'handles':['main',*handles],'supports_close':False,'supports_reset':False,'usage_reporting':True,'receipt':'real-fixture-inventory'}


def ready(compact_root,count=6,limit=16,concurrency=6):
    service=Service.create(compact_root,'runner','Vectors')
    from feedback_fixtures import infrastructure_only
    infrastructure_only(service)
    config=read_yaml(service.task/'task.yaml'); config['workflow']='authoring'
    config['author_concurrency']=concurrency
    config['provider']['handle_limit']=limit
    config['provider']['external_handles']=1
    config['presentations']=[{'id':'p01','title':'Vectors','units':[{'id':f'l{i+1:02d}','title':'Lesson','brief':'Explain coordinates and diagnose confusion.','sources':[]} for i in range(count)]}]
    write_yaml_atomic(service.task/'task.yaml',config);service.present();service.confirm('user')
    runner=Runner(service.task);runner.observe_host(host(limit=limit))
    return service,runner


def attach_requests(runner,result):
    handles=[]
    for req in result['requests']:
        assert req['operation']=='create'
        name='host-'+str(req['slot_id']);runtime=req['runtime']
        runner.attach(req['slot_id'],name,runtime['model'],runtime['reasoning_effort'],'creation:'+name)
        handles.append(name)
    runner.observe_host(host(handles))
    return handles


def test_unknown_host_never_spawns(compact_root):
    service=prepare(compact_root)
    result=Runner(service.task).tick()
    assert result['status']=='needs_host_observation' and result['requests'][0]['operation']=='capabilities'
    assert service.store.rows('SELECT * FROM pool_slots')==[]


def test_current_and_future_pools_fit_without_close(compact_root):
    service,runner=ready(compact_root,count=6,limit=16,concurrency=6)
    report=runner.capacity()
    assert report['ok'] and report['reviewer_slots_reserved']==5
    assert report['editor_slots_reserved']==1
    assert report['required_peak_handles']<=16
    assert not report['supports_close_used']


def test_less_capacity_reduces_concurrency_not_runtime(compact_root):
    service,runner=ready(compact_root,count=6,limit=12,concurrency=6)
    report=runner.capacity()
    assert report['actual_author_concurrency']==3
    assert report['ok']
    assert all(s['model']=='gpt-5.6-sol' for s in report['slots'])


def test_minimum_pool_impossible_blocks_without_mutation(compact_root):
    service,runner=ready(compact_root,limit=9)
    report=runner.tick()
    assert report['status']=='blocked'
    assert service.store.rows('SELECT * FROM pool_slots')==[]


def test_speculative_slots_do_not_create_reviewers(compact_root):
    service,runner=ready(compact_root)
    result=runner.tick()
    assert len(result['requests'])==6
    assert all(r['runtime']['family']=='author' for r in result['requests'])
    assert len(service.store.rows("SELECT * FROM pool_slots WHERE kind='review' AND state='pending'"))==5


def test_duplicate_ticks_do_not_repeat_launches(compact_root):
    service,runner=ready(compact_root,count=2)
    first=runner.tick();assert len(first['requests'])==2
    second=runner.tick();assert second['requests']==[]
    assert len(second['outstanding']['creations'])==2


def test_creation_receipt_is_idempotent_and_runtime_fixed(compact_root):
    service,runner=ready(compact_root,count=1)
    request=runner.tick()['requests'][0]
    with pytest.raises(MPresError,match='runtime'):runner.attach(request['slot_id'],'wrong','other-model','low','receipt')
    spec=request['runtime']
    assert not runner.attach(request['slot_id'],'h1',spec['model'],spec['reasoning_effort'],'receipt')['already_attached']
    assert runner.attach(request['slot_id'],'h1',spec['model'],spec['reasoning_effort'],'receipt')['already_attached']
    with pytest.raises(MPresError):runner.attach(request['slot_id'],'h2',spec['model'],spec['reasoning_effort'],'receipt')


def test_missing_host_handle_not_treated_as_closed(compact_root):
    service,runner=ready(compact_root,count=1)
    attach_requests(runner,runner.tick())
    runner.observe_host(host([]))
    report=runner.capacity()
    assert not report['ok'] and report['missing_sessions']
    assert service.store.rows('SELECT state FROM sessions')[0]['state']=='open'


def test_creation_uncertainty_is_durable(compact_root):
    service,runner=ready(compact_root,count=1)
    request=runner.tick()['requests'][0]
    runner.creation_uncertain(request['slot_id'],'lost reply')
    assert runner.tick()['requests']==[]
    assert runner.outstanding()['creations'][0]['state']=='uncertain'


def test_bridge_claims_once_and_compiles_only_local_brief(compact_root):
    service,runner=ready(compact_root,count=2)
    handles=attach_requests(runner,runner.tick())
    result=runner.tick()
    assert len(result['requests'])==2
    for request in result['requests']:
        assert request['operation']=='run'
        assert request['packet']['unit']['brief']
        assert 'TASK.md' not in json.dumps(request['packet'])
        assert request['runtime']['reasoning_effort']=='medium'
    assert runner.tick()['requests']==[]


def test_concurrent_runners_do_not_duplicate_work(compact_root):
    service,runner=ready(compact_root,count=2)
    attach_requests(runner,runner.tick())
    with ThreadPoolExecutor(max_workers=2) as pool:
        results=list(pool.map(lambda _:Runner(service.task).tick(),range(2)))
    run_requests=[r for v in results for r in v['requests'] if r['operation']=='run']
    assert len(run_requests)==2
    assert len({r['attempt_id'] for r in run_requests})==2


def test_context_overflow_blocks_before_external_execution(compact_root):
    service,runner=ready(compact_root,count=1)
    attach_requests(runner,runner.tick())
    original=runner.packet
    def failing(*args):raise MPresError('Context too large')
    runner.packet=failing
    result=runner.tick()
    assert result['requests']==[]
    assert service.jobs()[0]['state']=='blocked'
    assert service.store.rows('SELECT state FROM attempts')[0]['state']=='failed'
    assert service.store.rows('SELECT state FROM sessions')[0]['state']=='open'


def test_ambiguous_run_can_only_reconcile_same_attempt(compact_root):
    service,runner=ready(compact_root,count=1)
    attach_requests(runner,runner.tick())
    request=runner.tick()['requests'][0]
    service.uncertain(request['attempt_id'],'lost external result')
    assert runner.tick()['requests']==[]
    out=Path(request['packet']['writable_directory']);(out/'presentation.md').write_text('# Recovered content')
    response={'runtime':request['runtime'],'receipt':'actual-execution-recovered','source_dir':'output','result':{'summary':'Recovered same provider call'},'usage':[{'call_id':'actual-recovered-call','counters':{}}]}
    runner.accept(request,response)
    assert service.jobs()[0]['state']=='succeeded'
    assert runner.accept(request,response)['already_submitted']


def test_provider_output_cannot_escape_attempt_workspace(compact_root):
    service,runner=ready(compact_root,count=1)
    attach_requests(runner,runner.tick());request=runner.tick()['requests'][0]
    with pytest.raises(MPresError):runner.accept(request,{'receipt':'done','source_dir':'../../elsewhere','result':{'summary':'Done'}})


def test_changed_duplicate_source_is_rejected(compact_root):
    service=prepare(compact_root);a,_=completed(service)
    source=source_for(service);(source/'presentation.md').write_text('Different content')
    with pytest.raises(MPresError,match='source differs'):service.submit(a['id'],{'summary':'A worked example'},source=source)


def test_actual_provider_inventory_can_reduce_configured_capacity(compact_root):
    service,runner=ready(compact_root,limit=16)
    runner.observe_host(host(limit=11))
    report=runner.capacity()
    assert report['limit']==11 and report['actual_author_concurrency']==2


def test_stale_capability_receipt_blocks_admission(compact_root):
    service,runner=ready(compact_root)
    with service.store.transaction() as c:c.execute("UPDATE runtime_host SET observed_at='2000-01-01T00:00:00Z'")
    assert runner.tick()['requests'][0]['operation']=='capabilities'


def test_database_v1_upgrade_preserves_confirmed_profile(compact_root):
    service=prepare(compact_root)
    before=service.store.rows('SELECT * FROM configs')
    c=service.store.connect();c.execute('DROP TABLE audience_steps');c.execute('DROP TABLE release_versions');c.execute('DROP TABLE repair_jobs');c.execute('DROP TABLE repair_targets');c.execute('DROP TABLE attempt_briefings');c.execute('DROP TABLE feedback_rules');c.execute('DROP TABLE releases');c.execute('DROP TABLE decks');c.execute('DROP TABLE repair_cases');c.execute('DROP TABLE gate_runs');c.execute('DROP TABLE runtime_host');c.execute('DROP TABLE pool_slots');c.execute('ALTER TABLE task DROP COLUMN author_slots_limit');c.execute('PRAGMA user_version=1');c.close()
    assert service.store.rows('SELECT * FROM configs')==before
    c=service.store.connect();assert c.execute('PRAGMA user_version').fetchone()[0]==7;c.close()


def test_command_adapter_runs_jobs_without_main_scheduling(compact_root,tmp_path):
    service=Service.create(compact_root,'command','Command fixture')
    from feedback_fixtures import infrastructure_only
    infrastructure_only(service)
    config=read_yaml(service.task/'task.yaml'); config['workflow']='authoring'
    config['provider'].update(mode='command',command=[sys.executable,str(Path(__file__).with_name('fake_provider.py')),str(tmp_path/'provider.sqlite3')],handle_limit=16,external_handles=1)
    config['presentations']=[{'id':'p01','title':'Test','units':[{'id':f'l{i}','title':'Unit','brief':'Explain one semantic point.','sources':[]} for i in range(3)]}]
    write_yaml_atomic(service.task/'task.yaml',config);service.present();service.confirm('user')
    runner=Runner(service.task);result=runner.run(cycles=10,interval=0)
    assert all(j['state']=='succeeded' for j in service.jobs())
    assert service.metrics()['calls_observed']==3
    assert service.metrics()['fields']['total_tokens']['total']==315
    assert service.status()['status']=='running'  # Drafts are NOT a final deck.
    assert not list((service.task/'deliverables').iterdir())
    assert result['release_pipeline_enabled'] is False
    assert service.store.rows('SELECT count(*) n FROM sessions')[0]['n']==3


def test_actual_provider_fallback_runtime_rejected(compact_root):
    service,runner=ready(compact_root,count=1)
    attach_requests(runner,runner.tick());request=runner.tick()['requests'][0]
    with pytest.raises(MPresError,match='fallback model'):
        runner.accept(request,{'receipt':'actual-run','runtime':{'model':'wrong-model','reasoning_effort':'low'},'result':{'summary':'Wrong runtime'}})
    assert service.jobs()[0]['state']=='running'
    assert service.store.rows('SELECT * FROM artifacts')==[]


def test_concurrency_guard_is_inside_binding_transaction(compact_root):
    service=prepare(compact_root,count=2)
    register(service,'h1');register(service,'h2')
    with service.store.transaction() as c:c.execute('UPDATE task SET author_slots_limit=1')
    jobs=service.jobs()
    def bind(pair):
        try:service.bind(pair[0]['id'],pair[1]);return True
        except MPresError:return False
    with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(bind,zip(jobs,['h1','h2'])))
    assert results.count(True)==1


def test_runtime_overrides_reserve_distinct_future_reviewer_slots(compact_root):
    service=Service.create(compact_root,'overrides','Overrides')
    config=read_yaml(service.task/'task.yaml'); config['workflow']='authoring';config['provider']['handle_limit']=16
    config['presentations']=[{'id':'p01','title':'Test','units':[{'id':'l01','title':'Lesson','brief':'Explain dimensions.','sources':[]}]}]
    profile=read_yaml(service.task/'TASK-RUNTIME-PROFILE.yaml')
    profile['reviewer_channel_overrides']['domain_accuracy']={'model':'luna','reasoning_effort':'medium'}
    write_yaml_atomic(service.task/'task.yaml',config);write_yaml_atomic(service.task/'TASK-RUNTIME-PROFILE.yaml',profile)
    service.present();service.confirm('user');runner=Runner(service.task);runner.observe_host(host())
    domain=[s for s in runner.capacity()['slots'] if s['channel']=='domain_accuracy'][0]
    assert (domain['model'],domain['effort'])==('luna','medium')


def test_missing_token_collector_blocks_startup(compact_root):
    service,runner=ready(compact_root)
    report=host();report['usage_reporting']=False;runner.observe_host(report)
    tick=runner.tick()
    assert tick['status']=='blocked' and tick['requests']==[]
    assert 'token' in tick['capacity']['reason']


def test_provider_creation_failure_is_not_retried(compact_root):
    service,runner=ready(compact_root,count=1)
    def invoke(request):
        if request['operation']=='capabilities':return host()
        raise RuntimeError('connection dropped after provider may have accepted request')
    runner.invoke=invoke
    first=runner.run_once()
    assert first['results'][0]['status']=='uncertain'
    second=runner.run_once()
    assert second['requests']==[] and second['status']=='blocked'
    assert len(service.store.rows("SELECT * FROM pool_slots WHERE state='uncertain'"))==1


def test_promised_token_data_cannot_disappear(compact_root):
    service,runner=ready(compact_root,count=1)
    attach_requests(runner,runner.tick());request=runner.tick()['requests'][0]
    output=Path(request['packet']['writable_directory']);(output/'presentation.md').write_text('# Result')
    with pytest.raises(MPresError,match='no call receipts'):
        runner.accept(request,{'receipt':'actual-executed','runtime':request['runtime'],'source_dir':'output','result':{'summary':'Done'}})
    assert service.jobs()[0]['state']=='running'
    assert service.store.rows('SELECT * FROM artifacts')==[]
