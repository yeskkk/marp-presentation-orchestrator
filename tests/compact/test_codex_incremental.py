from __future__ import annotations
import json
import sqlite3
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import pytest
from mpres.control.codex_index import WireIndex
from mpres.control.codex_bridge import Journal, RpcTransport, TurnClock, counters_delta
from mpres.util import MPresError


def raw(tmp_path):
    p=tmp_path/'wire.sqlite3'
    c=sqlite3.connect(p);c.execute('CREATE TABLE wire(id INTEGER PRIMARY KEY,request_id TEXT,direction TEXT,payload TEXT)');c.commit();c.close()
    return p


def put(p,d,m,r=None):
    with sqlite3.connect(p) as c:
        return c.execute('INSERT INTO wire(request_id,direction,payload) VALUES(?,?,?)',(r,d,json.dumps(m))).lastrowid


def start(p,req,thread,rpc,turn):
    put(p,'out',{'id':rpc,'method':'turn/start','params':{'threadId':thread}},req)
    put(p,'in',{'id':rpc,'result':{'turn':{'id':turn,'status':'inProgress'}}},'WRONG-ambient')
    put(p,'in',{'method':'turn/started','params':{'threadId':thread,'turn':{'id':turn}}},'WRONG-ambient')


def finish(p,thread,turn,text,total):
    put(p,'in',{'method':'item/completed','params':{'threadId':thread,'turnId':turn,'item':{'type':'agentMessage','phase':'final_answer','text':text}}})
    put(p,'in',{'method':'thread/tokenUsage/updated','params':{'threadId':thread,'turnId':turn,'tokenUsage':{'total':{'totalTokens':total,'inputTokens':total-1,'outputTokens':1}}}})
    put(p,'in',{'method':'turn/completed','params':{'threadId':thread,'turn':{'id':turn,'status':'completed','items':[]}}})


def test_index_interleaved_threads_ignores_ambient_request(tmp_path):
    p=raw(tmp_path);start(p,'qa','a',1,'ta');start(p,'qb','b',2,'tb')
    finish(p,'b','tb','B',20);finish(p,'a','ta','A',10)
    index=WireIndex(p);result=index.sync(batch_size=2)
    assert result['rows_read']==12
    assert index.turns(request_id='qa')[0]['final_text']=='A'
    assert index.turns(request_id='qb')[0]['final_text']=='B'
    assert index.latest_usage('a')['totalTokens']==10
    assert index.sync()['rows_read']==0


def test_sync_cursors_commit_bounded_and_resume(tmp_path):
    p=raw(tmp_path)
    for _ in range(23):put(p,'in',{'method':'heartbeat'})
    index=WireIndex(p);assert index.sync(max_rows=7,batch_size=3)['rows_read']==7
    assert WireIndex(p).sync()['rows_read']==16
    assert index.summary()['cursor']==23
    with sqlite3.connect(p) as c:
        plan=c.execute('EXPLAIN QUERY PLAN SELECT * FROM wire WHERE id>? ORDER BY id LIMIT ?', (7,3)).fetchone()[3]
    assert 'SEARCH' in plan and 'PRIMARY KEY' in plan


def test_source_readonly_and_malformed_row_retained(tmp_path):
    p=raw(tmp_path)
    with sqlite3.connect(p) as c:c.execute("INSERT INTO wire VALUES(1,NULL,'in','not json')")
    before=p.read_bytes();index=WireIndex(p);assert index.sync()['cursor']==1
    assert p.read_bytes()==before and index.summary()['issues']==1


def test_truncated_or_replaced_source_not_silently_reused(tmp_path):
    p=raw(tmp_path);put(p,'in',{'method':'heartbeat'});i=WireIndex(p);i.sync()
    with sqlite3.connect(p) as c:c.execute('DELETE FROM wire')
    with pytest.raises(MPresError,match='truncated'):i.sync()
    replacement=raw(tmp_path/'new') if False else tmp_path/'replacement'
    p.rename(replacement);new=raw(tmp_path)
    rebuilt=WireIndex(new)
    assert rebuilt.sync()['cursor']==0
    assert rebuilt.summary()['turns']==0  # old identity/cursor is never reused


def test_concurrent_index_sync_never_double_projects(tmp_path):
    p=raw(tmp_path);start(p,'qa','a',1,'ta');finish(p,'a','ta','A',4);i=WireIndex(p)
    with ThreadPoolExecutor(4) as e:rows=list(e.map(lambda _:i.sync(batch_size=1),range(4)))
    assert sum(x['rows_read'] for x in rows)==6
    assert len(i.turns(request_id='qa'))==1


def test_started_notification_before_rpc_response_routes_by_exact_thread(tmp_path):
    p=raw(tmp_path)
    put(p,'out',{'id':'rpc','method':'turn/start','params':{'threadId':'a'}},'qa')
    put(p,'in',{'method':'turn/started','params':{'threadId':'a','turn':{'id':'ta'}}},'wrong')
    put(p,'in',{'id':'rpc','result':{'turn':{'id':'ta'}}})
    i=WireIndex(p);i.sync();assert i.turns(request_id='qa')[0]['id']=='ta'


def test_usage_unknown_not_zero_and_nonmonotonic_rejected(tmp_path):
    p=raw(tmp_path);start(p,'qa','a',1,'ta');i=WireIndex(p);i.sync()
    with pytest.raises(MPresError,match='baseline'):i.latest_usage('a')
    assert counters_delta({'totalTokens':3},{'totalTokens':5})['input_tokens'] is None
    with pytest.raises(MPresError,match='Non-monotonic'):counters_delta({'totalTokens':5},{'totalTokens':4})


def test_new_thread_only_can_have_zero_baseline(tmp_path):
    p=raw(tmp_path)
    put(p,'out',{'id':1,'method':'thread/start','params':{}},'create')
    put(p,'in',{'id':1,'result':{'thread':{'id':'a'},'model':'x','reasoningEffort':'low'}})
    i=WireIndex(p);i.sync();assert i.latest_usage('a')['totalTokens']==0


def test_no_delta_body_in_small_index_and_final_content_retained(tmp_path):
    p=raw(tmp_path);start(p,'qa','a',1,'ta')
    for _ in range(100):put(p,'in',{'method':'item/agentMessage/delta','params':{'threadId':'a','turnId':'ta','delta':'x'*1000}})
    finish(p,'a','ta','final',100)
    i=WireIndex(p);i.sync();assert i.path.stat().st_size<p.stat().st_size
    assert i.turns(request_id='qa')[0]['final_text']=='final'


def test_idle_and_hard_deadlines_are_distinct():
    c=TurnClock(0,10,50,0)
    c.observe(1,9);assert c.remaining(18)==1
    c.observe(1,18)  # replayed progress marker is not fresh progress
    with pytest.raises(MPresError,match='idle'):c.remaining(20)
    c=TurnClock(0,10,20,0);c.observe(2,19)
    with pytest.raises(MPresError,match='wall budget'):c.remaining(21)


def test_heartbeat_does_not_count_as_turn_progress(tmp_path):
    p=raw(tmp_path);start(p,'qa','a',1,'ta')
    put(p,'in',{'method':'heartbeat','params':{'threadId':'a','turnId':'ta'}})
    i=WireIndex(p);i.sync();assert i.turns(request_id='qa')[0]['progress_wire'] is None


def test_reroute_recorded_not_disguised_as_expected_runtime(tmp_path):
    p=raw(tmp_path);start(p,'qa','a',1,'ta')
    put(p,'in',{'method':'model/rerouted','params':{'threadId':'a','turnId':'ta','toModel':'other'}})
    i=WireIndex(p);i.sync();assert 'other' in i.turns(request_id='qa')[0]['runtime_error']


def test_journal_refuses_conflicting_response_and_resend(tmp_path):
    (tmp_path/'.mpres').mkdir();j=Journal(tmp_path)
    try:
        q={'request_id':'q','operation':'run'};j.enqueue(q);j.before_send('q')
        with pytest.raises(MPresError,match='resend'):j.before_send('q')
        j.save('q',{'result':1});j.save('q',{'result':1})
        with pytest.raises(MPresError,match='replace'):j.save('q',{'result':2})
    finally:j.close()


@pytest.fixture
def fake_server(tmp_path):
    script=tmp_path/'server.py'
    script.write_text('''import sys,json,threading,time
lock=threading.Lock()
def emit(m):
 with lock: print(json.dumps(m),flush=True)
def work(m):
 p=m['params'];t=p['threadId'];turn='turn-'+t
 time.sleep(.02 if t=='b' else .04)
 emit({'method':'turn/started','params':{'threadId':t,'turn':{'id':turn}}})
 emit({'id':m['id'],'result':{'turn':{'id':turn}}})
 time.sleep(.02)
 emit({'method':'thread/tokenUsage/updated','params':{'threadId':t,'turnId':turn,'tokenUsage':{'total':{'totalTokens':10 if t=='a' else 20}}}})
 emit({'method':'item/completed','params':{'threadId':t,'turnId':turn,'item':{'type':'agentMessage','phase':'final_answer','text':t}}})
 emit({'method':'turn/completed','params':{'threadId':t,'turn':{'id':turn,'status':'completed'}}})
for line in sys.stdin:
 m=json.loads(line)
 if m.get('method')=='turn/start': threading.Thread(target=work,args=(m,)).start()
 elif 'id' in m: emit({'id':m['id'],'result':{'ok':True}})
''')
    return script


def test_real_stdio_subprocess_routes_two_parallel_turns(tmp_path,fake_server):
    (tmp_path/'.mpres').mkdir();j=Journal(tmp_path);t=RpcTransport(j,[sys.executable,str(fake_server)],tmp_path,rpc_timeout=2)
    try:
        with ThreadPoolExecutor(2) as pool:
            replies=list(pool.map(lambda h:t.rpc('turn/start',{'threadId':h},request_id='q-'+h),['a','b']))
        assert {x['turn']['id'] for x in replies}=={'turn-a','turn-b'}
        deadline=time.monotonic()+2
        while time.monotonic()<deadline:
            j.sync()
            if all(j.index.turns(request_id='q-'+h)[0]['end_wire'] for h in ['a','b']):break
            time.sleep(.01)
        assert j.index.turns(request_id='q-a')[0]['final_text']=='a'
        assert j.index.turns(request_id='q-b')[0]['final_text']=='b'
        assert j.index.latest_usage('a')['totalTokens']==10
        assert j.index.latest_usage('b')['totalTokens']==20
    finally:t.close();j.close()


def test_rpc_disconnect_is_unknown_not_retry(tmp_path):
    (tmp_path/'.mpres').mkdir();j=Journal(tmp_path)
    t=RpcTransport(j,[sys.executable,'-c','import sys;sys.stdin.readline()'],tmp_path,rpc_timeout=1)
    try:
        with pytest.raises(MPresError,match='disconnected'):t.rpc('turn/start',{'threadId':'a'},request_id='q')
        j.sync()
        with sqlite3.connect(j.path) as c:assert c.execute("SELECT count(*) FROM wire WHERE direction='out'").fetchone()[0]==1
    finally:t.close();j.close()


def test_no_unattended_approval(tmp_path):
    (tmp_path/'.mpres').mkdir();j=Journal(tmp_path)
    code="import sys,json;sys.stdin.readline();print(json.dumps({'id':'ask','method':'item/commandExecution/requestApproval','params':{'threadId':'a'}}),flush=True);sys.stdin.readline()"
    t=RpcTransport(j,[sys.executable,'-c',code],tmp_path,rpc_timeout=3)
    try:
        with pytest.raises(MPresError):t.rpc('turn/start',{'threadId':'a'},request_id='q')
        j.flush()
        with sqlite3.connect(j.path) as c:
            out=[json.loads(r[0]) for r in c.execute("SELECT payload FROM wire WHERE direction='out'")]
        assert any(x.get('id')=='ask' and 'error' in x for x in out)
        assert not any(x.get('result') in ('accept','approved') for x in out)
    finally:t.close();j.close()


def test_history_rpc_projects_terminal_with_genuine_rpc_evidence(tmp_path):
    p=raw(tmp_path);start(p,'qa','a',1,'ta')
    put(p,'out',{'id':2,'method':'thread/read','params':{'threadId':'a','includeTurns':True}},'reconcile:qa')
    wire=put(p,'in',{'id':2,'result':{'thread':{'id':'a','turns':[{'id':'ta','status':'completed','items':[{'type':'agentMessage','text':'kept'}]}]}}})
    i=WireIndex(p);i.sync();turn=i.turns(request_id='qa')[0]
    assert turn['end_wire']==wire and turn['state']=='completed' and turn['final_text']=='kept'
    assert turn['usage_json'] is None  # do not invent missing telemetry


def test_native_bridge_full_pipeline_with_explicit_fake_server(compact_root,native_double,tmp_path):
    from mpres.control.codex_bridge import CodexBridge
    from test_deck_workflow import full_task
    service=full_task(compact_root,decks=1,units=2)
    server=tmp_path/'codex-fixture'
    server.write_text('#!'+sys.executable+'\nimport sys\nsys.path[:0]='+repr([str(Path(__file__).resolve().parent), str(Path(__file__).resolve().parents[2]/'src')])+'\n'+Path(__file__).with_name('fake_codex_server.py').read_text())
    server.chmod(0o755)
    with CodexBridge(service.task,executable=str(server)) as b:
        result=b.drive(120)
    assert service.status()['status']=='completed',result
    assert (service.task/'deliverables/p01/p01.md').is_file()
    assert len(service.store.rows("SELECT * FROM jobs WHERE kind='review' AND state='succeeded'"))==5
    assert not service.store.rows("SELECT * FROM host_requests WHERE state<>'accepted'")
    index=WireIndex(service.task/'.mpres/codex-bridge.sqlite3');index.sync()
    with index.connect() as c:
        timeline=[]
        for r in c.execute('SELECT * FROM turns'):
            timeline.extend([(r['start_wire'],1),(r['end_wire'],-1)])
    n=peak=0
    for _,delta in sorted(timeline):n+=delta;peak=max(peak,n)
    assert peak>=2, 'real subprocess fixture must exercise overlapping turns, not only parallel API calls'
    assert service.metrics()['attempt_coverage']==1


def test_bridge_replay_uses_business_journal_not_legacy_accepted_bit(compact_root,native_double,tmp_path):
    from mpres.control.codex_bridge import CodexBridge
    from test_deck_workflow import full_task
    service=full_task(compact_root,decks=1,units=1)
    server=tmp_path/'codex-fixture'
    server.write_text('#!'+sys.executable+'\nimport sys\nsys.path[:0]='+repr([str(Path(__file__).resolve().parent), str(Path(__file__).resolve().parents[2]/'src')])+'\n'+Path(__file__).with_name('fake_codex_server.py').read_text());server.chmod(0o755)
    with CodexBridge(service.task,executable=str(server)) as b:
        b.drive(120)
        before=service.store.rows('SELECT * FROM usage')
        # Local historical unaccepted rows do not resurrect old task work.
        with b.journal.lock:
            b.journal.db.execute("INSERT INTO requests(id,request,sent,accepted) VALUES('old','{}',1,0)");b.journal.flush()
        assert b.drive(1)['requests']==[]
        assert service.store.rows('SELECT * FROM usage')==before


# Existing project fixtures, not a native model/rendering acceptance claim.
from test_relational_control import compact_root
from test_deck_workflow import native_double
