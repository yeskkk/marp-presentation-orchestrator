"""Additional safeguards on top of the unchanged v0.9.4-v0.9.6 tests."""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from mpres.control.compatibility import open_task
from mpres.control.cost_report import report
from mpres.control.cost_scope import lineage
from mpres.control.rolling import drive
from mpres.control.store import Store
from mpres.control.telemetry import observed_wait, pin_job
from mpres.util import MPresError
from test_relational_control import compact_root, prepare
from test_v093_operations import admitted


def test_migration_13_adds_only_new_tables_and_keeps_business_state(compact_root):
    s, r, q = admitted(compact_root)
    tables = ['configs', 'jobs', 'attempts', 'usage', 'host_requests',
              'current_checkpoints', 'retention_tombstones', 'current_retention_policy']
    before = {t: s.store.rows('SELECT * FROM ' + t) for t in tables}
    db = s.task / '.mpres/task.sqlite3'
    with sqlite3.connect(db) as conn:
        conn.execute('DROP TABLE scheduler_observation')
        conn.execute('DROP TABLE job_cost_context')
        conn.execute('PRAGMA user_version=13')
    state = open_task(s.task)
    assert state['schema_version'] == Store.SCHEMA_VERSION == 14
    assert {t: s.store.rows('SELECT * FROM ' + t) for t in tables} == before
    assert not s.store.rows('SELECT * FROM job_cost_context')  # no retroactive pins
    assert not open_task(s.task)['compatibility_changed']


def test_13_report_is_read_only_and_does_not_require_migration(compact_root):
    s, r, q = admitted(compact_root)
    db = s.task / '.mpres/task.sqlite3'
    totals = report(s.task)['counters']
    with sqlite3.connect(db) as conn:
        conn.execute('DROP TABLE scheduler_observation')
        conn.execute('DROP TABLE job_cost_context')
        conn.execute('PRAGMA user_version=13')
    original = db.read_bytes()
    assert report(s.task)['counters'] == totals
    assert db.read_bytes() == original


def test_batch_at_reservation_is_immutable_and_filters_intersect(compact_root):
    s, r, q = admitted(compact_root)
    # A completed earlier attempt must NOT be attributed to a later active batch.
    jid = s.attempt(q['attempt_id'])['job_id']
    pinned = s.store.rows('SELECT * FROM job_cost_context WHERE job_id=?', (jid,))[0]
    assert pinned['batch_id'] is None
    job = s.job(jid)
    with s.store.transaction() as conn:
        cfg = conn.execute('SELECT config_id FROM task').fetchone()[0]
        conn.execute("INSERT INTO decks(presentation,config_id,ordinal,phase) VALUES('p01',?,0,'units')", (cfg,))
        # Explicit relational fixture, not a model receipt or a production bypass.
        conn.execute("INSERT INTO production_batches VALUES('b-fixture',?,'running','{}','2026-01-01Z',NULL,NULL)", (cfg,))
        conn.execute("INSERT INTO production_batch_targets VALUES('b-fixture','p01',0)")
        assert pin_job(conn, job) == pinned
    assert report(s.task, batch_id='b-fixture')['calls_observed'] == 0
    assert report(s.task, ['p01'], until='2000-01-01T00:00:00+08:00')['calls_observed'] == 0


def test_arbitrary_key_occurrence_is_not_a_repair_case_link():
    jobs = {'j': {'id': 'j', 'key': 'unrelated:case-1:stuff', 'kind': 'review', 'input_artifact_id': None}}
    result = lineage(jobs, {}, {}, [], [], {}, {'case-1': {}})
    assert result['j']['repair_case_id'] is None


def test_duplicate_group_rejected_before_any_executor_call():
    issued = []
    result = drive(lambda _: {'requests': [{'request_id': 'same'}, {'request_id': 'same'}]},
                   lambda q: issued.append(q), workers=2, cycles=2)
    assert not issued
    assert result['rolling']['stopped_on_failure'] and 'duplicate' in result['reason']


def test_identity_mismatch_stops_admission_and_keeps_original_id():
    result = drive(lambda _: {'requests': [{'request_id': 'original'}]},
                   lambda q: {'request_id': 'wrong', 'status': 'accepted'}, workers=1, cycles=3)
    assert result['rolling']['admission_ticks'] == 1
    assert result['results'][0]['request_id'] == 'original'
    assert result['results'][0]['status'] == 'executor_failed'


def test_terminal_block_stops_ticks_but_drains_existing_request():
    stage = 0
    peer_finished = threading.Event()
    def admit(active):
        nonlocal stage
        stage += 1
        if stage == 1:
            return {'requests': [{'request_id': 'slow'}, {'request_id': 'fast'}]}
        assert 'slow' in active
        return {'status': 'blocked', 'requests': [], 'reason': 'fixture resource block'}
    def execute(q):
        if q['request_id'] == 'slow':
            time.sleep(.08)
            peer_finished.set()
        return {'request_id': q['request_id'], 'status': 'accepted'}
    result = drive(admit, execute, workers=2, cycles=8)
    assert stage == 2 and peer_finished.is_set()
    assert result['status'] == 'blocked' and len(result['results']) == 2


def test_open_wait_unknown_and_closed_interval_clips_requested_time(compact_root, monkeypatch):
    s, r, q = admitted(compact_root)
    now = ['2026-09-16T00:00:00Z']
    import mpres.control.telemetry as telemetry
    monkeypatch.setattr(telemetry, 'utc_now', lambda: now[0])
    observed_wait(s, {'status': 'blocked', 'capacity': {'ok': False}})
    data = report(s.task)
    row = [w for w in data['automatic_waits'] if w['reason'] == 'capacity'][-1]
    assert row['open'] and row['seconds'] is None
    now[0] = '2026-09-16T00:00:20Z'
    observed_wait(s, {'status': 'completed', 'requests': []})
    data = report(s.task, since='2026-09-16T00:00:05Z', until='2026-09-16T00:00:10Z')
    row = [w for w in data['automatic_waits'] if w['reason'] == 'capacity'][-1]
    assert not row['open'] and row['seconds'] == 5


def test_global_wait_not_charged_to_arbitrary_individual_deck(compact_root, monkeypatch):
    s, r, q = admitted(compact_root)
    now = ['2026-09-16T00:00:00Z']
    import mpres.control.telemetry as telemetry
    monkeypatch.setattr(telemetry, 'utc_now', lambda: now[0])
    observed_wait(s, {'status': 'blocked', 'capacity': {'ok': False}})
    now[0] = '2026-09-16T00:00:10Z'
    observed_wait(s, {'status': 'completed'})
    assert any(w['reason'] == 'capacity' for w in report(s.task)['automatic_waits'])
    assert not any(w['reason'] == 'capacity' for w in report(s.task, ['p01'])['automatic_waits'])


def test_scope_metadata_is_not_added_to_worker_prompt(compact_root):
    s, r, q = admitted(compact_root)
    assert 'cost_context' not in q['packet']
    assert s.store.rows('SELECT * FROM job_cost_context')


def test_bridge_refuses_v096_collected_requests_before_transport():
    from mpres.control.codex_bridge import CodexBridge
    b = CodexBridge.__new__(CodexBridge)
    # The unchanged v0.9.6 early guard must execute before any missing runtime.
    with pytest.raises(MPresError, match='pruned'):
        b.execute({'_current_checkpoint': {'id': 'c'}, 'operation': 'run', 'request_id': 'old'})


def test_current_release_missing_reference_is_not_silently_dropped(compact_root, native_double):
    from test_confirmed_repairs import completed
    from mpres.control.compatibility import current_state
    s, h, r = completed(compact_root, decks=1)
    assert current_state(s.task)['current_releases']
    # Deliberately corrupt an isolated fixture to test the pre-existing v0.9.6
    # defensive check. Never suppress FKs in the production code.
    with sqlite3.connect(s.task / '.mpres/task.sqlite3') as conn:
        conn.execute('PRAGMA foreign_keys=OFF')
        conn.execute("DELETE FROM decks WHERE presentation='p01'")
    with pytest.raises(MPresError, match='missing artifact/deck reference'):
        current_state(s.task)


from test_deck_workflow import native_double


def test_actual_runner_admits_independent_editor_before_slow_peer(compact_root, native_double):
    from mpres.control.codex_bridge import CodexBridge, Journal
    from mpres.control.runner import Runner
    from test_deck_workflow import full_task, Host
    service = full_task(compact_root, decks=2, units=1)
    host = Host()
    editor_started = threading.Event()
    b = CodexBridge.__new__(CodexBridge)
    b.task = service.task
    b.runner = Runner(service.task)
    b.journal = Journal(service.task)
    b.capabilities = lambda: host({'operation': 'capabilities'})
    def execute(q):
        packet = q.get('packet', {})
        if q['operation'] == 'run' and packet.get('kind') == 'write' and packet.get('presentation') == 'p02':
            assert editor_started.wait(10), 'Independent p01 editor was blocked by unfinished p02 writer'
        if q['operation'] == 'run' and packet.get('kind') == 'edit' and packet.get('presentation') == 'p01':
            editor_started.set()
        result = host(q)
        if q['operation'] == 'run' and packet.get('kind') == 'write':
            # Two short pages keep this deterministic PDF fixture above the
            # existing real inspector's minimum-file-size rule.
            md = Path(packet['writable_directory']) / 'presentation.md'
            sid = f"{packet['presentation']}-{packet['unit']['id']}-s2"
            with md.open('a') as output:
                output.write(f'\n---\n<!-- slide-id: {sid} -->\n<!-- _class: core -->\n# Example\n\nCompare the two coordinates.\n')
        return result
    b.execute = execute  # deterministic semantic host; not a real model test
    try:
        value = b.drive(120)
    finally:
        b.journal.close()
    assert editor_started.is_set() and service.status()['status'] == 'completed', value
    assert not service.store.rows("SELECT * FROM host_requests WHERE state<>'accepted'")
    assert value['rolling']['whole_batch_barrier'] is False
