import json
from pathlib import Path
from contextlib import closing
import pytest
from mpres.control.cost_report import report,render,counters,union
from mpres.control.supervision import terminal,pending,acknowledge,wait_start,wait_end
from mpres.control.store import event
from mpres.control.cli import main
from mpres.util import MPresError
from test_relational_control import compact_root
from test_job_runner import ready
from test_deck_workflow import Host

def admitted(root):
    s,r=ready(root,count=1);host=Host()
    for q in r.tick()['requests']:r.accept(q,host(q))
    r.observe_host(host({'operation':'capabilities'}));q=r.tick()['requests'][0]
    r.accept(q,host(q))
    return s,r,q

def test_counters_do_not_add_subsets_or_replace_missing_with_zero():
    x=counters([{'input_tokens':100,'cached_input_tokens':80,'output_tokens':5,'reasoning_tokens':2,'total_tokens':105}, {'input_tokens':None,'cached_input_tokens':None,'output_tokens':0,'reasoning_tokens':None,'total_tokens':None}])
    assert x['total_tokens']=={'total':None,'known_sum':105,'known_records':1,'unknown_records':1}
    assert x['uncached_input_tokens']['known_sum']==20
    assert x['output_tokens']['total']==5

def test_parallel_time_is_interval_union_not_summed_wall_time():
    assert union([(0,10),(5,20),(30,40)])==[(0,20),(30,40)]

def test_report_readonly_unknown_duration_and_exact_usage(compact_root,tmp_path):
    s,r,q=admitted(compact_root);db=s.task/'.mpres/task.sqlite3';before=db.read_bytes()
    data=report(s.task,['p01'])
    assert data['calls_observed']>0
    assert data['timing']['provider_sum_seconds'] is None
    assert data['timing']['adapter_observed_sum_seconds'] is None
    assert data['coverage']['calls_with_provider_timestamps']==0
    assert db.read_bytes()==before
    assert '未记录' in render(data,'md')
    assert render(data,'csv').startswith('presentation,')
    assert json.loads(render(data))['calls_observed']==data['calls_observed']
    with pytest.raises(MPresError):report(s.task,['not-a-deck'])

def test_report_cli_does_not_write_task_or_overwrite_existing_file(compact_root,tmp_path,capsys):
    s,r,q=admitted(compact_root);db=s.task/'.mpres/task.sqlite3';before=db.read_bytes();out=tmp_path/'report.md'
    args=['--root',str(compact_root),'report','usage','runner','--format','md','--output',str(out)]
    assert main(args)==0 and out.is_file()
    assert main(args)==2
    assert db.read_bytes()==before

def test_handoff_is_deduplicated_ack_never_changes_execution(compact_root):
    s,r,q=admitted(compact_root);before=s.store.rows('SELECT * FROM attempts')
    fail={'status':'blocked','results':[{'request_id':q['request_id'],'status':'uncertain','error':'test interruption'}]}
    x=terminal(s,fail,'test');y=terminal(s,fail,'test')
    assert x['recommended_exit_code']==3 and not x['handoff']['host_push']
    assert x['handoff']['handoff_id']==y['handoff']['handoff_id']
    assert len(pending(s)['pending'])==1
    acknowledge(s,x['handoff']['handoff_id'],by='main',note='Investigate exact original request; no resubmit')
    assert not pending(s)['pending'] and s.store.rows('SELECT * FROM attempts')==before
    with pytest.raises(MPresError):acknowledge(s,'missing',by='main',note='test')

def test_explicit_wait_reason_is_not_guessed_from_event_gaps(compact_root):
    s,r,q=admitted(compact_root)
    w=wait_start(s,reason='resource',by='main',note='Missing local textbook',presentation='p01')
    a=report(s.task,['p01']);assert a['waits'][0]['open'] and a['waits'][0]['seconds'] is None
    wait_end(s,w['wait_id'],by='main')
    a=report(s.task,['p01']);assert not a['waits'][0]['open'] and a['waits'][0]['reason']=='resource'
    assert wait_end(s,w['wait_id'],by='main')['already_ended']
    with pytest.raises(MPresError):wait_start(s,reason='guessed-idle',by='main',note='test')

def test_runner_foreground_failure_becomes_main_handoff(compact_root,monkeypatch):
    s,r,q=admitted(compact_root)
    monkeypatch.setattr(r,'run_once',lambda:{'status':'blocked','reason':'test','requests':[],'results':[]})
    value=r.run(cycles=1,interval=0)
    assert value['needs_main_attention'] and pending(s)['pending']

def test_runner_exception_is_returned_nonzero_with_durable_handoff(compact_root,monkeypatch,capsys):
    s,r,q=admitted(compact_root)
    from mpres.control.runner import Runner
    def broken(*args,**kwargs):raise MPresError('test terminal exception')
    monkeypatch.setattr(Runner,'run',broken)
    assert main(['--root',str(compact_root),'runner','run','runner','--cycles','1'])==2
    data=json.loads(capsys.readouterr().out)
    assert data['needs_main_attention'] and pending(s)['pending']


def test_usage_report_schema_covers_generated_not_model_output(compact_root):
    from jsonschema import Draft202012Validator
    from mpres.control import cost_report
    s,r,q=admitted(compact_root)
    schema=json.loads((Path(cost_report.__file__).parent/'schemas/usage-report.json').read_text())
    Draft202012Validator(schema).validate(report(s.task))

def test_keyboard_interrupt_handoff_does_not_invent_completion(compact_root,monkeypatch,capsys):
    s,r,q=admitted(compact_root);before=s.store.rows('SELECT * FROM attempts')
    from mpres.control.runner import Runner
    def stop(*args,**kwargs):raise KeyboardInterrupt()
    monkeypatch.setattr(Runner,'run',stop)
    assert main(['--root',str(compact_root),'runner','run','runner'])==130
    assert json.loads(capsys.readouterr().out)['interrupted']
    assert pending(s)['pending'] and s.store.rows('SELECT * FROM attempts')==before

def test_main_only_operations_skill_does_not_expand_worker_surface():
    # Role routing itself is exercised by the existing guidance tests. The
    # administrative guide must not be an always-loaded shared fragment.
    from mpres.control import guidance
    text=Path(guidance.__file__).read_text()
    assert 'runtime-operations' not in text
