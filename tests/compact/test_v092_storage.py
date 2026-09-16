import json
import sqlite3
from contextlib import closing
from pathlib import Path
import pytest
from mpres.control.store import Store,encode
from mpres.control.storage import inspect,plan,apply,compact,_transform
from mpres.control.codex_bridge import Journal
from mpres.control.codex_index import WireIndex
from mpres.control.maintenance_lock import Lease
from mpres.util import MPresError
from test_relational_control import compact_root
from test_job_runner import ready,attach_requests
from test_deck_workflow import Host


def finished(root):
    s,r=ready(root,count=1);host=Host()
    for creation in r.tick()['requests']:r.accept(creation,host(creation))
    r.observe_host(host({'operation':'capabilities'}));q=r.tick()['requests'][0]
    response=host(q);r.accept(q,response)
    with s.store.transaction() as c:
        c.execute("UPDATE attempts SET finished_at='2000-01-01T00:00:00Z'")
        c.execute("UPDATE host_requests SET accepted_at='2000-01-01T00:00:00Z'")
        c.execute("UPDATE sessions SET created_at='2000-01-01T00:00:00Z'")
    j=Journal(s.task);j.enqueue(q);j.before_send(q['request_id'],{'totalTokens':0},q['runtime'])
    thread=q['session_id']
    j.record('out',{'id':'resume','method':'thread/resume','params':{'threadId':thread}})
    j.record('in',{'id':'resume','result':{'model':q['runtime']['model'],'reasoningEffort':q['runtime']['reasoning_effort'],'thread':{'id':thread,'turns':[{'id':'t0','items':[{'type':'commandExecution','aggregatedOutput':'history '*10000}]}]}}})
    j.record('out',{'id':'start','method':'turn/start','params':{'threadId':thread}},q['request_id'])
    j.record('in',{'id':'start','result':{'turn':{'id':'t1','status':'inProgress'}}})
    for _ in range(25):j.record('in',{'method':'item/agentMessage/delta','params':{'threadId':thread,'turnId':'t1','delta':'part '*1000},'emittedAtMs':12345})
    j.record('in',{'method':'thread/tokenUsage/updated','params':{'threadId':thread,'turnId':'t1','tokenUsage':{'total':{'totalTokens':105,'inputTokens':100,'cachedInputTokens':80,'outputTokens':5,'reasoningOutputTokens':0}}}})
    j.record('in',{'method':'turn/completed','params':{'threadId':thread,'turn':{'id':'t1','status':'completed','items':[{'id':'cmd','type':'commandExecution','aggregatedOutput':'tool '*1000},{'type':'agentMessage','phase':'final_answer','text':'{"summary":"done"}'}]}}})
    j.save(q['request_id'],response);j.sync();j.close()
    return s,q


def facts(path):
    with closing(sqlite3.connect(path)) as c:
        return {t:c.execute('SELECT * FROM '+t+' ORDER BY 1,2').fetchall() for t in ('rpc','threads','turns','issues')}


def test_read_only_inspection_never_migrates_or_creates_lock(tmp_path):
    task=tmp_path/'task';(task/'.mpres').mkdir(parents=True)
    p=task/'.mpres/task.sqlite3'
    with sqlite3.connect(p) as c:c.execute('PRAGMA user_version=11');c.execute('CREATE TABLE sample(x)')
    before=p.read_bytes();result=inspect(task)
    assert result['read_only'] and p.read_bytes()==before
    assert not (task/'.mpres/maintenance.lock').exists()
    with Store(task).readonly() as c:assert c.execute('PRAGMA user_version').fetchone()[0]==11


def test_additive_migration_is_audited_once_and_original_actor_not_invented(compact_root):
    s,r=ready(compact_root,count=1)
    with closing(s.store.connect()) as c:
        c.execute('DROP TABLE maintenance_runs');c.execute('PRAGMA user_version=11')
    with closing(s.store.connect()) as c:
        assert c.execute('PRAGMA user_version').fetchone()[0]==Store.SCHEMA_VERSION
        row=c.execute('SELECT * FROM migration_audit WHERE from_version=11').fetchone()
        assert row['state']=='succeeded' and row['actor'] is None
    with closing(s.store.connect()) as c:assert c.execute('SELECT COUNT(*) FROM migration_audit WHERE from_version=11').fetchone()[0]==1


def test_failed_schema_transition_is_atomic_and_durable(compact_root,monkeypatch):
    s,r=ready(compact_root,count=1)
    with closing(s.store.connect()) as c:c.execute('PRAGMA user_version=11')
    original=Path.read_text
    def invalid(path,*a,**kw):
        if path.name=='migrate_12.sql':return 'CREATE TABLE should_rollback(x); invalid SQL;'
        return original(path,*a,**kw)
    monkeypatch.setattr(Path,'read_text',invalid)
    with pytest.raises(sqlite3.Error):s.store.connect()
    with closing(s.store.readonly()) as c:
        assert c.execute('PRAGMA user_version').fetchone()[0]==11
        assert not c.execute("SELECT 1 FROM sqlite_master WHERE name='should_rollback'").fetchone()
        assert c.execute('SELECT state FROM migration_audit ORDER BY id DESC').fetchone()[0]=='failed'


def test_prune_preserves_exact_rebuilt_index_usage_and_final_answer(compact_root,tmp_path):
    s,q=finished(compact_root);source=s.task/'.mpres/codex-bridge.sqlite3'
    before=facts(source.with_name('codex-index.sqlite3'));usage=s.store.rows('SELECT * FROM usage')
    old_ids=[]
    with closing(sqlite3.connect(source)) as c:old_ids=c.execute('SELECT id FROM wire ORDER BY id').fetchall()
    p=plan(s.task);assert p['rows']>20 and p['safe_to_apply']
    result=apply(s.task,p['plan_id'],by='test');assert result['state']=='completed'
    idx=WireIndex(source,tmp_path/'rebuilt.sqlite3');idx.sync()
    assert facts(idx.path)==before
    assert s.store.rows('SELECT * FROM usage')==usage
    with closing(sqlite3.connect(source)) as c:
        assert c.execute('SELECT id FROM wire ORDER BY id').fetchall()==old_ids
        assert json.loads(c.execute('SELECT response FROM requests WHERE id=?',(q['request_id'],)).fetchone()[0])
    small=compact(s.task,by='test');assert small['reclaimed_database_bytes']>0
    assert WireIndex(source).sync()['rows_read']==0
    assert plan(s.task)['rows']==0


def test_stale_plan_and_unresolved_attempt_cannot_be_cleaned(compact_root):
    s,q=finished(compact_root);p=plan(s.task)
    with s.store.transaction() as c:c.execute("UPDATE attempts SET error='a changed record'")
    with pytest.raises(MPresError,match='changed'):apply(s.task,p['plan_id'],by='test')
    with s.store.transaction() as c:c.execute("UPDATE attempts SET state='uncertain'")
    p=plan(s.task);assert not p['safe_to_apply']
    with pytest.raises(MPresError,match='unresolved'):apply(s.task,p['plan_id'],by='test')


def test_live_journal_blocks_maintenance_even_when_business_looks_quiet(compact_root):
    s,q=finished(compact_root);p=plan(s.task);j=Journal(s.task)
    try:
        with pytest.raises(MPresError,match='in use'):apply(s.task,p['plan_id'],by='test')
    finally:j.close()


def test_exclusive_maintenance_prevents_new_writer(compact_root):
    s,q=finished(compact_root)
    with Lease(s.task,exclusive=True):
        with pytest.raises(MPresError,match='in use'):s.store.connect()
        assert inspect(s.task)['read_only']


def test_future_retention_preserves_fresh_requests(compact_root):
    from mpres.util import utc_now
    s,q=finished(compact_root)
    with s.store.transaction() as c:c.execute('UPDATE attempts SET finished_at=?',(utc_now(),))
    assert plan(s.task)['rows']==0


def test_read_history_keeps_complete_final_messages():
    msg={'result':{'thread':{'id':'h','turns':[{'id':'t','status':'completed','items':[{'type':'agentMessage','phase':'final_answer','text':'truth'},{'type':'commandExecution','aggregatedOutput':'long'}]}]}}}
    new,why=_transform(msg,'thread/read')
    assert new['result']['thread']['turns'][0]['items'][0]['text']=='truth'
    assert 'aggregatedOutput' not in new['result']['thread']['turns'][0]['items'][1]


def test_retention_values_cannot_be_negative(compact_root):
    s,q=finished(compact_root)
    with pytest.raises(MPresError):plan(s.task,success_days=-1)
