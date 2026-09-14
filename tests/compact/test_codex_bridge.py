"""Transport invariants through the current Journal/Bridge/Runner boundaries.

The removed monolithic bridge API is not restored just to satisfy old tests.
Unknown/interrupted work is never continued by rewriting an immutable request.
"""
import json
import threading
from types import SimpleNamespace
from pathlib import Path

import pytest

from mpres.control.codex_bridge import CodexBridge, Journal, counters_delta
from mpres.control.service import require_text
from mpres.util import MPresError
from test_relational_control import compact_root


@pytest.fixture
def bridge(tmp_path):
    b = CodexBridge.__new__(CodexBridge)
    b.task = tmp_path
    b.journal = Journal(tmp_path)
    b.loaded = {}; b.guard = threading.RLock(); b.session_locks = {}
    b.runner = SimpleNamespace(settings=lambda: {'provider': {'handle_limit': 16}})
    b.transport = SimpleNamespace(rpc=lambda *a, **kw: pytest.fail('Unexpected provider call'))
    yield b
    b.journal.close()


def seed_turn(b, request, state='completed', total=27, text='{"summary":"done"}'):
    j = b.journal
    j.enqueue(request); j.before_send(request['request_id'], {'totalTokens':20}, request['runtime'])
    j.record('out', {'id':'rpc','method':'turn/start','params':{'threadId':'thread'}}, request['request_id'])
    j.record('in', {'id':'rpc','result':{'turn':{'id':'turn','status':'inProgress'}}})
    if total is not None:
        j.record('in', {'method':'thread/tokenUsage/updated','params':{'threadId':'thread','turnId':'turn','tokenUsage':{'total':{'totalTokens':total}}}})
    if text is not None:
        j.record('in', {'method':'item/completed','params':{'threadId':'thread','turnId':'turn','item':{'type':'agentMessage','phase':'final_answer','text':text}}})
    if state != 'inProgress':
        j.record('in', {'method':'turn/completed','params':{'threadId':'thread','turn':{'id':'turn','status':state}}})


def run_request():
    return {'request_id':'a','attempt_id':'a','operation':'run','session_id':'thread',
            'runtime':{'model':'fixed-model','reasoning_effort':'low'},'packet':{}}


def test_missing_counter_is_not_zero_and_negative_delta_rejected():
    result = counters_delta({'totalTokens':20}, {'totalTokens':23,'outputTokens':3})
    assert result['total_tokens'] == 3 and result['output_tokens'] is None
    with pytest.raises(MPresError, match='Non-monotonic'):
        counters_delta({'totalTokens':20}, {'totalTokens':19})


def test_unknown_execution_never_resends(bridge):
    req=run_request();bridge.journal.enqueue(req);bridge.journal.before_send('a')
    with pytest.raises(MPresError, match='never resend'):bridge.execute(req)
    assert bridge.journal.row('a')['response'] is None


def test_created_thread_recovers_from_provider_wire_response(bridge):
    req={'operation':'create','request_id':'a','runtime':{'model':'fixed-model','reasoning_effort':'low'}}
    bridge.journal.enqueue(req);bridge.journal.before_send('a')
    receipt={'model':'fixed-model','reasoningEffort':'low','thread':{'id':'provider-thread'}}
    bridge.journal.record('out',{'id':'rpc1','method':'thread/start','params':{}},'a')
    bridge.journal.record('in',{'id':'rpc1','result':receipt})
    response=bridge.execute(req)
    assert response['handle']=='provider-thread'
    assert bridge.journal.handles()[0]['id']=='provider-thread'
    assert bridge.execute(req)==response


def test_queued_request_runtime_mismatch_is_rejected_and_marked_sent(bridge):
    req={'operation':'create','request_id':'a','runtime':{'model':'requested-model','reasoning_effort':'low'}}
    bridge.transport.rpc=lambda *a,**kw: {'model':'fallback-model','reasoningEffort':'low','thread':{'id':'actual'}}
    with pytest.raises(MPresError, match='no fallback'):bridge.execute(req)
    assert bridge.journal.row('a')['sent']==1
    assert bridge.journal.handles()==[]


def test_absolute_packet_output_normalized_before_saving(compact_root,bridge):
    from test_job_runner import ready, attach_requests
    service,runner=ready(compact_root,count=1);attach_requests(runner,runner.tick())
    request=runner.tick()['requests'][0];output=Path(request['packet']['writable_directory'])
    (output/'presentation.md').write_text('---\nmarp: true\n---\n<!-- slide-id: p01-l01-s1 -->\n# Example\n')
    from exercise_fixtures import empty_manifest
    empty_manifest(output)
    bridge.task=service.task
    response={'runtime':request['runtime'],'receipt':'test-provider-completed',
        'result':{'summary':'A worked example'},'usage':[{'call_id':'test-turn','counters':{'total_tokens':2}}]}
    corrected=bridge._source(request,response)
    assert corrected['source_dir']=='output'
    runner.accept(request,corrected)
    assert service.jobs()[0]['state']=='succeeded'
    assert service.metrics()['calls_observed']==1


def test_output_normalization_rejects_other_attempt_and_symlink(bridge):
    work=bridge.task/'.mpres/work';expected=work/'a1/output';other=work/'a2/output'
    expected.mkdir(parents=True);other.mkdir(parents=True)
    req={'operation':'run','attempt_id':'a1','packet':{'writable_directory':str(other)}}
    with pytest.raises(MPresError):bridge._source(req,{})
    (expected/'alias').symlink_to(other,target_is_directory=True)
    req['packet']['writable_directory']=str(expected/'alias')
    with pytest.raises(MPresError):bridge._source(req,{})


def test_compact_receipts_preserve_nested_arrays_only_in_raw_evidence(bridge):
    nested={'matrix':[[1,2],[3,4]]}
    raw={'method':'turn/completed','params':{'threadId':'actual-thread','turn':{'id':'actual-turn','status':'completed','items':[nested]}}}
    wire=bridge.journal.record('in',raw)
    receipt=bridge._reference('actual-thread','actual-turn',wire)
    assert require_text(receipt,'receipt')==receipt and '[[' not in receipt
    row=bridge.journal.db.execute('SELECT payload FROM wire WHERE id=?',(json.loads(receipt)['wire_row'],)).fetchone()
    assert json.loads(row[0])==raw


def test_capabilities_do_not_resume_or_fetch_full_history(bridge):
    bridge.journal.add_handle('known',{})
    calls=[]
    def rpc(method,params,**kw):
        calls.append((method,params))
        if method=='thread/loaded/list':return {'data':[]}
        assert method=='thread/read' and params=={'threadId':'known','includeTurns':False}
        return {'thread':{'id':'known'}}
    bridge.transport.rpc=rpc
    result=bridge.capabilities()
    assert result['handles']==['known']
    assert result['supports_reset'] is False and result['supports_close'] is False
    assert len(calls)==2


def test_completed_turn_recovered_with_genuine_evidence_no_model(bridge):
    req=run_request();seed_turn(bridge,req)
    response=bridge.execute(req)
    assert response['usage'][0]['counters']['total_tokens']==7
    assert response['result']=={'summary':'done'}
    ref=json.loads(response['receipt']);assert ref['turn_id']=='turn' and ref['wire_row']
    assert bridge.journal.row('a')['accepted']==0  # business journal alone owns acceptance
    assert bridge.execute(req)==response


@pytest.mark.parametrize('missing', ['usage','final'])
def test_reconcile_does_not_infer_missing_completion_evidence(bridge,missing):
    req=run_request();seed_turn(bridge,req,total=None if missing=='usage' else 27,text=None if missing=='final' else '{}')
    with pytest.raises(MPresError,match='never resend'):bridge.execute(req)
    assert bridge.journal.row('a')['response'] is None


def test_delta_batch_flushed_before_outgoing_or_completion(bridge):
    j=bridge.journal;j.record('in',{'method':'item/agentMessage/delta','params':{'delta':'x'}})
    assert j.db.in_transaction
    j.record('out',{'id':'rpc','method':'turn/start'})
    assert not j.db.in_transaction
    j.record('in',{'method':'item/agentMessage/delta','params':{'delta':'y'}})
    j.record('in',{'method':'turn/completed','params':{'turn':{'id':'t'}}})
    assert not j.db.in_transaction
    assert j.db.execute('SELECT count(*) FROM wire').fetchone()[0]==4


def test_request_envelope_immutable_even_before_send(bridge):
    req=run_request();bridge.journal.enqueue(req)
    changed={**req,'packet':{'new_instruction':'must be separately authorized'}}
    with pytest.raises(MPresError,match='immutable'):bridge.journal.enqueue(changed)
    assert json.loads(bridge.journal.row('a')['request'])==req


@pytest.mark.parametrize('state',['inProgress','interrupted','failed'])
def test_author_continuation_cannot_overwrite_unknown_or_interrupted_request(bridge,state):
    req=run_request();seed_turn(bridge,req,state=state)
    with pytest.raises(MPresError):bridge.execute(req)
    assert bridge.journal.row('a')['response'] is None
    assert len(bridge.journal.index.turns(request_id='a'))==1
    assert json.loads(bridge.journal.row('a')['request'])==req
