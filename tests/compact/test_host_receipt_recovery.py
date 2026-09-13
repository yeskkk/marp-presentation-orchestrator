from __future__ import annotations

import copy
import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from mpres.control.host_journal import HostJournal
from mpres.control.runner import Runner
from mpres.control.store import Store
from mpres.util import MPresError
from test_relational_control import compact_root
from test_audience_reading import audience_ready
from test_deck_workflow import native_double
from test_job_runner import ready, attach_requests


def test_response_saved_before_semantic_reject_and_usage_not_lost(compact_root,native_double):
    service,runner,host,request=audience_ready(compact_root)
    response=host(request)
    response['result']['observations']=[{'slide_id':request['packet']['read_slide_ids'][0],
        'quote':'not in this source','learning_impact':'fixture'}]
    with pytest.raises(MPresError,match='invented'):
        runner.accept(request,response)
    stored=service.store.rows('SELECT response_json FROM host_responses WHERE request_id=?',(request['request_id'],))[0]
    assert json.loads(stored['response_json'])==response
    assert service.store.rows('SELECT 1 FROM usage WHERE attempt_id=?',(request['attempt_id'],))
    assert service.attempt(request['attempt_id'])['state']=='reserved'
    assert runner.tick()['status']=='blocked'
    assert len(HostJournal(service).pending())==1
    assert service.store.rows("SELECT state FROM audience_steps WHERE attempt_id=? AND sequence=0",(request['attempt_id'],))[0]['state']=='dispatched'


def test_replay_saved_valid_response_after_parser_failure_without_model(compact_root,native_double,monkeypatch):
    service,runner,host,request=audience_ready(compact_root)
    response=host(request)
    original=runner._accept
    def parser_bug(*args):raise MPresError('deterministic receiver bug')
    monkeypatch.setattr(runner,'_accept',parser_bug)
    with pytest.raises(MPresError,match='receiver bug'): runner.accept(request,response)
    usage=service.store.rows('SELECT * FROM usage ORDER BY attempt_id,call_id')
    monkeypatch.setattr(runner,'_accept',original)
    def no_model(*args):raise AssertionError('replay must not invoke a model')
    monkeypatch.setattr(runner,'invoke',no_model)
    assert runner.replay(request['request_id'])['sequence']==0
    assert not HostJournal(service).pending()
    assert runner.replay(request['request_id'])['already_recorded']
    assert service.store.rows('SELECT * FROM usage ORDER BY attempt_id,call_id')==usage


def test_conflicting_saved_response_not_overwritten(compact_root,native_double):
    service,runner,host,request=audience_ready(compact_root)
    response=host(request);runner.accept(request,response)
    changed=copy.deepcopy(response);changed['result']['summary']='different'
    with pytest.raises(MPresError,match='Conflicting'):runner.accept(request,changed)
    assert HostJournal(service).replay_data(request['request_id'])[1]==response
    assert service.store.rows('SELECT state FROM host_requests WHERE request_id=?',(request['request_id'],))[0]['state']=='accepted'


def test_other_session_cannot_submit_saved_request(compact_root,native_double):
    service,runner,host,request=audience_ready(compact_root)
    changed=copy.deepcopy(request);changed['session_id']='somebody-else'
    with pytest.raises(MPresError):runner.accept(changed,host(request))
    assert service.store.rows('SELECT * FROM host_responses WHERE request_id=?',(request['request_id'],))==[]


def test_unknown_request_never_auto_reissues(compact_root):
    service,runner=ready(compact_root,count=1)
    with pytest.raises(MPresError,match='No saved response'):runner.replay('not-issued')
    assert service.store.rows('SELECT * FROM host_responses')==[]


def test_same_response_concurrent_replay_only_once(compact_root,native_double):
    service,runner,host,request=audience_ready(compact_root)
    response=host(request)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results=list(pool.map(lambda _:Runner(service.task).accept(request,response),range(2)))
    assert sum(not r['already_recorded'] for r in results)==1
    assert len(service.store.rows('SELECT * FROM host_responses WHERE request_id=?',(request['request_id'],)))==1


def test_undispatched_local_input_failure_resumes_same_attempt(compact_root,monkeypatch):
    service,runner=ready(compact_root,count=1)
    attach_requests(runner,runner.tick())
    original=runner.packet
    monkeypatch.setattr(runner,'packet',lambda *a: (_ for _ in ()).throw(MPresError('budget')))
    assert runner.tick()['requests']==[]
    attempt=service.store.rows('SELECT * FROM attempts')[0]
    assert attempt['state']=='reserved' and attempt['finished_at'] is None
    assert runner.tick()['requests']==[]
    monkeypatch.setattr(runner,'packet',original)
    runner.resume_input(attempt['id'])
    request=runner.tick()['requests'][0]
    assert request['attempt_id']==attempt['id'] and request['operation']=='run'
    assert len(service.store.rows('SELECT * FROM attempts'))==1
    with pytest.raises(MPresError):runner.resume_input(attempt['id'])


def test_final_packet_block_retains_all_completed_readings(compact_root,native_double,monkeypatch):
    service,runner,host,request=audience_ready(compact_root,pages=14)
    original=runner.packet
    def fail_final(job,*args):
        if job['kind']=='review' and job['channel']=='audience':raise MPresError('final packet over budget')
        return original(job,*args)
    monkeypatch.setattr(runner,'packet',fail_final)
    while request:
        runner.accept(request,host(request))
        reqs=runner.tick()['requests']
        request=reqs[0] if reqs else None
    attempt_id=service.store.rows("SELECT a.id FROM attempts a JOIN jobs j ON j.id=a.job_id WHERE j.channel='audience'")[0]['id']
    steps=service.store.rows('SELECT * FROM audience_steps WHERE attempt_id=? ORDER BY sequence',(attempt_id,))
    assert len(steps)==4 and all(s['state']=='completed' for s in steps)
    assert service.attempt(attempt_id)['state']=='reserved'
    monkeypatch.setattr(runner,'packet',original)
    runner.resume_input(attempt_id)
    req=runner.tick()['requests'][0]
    assert req['operation']=='run' and req['attempt_id']==attempt_id
    assert service.store.rows('SELECT * FROM audience_steps WHERE attempt_id=? ORDER BY sequence',(attempt_id,))==steps


def test_input_resume_refuses_issued_step(compact_root,native_double):
    service,runner,host,request=audience_ready(compact_root)
    with pytest.raises(MPresError):runner.resume_input(request['attempt_id'])
    assert runner.tick()['requests']==[]


def test_bad_runtime_raw_saved_but_not_usage_or_task_context(compact_root,native_double):
    service,runner,host,request=audience_ready(compact_root)
    response=copy.deepcopy(host(request));response['runtime']['model']='forbidden-model'
    usage=service.store.rows('SELECT * FROM usage ORDER BY attempt_id,call_id')
    with pytest.raises(MPresError,match='runtime'):runner.accept(request,response)
    assert HostJournal(service).replay_data(request['request_id'])[1]==response
    assert service.store.rows('SELECT * FROM usage ORDER BY attempt_id,call_id')==usage


def test_raw_journal_migration_is_additive_and_idempotent(compact_root):
    service,runner=ready(compact_root,count=1)
    saved={t:service.store.rows(f'SELECT * FROM {t}') for t in ('configs','jobs','events')}
    conn=service.store.connect()
    conn.execute('DROP TABLE IF EXISTS plan_item_origins');conn.execute('DROP TABLE IF EXISTS delivery_parts');conn.execute('DROP TABLE IF EXISTS plan_changes');conn.execute('DROP TABLE IF EXISTS production_batch_targets');conn.execute('DROP TABLE IF EXISTS production_batches');conn.execute('DROP TABLE IF EXISTS policy_values');conn.execute('DROP TABLE IF EXISTS policy_cursor');conn.execute('DROP INDEX IF EXISTS events_kind_id');conn.execute('DROP TABLE IF EXISTS host_responses');conn.execute('DROP TABLE IF EXISTS host_requests');conn.execute('DROP INDEX IF EXISTS events_kind_job_id');conn.execute('DROP INDEX IF EXISTS events_request_kind');
    conn.execute('DROP TABLE IF EXISTS host_responses');conn.execute('DROP TABLE IF EXISTS host_requests')
    conn.execute('DROP INDEX IF EXISTS events_kind_job_id');conn.execute('DROP INDEX IF EXISTS events_request_kind')
    conn.execute('PRAGMA user_version=8');conn.close()
    for _ in range(2):
        conn=Store(service.task).connect()
        assert conn.execute('PRAGMA user_version').fetchone()[0]==11
        assert conn.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
        assert not conn.execute('PRAGMA foreign_key_check').fetchall()
        conn.close()
    assert {t:service.store.rows(f'SELECT * FROM {t}') for t in saved}==saved
