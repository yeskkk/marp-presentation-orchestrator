from pathlib import Path
import hashlib
import json
import pytest
from mpres.control.compatibility import open_task, current_state
from mpres.control.source_evidence import quote, resolve, lines
from mpres.control.preflight import environment_manifest
from mpres.control.semantic import validate
from mpres.util import MPresError
from test_relational_control import compact_root, prepare
from test_deck_workflow import native_double


def test_open_is_idempotent_preserves_confirmed_config(compact_root):
    s=prepare(compact_root)
    before=s.store.rows('SELECT * FROM configs')
    first=open_task(s.task);second=open_task(s.task)
    assert first['compatibility_changed'] and not second['compatibility_changed']
    assert s.store.rows('SELECT * FROM configs')==before
    assert second['current_releases']==[] and not second['source_edited']
    assert len(s.store.rows("SELECT * FROM events WHERE kind='task.compatibility_opened'"))==1
    old=s.store.path.stat().st_mtime_ns
    current_state(s.task)
    assert s.store.path.stat().st_mtime_ns==old


def test_open_missing_never_initializes(tmp_path):
    with pytest.raises(MPresError,match='never initializes'):open_task(tmp_path)
    assert not (tmp_path/'.mpres').exists()


@pytest.fixture
def source(tmp_path):
    (tmp_path/'presentation.md').write_text('---\nmarp: true\n---\n<!-- slide-id: p01-a -->\n# 矩阵\n\n设 $A=\\begin{bmatrix}1&-2\\\\3&4\\end{bmatrix}$。\n')
    return tmp_path


def test_reference_resolves_exact_math_without_retyping(source):
    view=lines(source,'p01-a')
    line=next(r['line'] for r in view['lines'] if r['text'].startswith('设'))
    q=quote(source,'p01-a',line,line)
    raw={'summary':'specific judgment','findings':[], 'feedback_checks':[{'id':'a','version':1,'status':'satisfied','explanation':'Evidence read.', 'evidence':[{'slide_id':'p01-a','source_ref':q['source_ref']}]}]}
    validate('review-result',raw)
    normalized=resolve(raw,source)
    assert normalized['feedback_checks'][0]['evidence']==[{'slide_id':'p01-a','quote':q['quote']}]
    assert 'source_ref' in raw['feedback_checks'][0]['evidence'][0]
    (source/'presentation.md').write_text((source/'presentation.md').read_text().replace('1&-2','1&2'))
    with pytest.raises(MPresError,match='revision differs'):resolve(raw,source)


def test_reference_rejects_changed_quote_wrong_id_and_hidden(source):
    with pytest.raises(MPresError,match='hidden'):quote(source,'p01-a',1,1)
    view=lines(source,'p01-a');line=next(r['line'] for r in view['lines'] if r['text'].startswith('设'))
    q=quote(source,'p01-a',line,line)
    for entry in [{'slide_id':'wrong','source_ref':q['source_ref']},{'slide_id':'p01-a','quote':'invented','source_ref':q['source_ref']}]:
        with pytest.raises(MPresError):resolve({'observations':[entry]},source)
    with pytest.raises(MPresError):quote(source,'p01-a',line,line+999)


def test_environment_uses_existing_absolute_interpreter():
    e=environment_manifest()
    assert Path(e['python_executable']).is_file()
    assert Path(e['project_cli_argv'][1]).is_file()
    assert isinstance(e['available_modules']['sympy'],bool)


def test_identity_delivery_part_is_current_not_a_superseded_parent(compact_root,native_double):
    from test_confirmed_repairs import completed
    from mpres.control.delivery import Delivery
    s,h,r=completed(compact_root,decks=1)
    with s.store.transaction() as c:
        c.execute("INSERT INTO plan_changes VALUES('identity-part',1,'confirmed','{}','{}','2026-01-01T00:00:00Z','2026-01-01T00:00:00Z','fixture')")
        c.execute("INSERT INTO delivery_parts VALUES('p01','p01',0,'Unsplit current deck',10,'identity-part')")
    state=current_state(s.task)
    assert [r['presentation'] for r in state['current_releases']]==['p01']
    assert state['superseded_parents']==[]
    assert [r['presentation'] for r in Delivery(s.task)._releases()]==['p01']
