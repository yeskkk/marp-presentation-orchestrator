from pathlib import Path
from collections import Counter
import copy
import json

import pytest

from mpres.control.runner import Runner
from mpres.control.task_context import context, received, ACCEPTED, REQUESTED
from mpres.control.store import encode
from mpres.startup import build_command
from mpres.util import MPresError
from test_relational_control import compact_root, prepare, register
from test_deck_workflow import full_task, Host, native_double, run_host
from test_historical_feedback import FeedbackHost
from feedback_fixtures import teaching_policy


def launch(root, *, feedback=False):
    s=prepare(root, count=2);register(s)
    if feedback:teaching_policy(s)
    r=Runner(s.task);a=s.bind(s.jobs()[0]['id'],'h1')
    q=r.execution_request(s.job(a['job_id']),a)
    return s,r,a,q


def response(req):
    if req['operation']=='brief':return FeedbackHost()(req)
    path=Path(req['packet']['writable_directory'])
    (path/'presentation.md').write_text('---\nmarp: true\n---\n<!-- slide-id: p01-l01-s1 -->\n# Example\n')
    from exercise_fixtures import empty_manifest
    empty_manifest(path)
    return {'runtime':req['runtime'],'receipt':'actual-fixture:'+req['request_id'],
            'source_dir':'output','result':{'summary':'An explicitly deterministic test result.'},
            'usage':[{'call_id':'work','counters':{}}]}


@pytest.mark.parametrize('feedback',[False,True])
def test_first_request_contains_exact_task_before_any_role_work(compact_root,feedback):
    s,r,a,q=launch(compact_root,feedback=feedback)
    assert q['operation']==('brief' if feedback else 'run')
    packet=q['packet'];ctx=packet['task_context']
    assert ctx['action']=='read_full' and ctx['text']==(s.task/'TASK.md').read_text()
    assert packet['reading_order'][0]=='task_context'
    assert not any(str(p).endswith('/TASK.md') for p in packet['input_files'])
    assert packet['context_bytes']>=len(ctx['text'].encode())
    assert s.store.rows('SELECT * FROM events WHERE kind=?',(ACCEPTED,))==[]


def test_next_job_same_session_reuses_context_even_after_runner_restart(compact_root):
    s,r,a,q=launch(compact_root);reply=response(q);r.accept(q,reply)
    b=s.bind(s.jobs()[1]['id'],'h1');r=Runner(s.task)
    q2=r.execution_request(s.job(b['job_id']),b)
    assert q2['packet']['task_context']['action']=='reuse'
    assert 'text' not in q2['packet']['task_context']
    assert len(s.store.rows('SELECT * FROM events WHERE kind=?',(ACCEPTED,)))==1
    r.accept(q,reply)
    assert len(s.store.rows('SELECT * FROM events WHERE kind=?',(ACCEPTED,)))==1


def test_task_read_once_in_brief_not_again_in_run(compact_root):
    s,r,a,q=launch(compact_root,feedback=True);r.accept(q,response(q))
    run=r.execution_request(s.job(a['job_id']),s.attempt(a['id']))
    assert run['operation']=='run' and run['packet']['task_context']['action']=='reuse'
    assert 'text' not in run['packet']['task_context']


def test_distinct_session_must_read_for_itself(compact_root):
    s,r,a,q=launch(compact_root);r.accept(q,response(q));register(s,'h2')
    b=s.bind(s.jobs()[1]['id'],'h2')
    assert r.execution_request(s.job(b['job_id']),b)['packet']['task_context']['action']=='read_full'


def test_invalid_runtime_does_not_claim_reading(compact_root):
    s,r,a,q=launch(compact_root,feedback=True);reply=response(q)
    reply['runtime']={**reply['runtime'],'model':'wrong'}
    with pytest.raises(MPresError):r.accept(q,reply)
    assert not s.store.rows('SELECT * FROM events WHERE kind=?',(ACCEPTED,))


def test_unknown_result_remains_unacknowledged_until_same_receipt_recovers(compact_root):
    s,r,a,q=launch(compact_root);s.uncertain(a['id'],'lost transport')
    assert not s.store.rows('SELECT * FROM events WHERE kind=?',(ACCEPTED,))
    r.accept(q,response(q))
    assert len(s.store.rows('SELECT * FROM events WHERE kind=?',(ACCEPTED,)))==1


def test_task_edit_without_confirmation_fails_before_context_dispatch(compact_root):
    s=prepare(compact_root);register(s);a=s.bind(s.jobs()[0]['id'],'h1')
    (s.task/'TASK.md').write_text('unapproved change')
    with pytest.raises(MPresError,match='changed'):Runner(s.task).execution_request(s.job(a['job_id']),a)
    assert not s.store.rows('SELECT * FROM events WHERE kind=?',(REQUESTED,))


def test_task_text_cannot_be_truncated_by_transport(compact_root):
    s,r,a,q=launch(compact_root);bad=copy.deepcopy(q);bad['packet']['task_context']['text']='partial'
    with pytest.raises(MPresError,match='truncated'):r.accept(bad,response(q))
    assert not s.store.rows('SELECT * FROM events WHERE kind=?',(ACCEPTED,))


def test_task_context_cannot_be_attached_to_undispatched_request(compact_root):
    s,r,a,q=launch(compact_root);bad=copy.deepcopy(q);bad['request_id']='invented'
    with pytest.raises(MPresError,match='No dispatched'):r.accept(bad,response(q))


def test_packet_preview_never_marks_task_read(compact_root):
    s=prepare(compact_root);register(s);a=s.bind(s.jobs()[0]['id'],'h1');r=Runner(s.task)
    assert r.packet(s.job(a['job_id']),a['id'])['task_context']['action']=='read_full'
    assert not s.store.rows('SELECT * FROM events WHERE kind IN (?,?)',(REQUESTED,ACCEPTED))


def test_existing_requests_do_not_gain_fabricated_read_history(compact_root):
    s,r,a,q=launch(compact_root)
    # Simulate a genuinely old, already-dispatched request, not a fresh bypass.
    with s.store.transaction() as c:
        c.execute('DELETE FROM host_requests WHERE request_id=?',(q['request_id'],))
        c.execute('DELETE FROM events WHERE kind=?',(REQUESTED,))
    q['packet'].pop('task_context');q['packet'].pop('reading_order')
    r.accept(q,response(q))
    assert not s.store.rows('SELECT * FROM events WHERE kind=?',(ACCEPTED,))
    b=s.bind(s.jobs()[1]['id'],'h1')
    assert r.execution_request(s.job(b['job_id']),b)['packet']['task_context']['action']=='read_full'


def test_all_five_reviewers_and_authors_read_once_across_two_decks(compact_root,native_double):
    s=full_task(compact_root,decks=2,units=2);host=Host(findings=True);run_host(s,host)
    assert s.status()['status']=='completed'
    counts=Counter(q['session_id'] for q in host.calls if q['packet']['task_context']['action']=='read_full')
    assert set(counts.values())=={1}
    assert len(counts)==len(host.handles)
    assert all('confirmed_task_brief' not in q['packet'] for q in host.calls)
    assert any(q['operation']=='audience_step' and q['packet']['task_context']['action']=='reuse' for q in host.calls)


def test_authorized_updated_task_delivers_only_delta(compact_root):
    s,r,a,q=launch(compact_root);r.accept(q,response(q))
    old=s.store.rows('SELECT * FROM configs')[0]
    newtext=old['task_text']+'\nA newly confirmed requirement.\n'
    # Emulate a separate, completed approval transaction; not an update API.
    with s.store.transaction() as c:
        cid=c.execute('INSERT INTO configs(settings_json,runtime_json,task_text,task_digest,confirmed_by,confirmed_at) VALUES(?,?,?,?,?,?)',
          (old['settings_json'],old['runtime_json'],newtext,'fixture','explicit-test-user',old['confirmed_at'])).lastrowid
        c.execute('UPDATE task SET config_id=?',(cid,))
    (s.task/'TASK.md').write_text(newtext)
    from mpres.util import task_sha256
    # immutable configs cannot be patched; configure the fixture's documents read instead.
    original=s.documents
    s.documents=lambda:{**original(),'task_digest':'fixture'}
    value=context(s,a)
    assert value['action']=='apply_delta' and 'text' not in value
    assert '+A newly confirmed requirement.' in value['delta']
    assert value['base_config_id']==old['id']


def test_startup_leaves_amendment_choice_before_task_work(tmp_path):
    cmd=build_command(tmp_path,{'codex':'codex','runtime':{'model':'chosen','reasoning_effort':'high','task':'demo'}},[])
    text=cmd[-1]
    assert 'amend' in text and 'do not automatically start production' in text
    assert text.index('amend') < text.index('read TASK.md')
    assert 'once in this session' in text
