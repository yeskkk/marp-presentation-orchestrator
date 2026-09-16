"""Deterministic local protocol tests; never invokes a provider."""
import json,threading,time
from pathlib import Path
import pytest
from mpres.control.rolling import drive
from mpres.control.cost_report import report
from mpres.control.cost_scope import boundary,lineage
from mpres.control.telemetry import observed_wait
from mpres.control.wire_checkpoint import compact_envelope
from mpres.util import MPresError
from test_relational_control import compact_root
from test_v093_operations import admitted


def test_ready_successor_runs_before_unrelated_slow_request_finishes():
    next_started=threading.Event();order=[];lock=threading.Lock();stage=0
    def admit(active):
        nonlocal stage
        stage+=1
        if stage==1:return {'status':'requests_ready','requests':[{'request_id':'slow'},{'request_id':'fast'}]}
        if stage==2:
            assert active==frozenset({'slow'})
            return {'status':'requests_ready','requests':[{'request_id':'next'}]}
        return {'status':'completed','requests':[]}
    def execute(q):
        rid=q['request_id']
        if rid=='slow':assert next_started.wait(5),'A whole-batch barrier prevented independent successor'
        if rid=='next':next_started.set()
        with lock:order.append(rid)
        return {'request_id':rid,'status':'accepted'}
    result=drive(admit,execute,workers=2,cycles=10)
    assert order.index('next')<order.index('slow')
    assert len(result['results'])==3 and not result['rolling']['whole_batch_barrier']


def test_failure_stops_admissions_but_drains_real_operations():
    stage=0;finished=threading.Event()
    def admit(active):
        nonlocal stage
        stage+=1
        return {'status':'requests_ready','requests':[{'request_id':'bad'},{'request_id':'already-sent'}]}
    def execute(q):
        if q['request_id']=='already-sent':time.sleep(.05);finished.set();return {'request_id':q['request_id'],'status':'accepted'}
        return {'request_id':'bad','status':'uncertain','error':'no terminal receipt'}
    value=drive(admit,execute,workers=2,cycles=10)
    assert stage==1 and finished.is_set() and len(value['results'])==2
    assert value['rolling']['stopped_on_failure'] and value['status']=='blocked'


def test_admission_budget_drains_and_never_reissues():
    calls=[]
    value=drive(lambda active:{'status':'requests_ready','requests':[{'request_id':'once'}]},lambda q:(calls.append(q['request_id']) or {'request_id':q['request_id'],'status':'accepted'}),workers=1,cycles=1)
    assert calls==['once'] and value['rolling']['budget_exhausted']
    value=drive(lambda active:{'requests':[{'request_id':'duplicate'}]},lambda q:{'request_id':q['request_id'],'status':'accepted'},workers=1,cycles=3)
    assert len(value['results'])==1 and 'duplicate' in value['reason']


def test_admission_exception_drains_without_cancel_receipts():
    n=0;continued=threading.Event()
    def admit(active):
        nonlocal n
        n+=1
        if n==1:return {'requests':[{'request_id':'slow'},{'request_id':'fast'}]}
        raise MPresError('local gate blocked')
    def execute(q):
        if q['request_id']=='slow':time.sleep(.05);continued.set()
        return {'request_id':q['request_id'],'status':'accepted'}
    v=drive(admit,execute,workers=2,cycles=10)
    assert continued.is_set() and len(v['results'])==2 and 'local gate blocked' in v['reason']


def test_time_filter_whole_records_and_reject_ambiguous_dates(compact_root):
    s,r,q=admitted(compact_root);base=report(s.task);before=(s.task/'.mpres/task.sqlite3').read_bytes()
    assert report(s.task,since='2000-01-01T00:00:00+08:00',until='2099-01-01T00:00:00Z')['counters']==base['counters']
    assert report(s.task,until='2000-01-01T00:00:00Z')['calls_observed']==0
    assert (s.task/'.mpres/task.sqlite3').read_bytes()==before
    for kw in ({'since':'2026-09-15'},{'since':'2026-09-15T00:00:00'},{'since':'2030-01-01T00:00:00Z','until':'2020-01-01T00:00:00Z'},{'case_id':'missing'},{'batch_id':'missing'}):
        with pytest.raises(MPresError):report(s.task,**kw)


def test_new_jobs_pin_context_once_and_not_to_current_deck_history(compact_root):
    s,r,q=admitted(compact_root);pins=s.store.rows('SELECT * FROM job_cost_context')
    assert pins and pins[0]['repair_case_id'] is None
    from mpres.control.telemetry import context
    j=s.job(pins[0]['job_id']);assert context(s,j)==pins[0]
    assert len(s.store.rows('SELECT * FROM job_cost_context'))==len(pins)


def test_exact_lineage_stops_at_new_edit_boundary():
    jobs={i:{'id':i,'key':i,'kind':kind,'input_artifact_id':aid} for i,kind,aid in [('old','edit',None),('review','review','a1'),('new','edit','a1'),('new-review','review','a2')]}
    attempts={'t1':{'job_id':'old'},'t2':{'job_id':'new'}}
    artifacts={'a1':{'attempt_id':'t1'},'a2':{'attempt_id':'t2'}}
    r=lineage(jobs,attempts,artifacts,[{'job_id':'old','case_id':'case-old'}],[],{}, {'case-old':{}})
    assert r['review']['repair_case_id']=='case-old'
    assert r['new']['repair_case_id'] is None and r['new-review']['repair_case_id'] is None


def test_checkpoint_compaction_retains_scope_and_usage_but_not_prompt():
    q={'request_id':'r','attempt_id':'a','operation':'run','packet':{'repair_scope':{'case_id':'c','huge':'private old text'},'cost_context':{'repair_case_id':'c','batch_id':None},'instructions':'old long content'}}
    out=json.loads(compact_envelope(json.dumps(q),'cp'))
    assert out['packet']['repair_scope']=={'case_id':'c'}
    assert 'instructions' not in out['packet']
    assert compact_envelope(json.dumps(out),'other')==json.dumps(out)


def test_wait_events_are_transition_based_not_poll_counts(compact_root,monkeypatch):
    s,r,q=admitted(compact_root)
    import mpres.control.telemetry as t
    now=['2026-09-16T00:00:00Z'];monkeypatch.setattr(t,'utc_now',lambda:now[0])
    observed_wait(s,{'status':'blocked','capacity':{'ok':False}})
    now[0]='2026-09-16T00:00:07Z';observed_wait(s,{'status':'blocked','capacity':{'ok':False}})
    now[0]='2026-09-16T00:00:10Z';observed_wait(s,{'status':'requests_ready','requests':[]})
    closed=[e for e in s.store.rows("SELECT * FROM events WHERE kind='scheduler.wait_closed'") if json.loads(e['detail_json'])['reason']=='capacity']
    assert len(closed)==1
    value=report(s.task)
    found=[v for v in value['automatic_waits'] if v['reason']=='capacity']
    assert len(found)==1 and found[0]['seconds']==10
    before=len(s.store.rows("SELECT * FROM events WHERE kind='scheduler.wait_opened'"))
    observed_wait(s,{'status':'idle_or_waiting','outstanding':{'executions':[{'id':'live','state':'running'}]}},in_flight={'live'})
    assert len(s.store.rows("SELECT * FROM events WHERE kind='scheduler.wait_opened'"))==before
