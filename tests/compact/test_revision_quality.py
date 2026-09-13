from __future__ import annotations
import json
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

from mpres.control.quality import Quality, asset_boundary
from mpres.util import MPresError
from test_relational_control import compact_root, prepare, register, source_for

HEADER = '---\nmarp: true\ntheme: mathist-academic\npaginate: true\nsize: "16:9"\nmath: mathjax\n---\n'
SLIDE = '<!-- slide-id: p01-l01-s1 -->\n<!-- _class: core -->\n# Quantities\n\nA vector $x=(1,2)$ has two coordinates.\n'


def good_source(service):
    source=source_for(service)
    (source/'presentation.md').write_text(HEADER+SLIDE)
    return source


def revision(service, source=None):
    register(service)
    a=service.bind(service.jobs()[0]['id'],'h1')
    service.started(a['id'],'executed')
    return service.submit(a['id'],{'summary':'A concrete quantity example'},source=source or good_source(service))['artifact_id']


def test_source_checks_without_process_documents(compact_root):
    service=prepare(compact_root); aid=revision(service)
    q=Quality(service.task);result=q.inspect(aid)
    assert result['state']=='passed'
    assert {r['name'] for r in service.store.rows('SELECT * FROM checks')}=={'source','math_source','asset_boundary','pages'}
    assert not list(service.task.rglob('SELF-CHECK.md'))
    with pytest.raises(MPresError,match='full'): q.require_pass(aid,'full')


def test_repeated_check_is_noop(compact_root):
    service=prepare(compact_root);aid=revision(service);q=Quality(service.task)
    first=q.inspect(aid);second=q.inspect(aid)
    assert first['id']==second['id'] and second['already_recorded']
    assert len(service.store.rows('SELECT * FROM gate_runs'))==1


@pytest.mark.parametrize('body',[
    HEADER+SLIDE+'\n---\n'+SLIDE,
    HEADER+SLIDE+'\n![escape](../../../etc/passwd)',
    HEADER+SLIDE+'\n<script>alert(1)</script>',
    HEADER+SLIDE+'\n$$ \\begin{pmatrix}1 & 2 $$',
    HEADER+'# No canonical ID or class',
])
def test_invalid_content_never_passes(compact_root,body):
    service=prepare(compact_root);source=good_source(service);(source/'presentation.md').write_text(body)
    try:
        aid=revision(service,source)
    except MPresError as exc:
        assert 'source contract' in str(exc)
        assert not service.store.rows('SELECT * FROM artifacts')
        return  # v0.6.17 rejects forbidden syntax before accepting a revision.
    q=Quality(service.task)
    assert q.inspect(aid)['state']=='failed'
    with pytest.raises(MPresError):q.require_pass(aid,'source')


def test_asset_css_svg_cannot_load_external_resources(compact_root):
    service=prepare(compact_root);source=good_source(service)
    (source/'theme.css').chmod(0o644)
    (source/'theme.css').write_text('/* @theme mathist-academic */ @import "https://bad.invalid/style";')
    assert not asset_boundary(source)['success']
    (source/'theme.css').write_text('/* @theme mathist-academic */')
    (source/'bad.svg').write_text('<svg><image href="file:///etc/passwd"/></svg>')
    assert not asset_boundary(source)['success']


def test_missing_renderer_fails_closed(compact_root,monkeypatch):
    import mpres.control.quality as module
    service=prepare(compact_root);aid=revision(service);q=Quality(service.task)
    def unavailable(*a,**kw): raise MPresError('Pinned renderer is not installed')
    monkeypatch.setattr(module,'require_pinned_marp',unavailable)
    report=q.inspect(aid,'full')
    assert report['state']=='failed' and report['pdf_path'] is None
    assert 'not installed' in report['detail_json']
    assert not list((service.task/'deliverables').iterdir())


def test_concurrent_check_single_execution(compact_root,monkeypatch):
    service=prepare(compact_root);aid=revision(service);q=Quality(service.task)
    entered=threading.Event();release=threading.Event();original=q._run
    def hold(*args): entered.set();release.wait(5);return original(*args)
    monkeypatch.setattr(q,'_run',hold)
    with ThreadPoolExecutor() as pool:
        future=pool.submit(q.inspect,aid)
        assert entered.wait(5)
        other=q.inspect(aid); assert other['state']=='running'
        # SQLite writer is free while the tool runs.
        with service.store.transaction() as c:c.execute('SELECT 1')
        release.set(); assert future.result()['state']=='passed'
    assert len(service.store.rows('SELECT * FROM gate_runs'))==1


def test_retry_preserves_old_result_and_new_revision_is_not_approved(compact_root):
    service=prepare(compact_root);aid=revision(service);q=Quality(service.task)
    first=q.inspect(aid);second=q.inspect(aid,retry=True)
    assert first['id']!=second['id'] and second['sequence']==2
    a=service.bind(service.jobs()[1]['id'],'h1');service.started(a['id'],'second-execution')
    other=service.submit(a['id'],{'summary':'Different lesson'},source=good_source(service))['artifact_id']
    with pytest.raises(MPresError):q.require_pass(other,'source')


def test_migration_v2_retains_every_config(compact_root):
    service=prepare(compact_root);before=service.store.rows('SELECT * FROM configs')
    c=service.store.connect();c.execute('DROP TABLE IF EXISTS plan_item_origins');c.execute('DROP TABLE IF EXISTS delivery_parts');c.execute('DROP TABLE IF EXISTS plan_changes');c.execute('DROP TABLE IF EXISTS production_batch_targets');c.execute('DROP TABLE IF EXISTS production_batches');c.execute('DROP TABLE IF EXISTS policy_values');c.execute('DROP TABLE IF EXISTS policy_cursor');c.execute('DROP INDEX IF EXISTS events_kind_id');c.execute('DROP TABLE IF EXISTS host_responses');c.execute('DROP TABLE IF EXISTS host_requests');c.execute('DROP INDEX IF EXISTS events_kind_job_id');c.execute('DROP INDEX IF EXISTS events_request_kind');c.execute('DROP TABLE audience_steps');c.execute('DROP TABLE release_versions');c.execute('DROP TABLE repair_jobs');c.execute('DROP TABLE repair_targets');c.execute('DROP TABLE attempt_briefings');c.execute('DROP TABLE feedback_rules');c.execute('DROP TABLE releases');c.execute('DROP TABLE decks');c.execute('DROP TABLE repair_cases');c.execute('DROP TABLE gate_runs');c.execute('PRAGMA user_version=2');c.close()
    assert service.store.rows('SELECT * FROM configs')==before
    c=service.store.connect();assert c.execute('PRAGMA user_version').fetchone()[0]==11;c.close()


def test_pending_gate_requires_explicit_interruption_before_retry(compact_root):
    service=prepare(compact_root);aid=revision(service);q=Quality(service.task)
    with service.store.transaction() as c:
        c.execute("INSERT INTO gate_runs VALUES('g-lost',?,'source',1,'running','now',NULL,NULL,NULL)",(aid,))
    assert q.inspect(aid,retry=True)['id']=='g-lost'
    q.interrupt('g-lost','Confirmed the local checker process no longer exists')
    assert q.inspect(aid,retry=True)['state']=='passed'
