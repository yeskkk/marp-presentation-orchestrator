"""Partition tests use deterministic semantic/render fixtures, not a real course."""
from __future__ import annotations
import copy,json,sqlite3
from concurrent.futures import ThreadPoolExecutor
import pytest
from mpres.util import MPresError,read_yaml,write_yaml_atomic
from mpres.control.service import Service
from mpres.control.planning import Planning,ancestors,runtime_origin,source_artifact
from mpres.control.batches import Batches
from mpres.control.runner import Runner
from mpres.control.workflow import Workflow
from mpres.control.store import Store,encode
from test_relational_control import compact_root
from test_deck_workflow import full_task,Host,native_double,run_host


def paused(root):
    s=full_task(root,decks=4,units=2,delivery='pilot');s.materialize();Workflow(s.task).ensure()
    with s.store.transaction() as c:c.execute("UPDATE task SET status='paused'")
    return s


def proposal(parent='p02'):
    return {'parents':[{'presentation':parent,'parts':[
        {'id':parent+'-01','title':'First independent lesson','estimated_pages':80,'units':['l01']},
        {'id':parent+'-02','title':'Second independent lesson','estimated_pages':70,'units':['l02']}
    ]}]}


def split(s, prop=None):
    p=Planning(s.task);shown=p.present(prop or proposal());p.confirm(shown['plan_change_id'],'test-user-confirmed')
    return p,shown


def test_partition_preserves_original_config_and_plans(compact_root):
    s=paused(compact_root);config=s.store.rows('SELECT * FROM configs');old=s.store.rows('SELECT * FROM plan_items');jobs=s.jobs();docs=s.documents()
    p,shown=split(s)
    assert s.documents()==docs and s.store.rows('SELECT * FROM configs')==config
    assert s.store.rows('SELECT * FROM plan_items WHERE id<=?',(max(r['id'] for r in old),))==old
    assert s.jobs()==jobs and s.status()['status']=='paused'
    effective=p.show()['presentations']
    assert [d['id'] for d in effective]==['p01','p02-01','p02-02','p03','p04']
    assert [d['estimated_pages'] for d in effective[1:3]]==[80,70]
    assert effective[1]['units'][0]['brief']==old[2]['brief']
    assert not s.store.rows('SELECT * FROM attempts')


@pytest.mark.parametrize('case',['lost','duplicate','reordered','unknown','empty','collision','oversize','bool','runtime','parent-child','idtype'])
def test_invalid_partition_rejected_without_new_records(compact_root,case):
    s=paused(compact_root);p=proposal();a=p['parents'][0];parts=a['parts']
    if case=='lost':parts.pop()
    elif case=='duplicate':parts[1]['units']=['l01']
    elif case=='reordered':parts.reverse()
    elif case=='unknown':parts[1]['units']=['l99']
    elif case=='empty':parts[0]['units']=[]
    elif case=='collision':parts[0]['id']='p03'
    elif case=='oversize':parts[0]['estimated_pages']=101
    elif case=='bool':parts[0]['estimated_pages']=True
    elif case=='runtime':parts[0]['model']='other'
    elif case=='parent-child':parts[0]['id']='p02'
    elif case=='idtype':parts[0]['id']=None
    before=s.store.rows('SELECT * FROM plan_items')
    with pytest.raises(MPresError):Planning(s.task).present(p)
    assert s.store.rows('SELECT * FROM plan_items')==before
    assert not s.store.rows('SELECT * FROM plan_changes')


def test_delivered_and_active_parents_cannot_split(compact_root):
    s=paused(compact_root)
    with s.store.transaction() as c:c.execute("UPDATE decks SET phase='delivered' WHERE presentation='p01'")
    with pytest.raises(MPresError,match='unpublished'):Planning(s.task).present(proposal('p01'))
    with s.store.transaction() as c:c.execute("UPDATE task SET status='running'")
    with pytest.raises(MPresError,match='pause'):Planning(s.task).present(proposal())


def test_cancel_and_stale_proposal(compact_root):
    s=paused(compact_root);p=Planning(s.task);x=p.present(proposal());p.cancel(x['plan_change_id'],'user')
    with pytest.raises(MPresError,match='Cancelled'):p.confirm(x['plan_change_id'],'user')
    x=p.present(proposal())
    with s.store.transaction() as c:c.execute("UPDATE jobs SET state='blocked' WHERE presentation='p02'")
    with pytest.raises(MPresError,match='changed'):p.confirm(x['plan_change_id'],'user')
    assert not s.store.rows('SELECT * FROM delivery_parts')


def test_concurrent_confirm_idempotent(compact_root):
    s=paused(compact_root);p=Planning(s.task);x=p.present(proposal())
    with ThreadPoolExecutor(2) as ex:results=list(ex.map(lambda _:p.confirm(x['plan_change_id'],'user'),range(2)))
    assert sum(not r['already_confirmed'] for r in results)==1
    assert len(s.store.rows('SELECT * FROM delivery_parts'))==2
    with pytest.raises(MPresError,match='attribution'):p.confirm(x['plan_change_id'],'other')


def test_exact_parent_batch_expansion_not_prefix(compact_root):
    s=paused(compact_root);split(s);b=Batches(s.task);x=b.present(['p02','p03'])
    assert x['presentations']==['p02-01','p02-02','p03']
    assert x['requested_presentations']==['p02','p03']
    with pytest.raises(MPresError,match='Overlapping'):b.present(['p02','p02-01'])
    b.confirm(x['batch_id'],'user');s.materialize()
    assert Workflow(s.task).allowed()=={'p02-01','p02-02'}
    old=next(j for j in s.jobs() if j['presentation']=='p02')
    with pytest.raises(MPresError,match='Superseded'):s.bind(old['id'],'nonexistent')
    other=next(j for j in s.jobs() if j['presentation']=='p04')
    with pytest.raises(MPresError,match='outside'):s.bind(other['id'],'nonexistent')
    assert not s.store.rows('SELECT * FROM attempts')


def test_pre_split_presented_batch_becomes_stale(compact_root):
    s=paused(compact_root);b=Batches(s.task);x=b.present(['p02']);split(s)
    with pytest.raises(MPresError,match='changed'):b.confirm(x['batch_id'],'user')
    assert s.status()['status']=='paused'


def test_estimate_only_parent_keeps_plan_identity(compact_root):
    s=paused(compact_root);old=s.store.rows('SELECT * FROM plan_items')
    p=proposal();p['parents'].append({'presentation':'p03','parts':[{'id':'p03','title':'Third deck','estimated_pages':90,'units':['l01','l02']}]})
    planning,_=split(s,p)
    shown=next(d for d in planning.show()['presentations'] if d['id']=='p03')
    assert shown['estimated_pages']==90
    assert s.store.rows("SELECT * FROM plan_items WHERE presentation='p03'")==[x for x in old if x['presentation']=='p03']


def test_runtime_and_independence_follow_parent(compact_root):
    s=paused(compact_root);split(s);s.materialize()
    with s.store.transaction() as c:
        child=c.execute("SELECT * FROM jobs WHERE presentation='p02-01'").fetchone()
        parent=c.execute("SELECT * FROM jobs WHERE presentation='p02'").fetchone()
        assert s.expected_runtime(c,child)==s.expected_runtime(c,parent)
        assert runtime_origin(c,'p02-01')=='p02'
    with s.store.transaction() as c:spec=s.expected_runtime(c,child)
    review_spec={'model':spec['model'],'reasoning_effort':'low'}
    s.register_session('formerly-author','reviewer',review_spec['model'],review_spec['reasoning_effort'],'actual-test-receipt')
    with s.store.transaction() as c:
        c.execute("INSERT INTO participation VALUES('formerly-author','p02','write',0,'')")
        jid=s.ensure_job(c,key='review:independence',presentation='p02-01',kind='review',channel='audience',round=1)
        j=c.execute('SELECT * FROM jobs WHERE id=?',(jid,)).fetchone();session=c.execute("SELECT * FROM sessions WHERE id='formerly-author'").fetchone()
        assert not s.eligible(c,j,session)


def test_parent_scoped_feedback_follows_children(compact_root):
    from mpres.control.feedback import Feedback
    s=paused(compact_root);split(s)
    with s.store.transaction() as c:
        row=c.execute('SELECT * FROM feedback_rules ORDER BY version DESC LIMIT 1').fetchone();data=json.loads(row['payload_json']);data['enabled']=True;data['presentations']=['p02']
        c.execute('UPDATE feedback_rules SET payload_json=? WHERE id=? AND version=?',(encode(data),row['id'],row['version']))
        assert any(x['id']==row['id'] for x in Feedback.effective(c,'p02-01'))
        assert not any(x['id']==row['id'] for x in Feedback.effective(c,'p03'))


def test_real_old_source_copied_to_writer_not_certified(compact_root):
    from mpres.source_policy import install_theme
    from test_revision_quality import HEADER
    s=paused(compact_root);source=s.task/'.mpres/artifacts/imported';source.mkdir(parents=True)
    text=HEADER+'<!-- slide-id: p02-l01-old -->\n# Prior lesson\n\nKeep the relevant mathematical content.\n'
    (source/'presentation.md').write_text(text);install_theme(source)
    with s.store.transaction() as c:
        c.execute("INSERT INTO artifacts(id,attempt_id,presentation,unit,path,entrypoint,origin,created_at) VALUES('old',NULL,'p02','l01','.mpres/artifacts/imported','presentation.md','import','2026-01-01')")
    split(s);b=Batches(s.task);x=b.present(['p02']);b.confirm(x['batch_id'],'user');s.materialize()
    j=next(j for j in s.jobs() if j['presentation']=='p02-01')
    with s.store.transaction() as c:spec=s.expected_runtime(c,j)
    s.register_session('new-author','author',spec['model'],spec['reasoning_effort'],'actual-test-receipt')
    a=s.bind(j['id'],'new-author');packet=Runner(s.task).packet(j,a['id'])
    assert packet['content_origin']=='p02'
    assert (source/'presentation.md').read_text()==text
    from pathlib import Path
    assert (Path(packet['writable_directory'])/'presentation.md').read_text()==text
    assert not s.store.rows('SELECT * FROM gate_runs')
    assert len(s.store.rows('SELECT * FROM artifacts'))==1


def test_complete_split_selected_scope_and_pause_without_p04(compact_root,native_double):
    s=full_task(compact_root,decks=4,units=4,delivery='pilot');host=Host(findings=True);run_host(s,host)
    assert s.status()['status']=='paused'
    original=s.store.rows("SELECT * FROM releases WHERE presentation='p01'")
    original_pdf=(s.task/original[0]['pdf_path']).read_bytes()
    prop=proposal();prop['parents'][0]['parts'][0]['units']=['l01','l02'];prop['parents'][0]['parts'][1]['units']=['l03','l04']
    split(s,prop);b=Batches(s.task);x=b.present(['p02','p03']);b.confirm(x['batch_id'],'real-test-user')
    runner,last=run_host(s,host,cycles=180)
    assert s.status()['status']=='paused',(last,Workflow(s.task).status())
    assert {r['presentation'] for r in s.store.rows('SELECT * FROM releases')}=={'p01','p02-01','p02-02','p03'}
    assert b.status()[0]['state']=='completed'
    assert not s.store.rows("SELECT a.* FROM attempts a JOIN jobs j ON j.id=a.job_id WHERE j.presentation IN ('p02','p04')")
    assert s.store.rows("SELECT * FROM releases WHERE presentation='p01'")==original
    assert (s.task/original[0]['pdf_path']).read_bytes()==original_pdf
    assert all((s.task/'deliverables'/pid/'WARNINGS.md').is_file() for pid in ('p02-01','p02-02','p03'))


def test_schema10_upgrade_only_adds_relations(compact_root):
    s=paused(compact_root);saved={t:s.store.rows('SELECT * FROM '+t) for t in ('configs','plan_items','jobs','events')}
    c=s.store.connect()
    for table in ('plan_item_origins','delivery_parts','plan_changes'):c.execute('DROP TABLE '+table)
    c.execute('PRAGMA user_version=10');c.close()
    for _ in range(2):
        c=Store(s.task).connect();assert c.execute('PRAGMA user_version').fetchone()[0]==11
        assert c.execute('PRAGMA integrity_check').fetchone()[0]=='ok';assert not c.execute('PRAGMA foreign_key_check').fetchall();c.close()
    assert {t:s.store.rows('SELECT * FROM '+t) for t in saved}==saved


def test_estimate_refinement_then_split_preserves_confirmation_history(compact_root):
    s=paused(compact_root)
    only={'parents':[{'presentation':'p02','parts':[{'id':'p02','title':'Original scope','estimated_pages':90,'units':['l01','l02']}]}]}
    p,x=split(s,only)
    only['parents'][0]['parts'][0]['estimated_pages']=100
    y=p.present(only);p.confirm(y['plan_change_id'],'user')
    z=p.present(proposal());p.confirm(z['plan_change_id'],'user')
    assert len(s.store.rows("SELECT * FROM plan_changes WHERE state='confirmed'"))==3
    assert json.loads(s.store.rows('SELECT proposal_json FROM plan_changes WHERE id=?',(x['plan_change_id'],))[0]['proposal_json'])['parents'][0]['parts'][0]['estimated_pages']==90
    assert len(s.store.rows('SELECT * FROM delivery_parts'))==2


def test_source_preparation_accepts_legacy_section_entrypoint(compact_root):
    from mpres.control.files import prepare_edit_source
    from test_revision_quality import HEADER
    s=paused(compact_root);source=s.task/'content/old';source.mkdir()
    text=HEADER+'<!-- slide-id: old-page -->\n# Prior section\n\nKeep this content.\n'
    (source/'section.md').write_text(text)
    target=s.task/'.mpres/work/test/output'
    target.parent.mkdir(parents=True)
    result=prepare_edit_source(s.task,source,target,entrypoint='section.md')
    assert result['state']=='prepared'
    assert (target/'presentation.md').read_text()==(source/'section.md').read_text()
    assert not (source/'presentation.md').exists()


def test_child_runtime_override_resolves_original_parent(compact_root):
    # Construct an actual confirmed parent override; never edit an immutable config.
    from mpres.control.store import Store
    from mpres.control.planning import runtime_origin
    s=Service.create(compact_root,'override','Runtime inheritance fixture')
    cfg=read_yaml(s.task/'task.yaml');cfg.update(workflow='full',delivery='all')
    cfg['presentations']=[{'id':'p02','title':'Parent','units':[{'id':u,'title':u,'brief':'Explain the mathematical concept with a worked example','sources':[]} for u in ('l01','l02')]}]
    write_yaml_atomic(s.task/'task.yaml',cfg)
    profile=read_yaml(s.task/'TASK-RUNTIME-PROFILE.yaml')
    profile['presentation_overrides']={'p02':{'author':{'model':'chosen-test-model','reasoning_effort':'high'}}}
    write_yaml_atomic(s.task/'TASK-RUNTIME-PROFILE.yaml',profile)
    s.present();s.confirm('user');s.materialize();Workflow(s.task).ensure()
    with s.store.transaction() as c:c.execute("UPDATE task SET status='paused'")
    split(s);s.materialize()
    with s.store.transaction() as c:
        parent=c.execute("SELECT * FROM jobs WHERE presentation='p02'").fetchone()
        child=c.execute("SELECT * FROM jobs WHERE presentation='p02-01'").fetchone()
        assert s.expected_runtime(c,child)==s.expected_runtime(c,parent)
        assert s.expected_runtime(c,child)['model']=='chosen-test-model'
