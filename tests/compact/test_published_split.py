"""Lossless publication provenance; semantic host/native rendering are test doubles."""
import json
import pytest

from mpres.control.published_split import PublishedSplit
from mpres.control.planning import Planning
from mpres.control.quality import Quality
from mpres.marp_source import parse_deck
from mpres.util import MPresError
from test_relational_control import compact_root
from test_deck_workflow import full_task, Host, run_host, native_double


def setup(root):
    s = full_task(root,decks=1,units=4)
    _,last = run_host(s,Host())
    assert last['status'] == 'completed',last
    return s,PublishedSplit(s.task)


def proposal():
    return {'parents':[{'presentation':'p01','parts':[
        {'id':'p01-01','title':'First','estimated_pages':2,'units':['l01','l02']},
        {'id':'p01-02','title':'Second','estimated_pages':2,'units':['l03','l04']}]}]}


def test_lossless_split_preserves_history_and_is_idempotent(compact_root,native_double):
    s,p = setup(compact_root)
    original = s.store.rows('SELECT * FROM releases')[0]
    attempts = s.store.rows('SELECT * FROM attempts')
    configs = s.store.rows('SELECT * FROM configs')
    shown = p.present(proposal());ident = shown['plan_change_id']
    with pytest.raises(MPresError,match='Confirm'):p.run(ident,'main')
    with pytest.raises(MPresError,match='split-published-confirm'):Planning(s.task).confirm(ident,'user')
    p.confirm(ident,'user')
    assert len(s.store.rows('SELECT * FROM releases')) == 1
    result = p.run(ident,'main')
    assert result['delivery_package']['state'] == 'ready',result
    assert s.store.rows("SELECT * FROM releases WHERE presentation='p01'")[0] == original
    assert s.store.rows('SELECT * FROM attempts') == attempts
    assert s.store.rows('SELECT * FROM configs') == configs
    source = s.task/shown['baseline']['release']['path']/'presentation.md'
    slides = parse_deck(source).slides
    for i,pid in enumerate(('p01-01','p01-02')):
        child = parse_deck(s.task/'deliverables'/pid/(pid+'.md'))
        assert [x.source.strip() for x in child.slides] == [x.source.strip() for x in slides[2*i:2*i+2]]
    assert p.run(ident,'main')['already_committed']
    assert len(s.store.rows('SELECT * FROM release_versions')) == 3


@pytest.mark.parametrize('case',['duplicate','reorder','missing','oversize','idtype','parts_type'])
def test_invalid_scope_no_records(compact_root,native_double,case):
    s,p = setup(compact_root);prop = proposal();parts = prop['parents'][0]['parts']
    if case == 'duplicate':parts[1]['units'] = ['l01']
    if case == 'reorder':parts.reverse()
    if case == 'missing':parts.pop()
    if case == 'oversize':parts[0]['estimated_pages'] = 101
    if case == 'idtype':parts[0]['id'] = None
    if case == 'parts_type':prop['parents'] = None
    with pytest.raises(MPresError):p.present(prop)
    assert not s.store.rows('SELECT * FROM plan_changes')


def test_stale_source_rejected(compact_root,native_double):
    s,p = setup(compact_root);shown = p.present(proposal())
    path = s.task/shown['baseline']['release']['path']/'presentation.md'
    path.chmod(0o644);path.write_text(path.read_text()+'\nChanged content.\n')
    with pytest.raises(MPresError,match='baseline changed'):p.confirm(shown['plan_change_id'],'user')
    assert len(s.store.rows('SELECT * FROM releases')) == 1


def test_failed_gate_has_no_partial_publication_and_recovers(compact_root,native_double,monkeypatch):
    s,p = setup(compact_root);shown = p.present(proposal());ident = shown['plan_change_id'];p.confirm(ident,'user')
    original = Quality.inspect_recovering
    def blocked(self,artifact,level):
        return {'id':'test-failed','state':'failed','detail_json':json.dumps({'test_double':True})}
    monkeypatch.setattr(Quality,'inspect_recovering',blocked)
    assert p.run(ident,'main')['state'] == 'blocked'
    assert len(s.store.rows('SELECT * FROM releases')) == 1
    assert not s.store.rows('SELECT * FROM delivery_parts')
    monkeypatch.setattr(Quality,'inspect_recovering',original)
    assert p.run(ident,'main')['delivery_package']['state'] == 'ready'


def test_index_partition_keeps_question_answer_together(tmp_path):
    from test_revision_quality import HEADER
    ids = ['p01-l01-question','p01-l01-answer','p01-l02-question','p01-l02-answer']
    (tmp_path/'presentation.md').write_text(HEADER+'\n\n---\n\n'.join(
        f'<!-- slide-id: {sid} -->\n# Page\n\nCoordinates.' for sid in ids))
    entries = [{'exercise_id':f'e{i}','question_slide_id':ids[i],
                'answer_slide_ids':[ids[i+1]],'learning_goal':'Identify coordinates'} for i in (0,2)]
    (tmp_path/'exercises.json').write_text(json.dumps({'version':1,'exercises':entries}))
    splitter = PublishedSplit.__new__(PublishedSplit)
    result = splitter._manifest(tmp_path,{'slide_ids':ids[:2]})
    assert result['exercises'] == entries[:1]
    with pytest.raises(MPresError,match='separate an indexed question'):
        splitter._manifest(tmp_path,{'slide_ids':ids[:1]})
    assert json.loads((tmp_path/'exercises.json').read_text())['exercises'] == entries


def test_split_child_repair_never_dispatches_curricular_unit_writes(compact_root,native_double):
    from test_confirmed_repairs import RepairHost, propose, confirm
    from feedback_fixtures import teaching_policy
    s=full_task(compact_root,decks=1,units=4);teaching_policy(s)
    h=RepairHost();runner,last=run_host(s,h)
    splitter=PublishedSplit(s.task)
    shown=splitter.present(proposal());ident=shown['plan_change_id']
    splitter.confirm(ident,'user');splitter.run(ident,'main')
    repair,cid=propose(s,runner,['p01-01','p01-02']);confirm(repair,cid)
    before=len(h.calls)
    result=runner.run(cycles=150,interval=0)
    assert repair.case(cid)['state']=='completed',result
    assert not [q for q in h.calls[before:] if q.get('packet',{}).get('kind')=='write']
    assert all(x['phase']=='delivered' for x in s.store.rows("SELECT phase FROM decks WHERE presentation IN ('p01-01','p01-02')"))
