from __future__ import annotations

import json
import shutil
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from mpres.control.files import copy_tree, inside, remove_tree
from mpres.control.migration import import_legacy
from mpres.control.service import CHANNELS, Service
from mpres.util import MPresError, read_yaml, task_path, write_yaml_atomic

ROOT = Path(__file__).resolve().parents[2]

@pytest.fixture
def compact_root(tmp_path):
    shutil.copytree(ROOT/'templates'/'compact',tmp_path/'templates'/'compact')
    return tmp_path


def prepare(root, slug='sample', count=2):
    service=Service.create(root,slug,'Vectors')
    from feedback_fixtures import infrastructure_only
    infrastructure_only(service)
    settings=read_yaml(service.task/'task.yaml'); settings['workflow']='authoring'
    settings['presentations']=[{'id':'p01','title':'Vectors','units':[
        {'id':f'l{i+1:02d}','title':f'Meeting {i+1}', 'brief':'Explain quantities, units and a worked example.','sources':[]}
        for i in range(count)]}]
    settings['provider']['handle_limit']=16
    write_yaml_atomic(service.task/'task.yaml',settings)
    service.present();service.confirm('user')
    service.materialize()
    return service


def register(service, handle='h1', family='author', effort='medium'):
    return service.register_session(handle,family,'gpt-5.6-sol',effort,'provider-created:'+handle)


def source_for(service):
    source=service.task/'content'/'unit'
    source.mkdir(parents=True,exist_ok=True)
    (source/'presentation.md').write_text('---\nmarp: true\n---\n<!-- slide-id: p01-l01-s1 -->\n# Example\n')
    (source/'theme.css').write_text('/* @theme mathist-academic */')
    return source


def completed(service):
    register(service)
    attempt=service.bind(service.jobs()[0]['id'],'h1')
    service.started(attempt['id'],'started-h1')
    result=service.submit(attempt['id'],{'summary':'A worked example'},source=source_for(service))
    return attempt,result


def test_only_three_user_documents(compact_root):
    service=Service.create(compact_root,'tiny','Tiny')
    assert sorted(p.name for p in service.task.iterdir() if p.is_file()) == ['TASK-RUNTIME-PROFILE.yaml','TASK.md','task.yaml']
    assert not list(service.task.rglob('ASSIGNMENT-*'))
    assert not list(service.task.rglob('STAGE-ARTIFACT.md'))
    assert not (service.task/'THREAD-REGISTRY.yaml').exists()


def test_missing_semantic_plan_cannot_be_presented(compact_root):
    service=Service.create(compact_root,'tiny','Tiny')
    with pytest.raises(MPresError,match='semantic course plan'):service.present()


def test_fixed_defaults_and_confirmation(compact_root):
    service=prepare(compact_root)
    profile=read_yaml(service.task/'TASK-RUNTIME-PROFILE.yaml')
    assert [profile['defaults'][k]['reasoning_effort'] for k in ('planner','author','reviewer')] == ['high','medium','low']
    assert service.confirm('user')['already_confirmed']
    profile['defaults']['author']['reasoning_effort']='high'
    write_yaml_atomic(service.task/'TASK-RUNTIME-PROFILE.yaml',profile)
    with pytest.raises(MPresError,match='changed'):service.materialize()


def test_presented_config_cannot_change_silently(compact_root):
    service=prepare(compact_root)
    settings=read_yaml(service.task/'task.yaml'); settings['workflow']='authoring';settings['author_concurrency']=5
    write_yaml_atomic(service.task/'task.yaml',settings)
    with pytest.raises(MPresError):service.confirm('user')


def test_database_config_rows_are_immutable(compact_root):
    service=prepare(compact_root)
    with pytest.raises(sqlite3.IntegrityError,match='immutable'):
        with service.store.transaction() as c:c.execute("UPDATE configs SET runtime_json='{}'")


def test_materialize_is_idempotent(compact_root):
    service=prepare(compact_root)
    before=service.jobs();service.materialize()
    assert before==service.jobs()
    assert len(before)==2


def test_bad_assignment_id_is_rejected_before_binding(compact_root):
    service=prepare(compact_root);register(service)
    for bad in ('lesson-p01-l02','p01-l04'):
        with pytest.raises(MPresError,match='Unknown job'):service.bind(bad,'h1')
    assert service.store.rows('SELECT * FROM attempts')==[]
    assert service.bind(service.jobs()[0]['id'],'h1')['state']=='reserved'


def test_coordinates_must_match_approved_plan(compact_root):
    service=prepare(compact_root)
    with pytest.raises(MPresError):
        with service.store.transaction() as c:service.ensure_job(c,key='wrong',presentation='p02',kind='write',plan_item_id=1)
    assert len(service.jobs())==2


def test_wrong_runtime_rejected(compact_root):
    service=prepare(compact_root);register(service,effort='high')
    with pytest.raises(MPresError,match='incompatible'):service.bind(service.jobs()[0]['id'],'h1')
    assert service.store.rows('SELECT * FROM attempts')==[]


def test_concurrent_bind_has_single_winner(compact_root):
    service=prepare(compact_root);register(service)
    jobs=service.jobs()
    def bind(job):
        try:service.bind(job['id'],'h1');return True
        except MPresError:return False
    with ThreadPoolExecutor(max_workers=2) as pool:result=list(pool.map(bind,jobs))
    assert result.count(True)==1
    assert len(service.store.rows('SELECT * FROM attempts'))==1


def test_foreign_keys_and_rollback(compact_root):
    service=prepare(compact_root)
    with pytest.raises(sqlite3.IntegrityError):
        with service.store.transaction() as c:
            c.execute("UPDATE task SET title='bad'")
            c.execute("INSERT INTO dependencies VALUES('bad','missing')")
    assert service.status()['title']=='Vectors'


def test_submit_requires_execution_ack(compact_root):
    service=prepare(compact_root);register(service)
    attempt=service.bind(service.jobs()[0]['id'],'h1')
    with pytest.raises(MPresError,match='acknowledged'):service.submit(attempt['id'],{'summary':'Done'},source=source_for(service))


def test_submission_idempotent_and_frozen(compact_root):
    service=prepare(compact_root);attempt,result=completed(service)
    assert service.submit(attempt['id'],{'summary':'A worked example'},source=source_for(service))['already_submitted']
    with pytest.raises(MPresError,match='differs'):service.submit(attempt['id'],{'summary':'Different'},source=source_for(service))
    assert len(service.store.rows('SELECT * FROM artifacts'))==1
    source_for(service).joinpath('presentation.md').write_text('changed draft')
    artifact=service.store.rows('SELECT * FROM artifacts')[0]
    assert 'changed draft' not in (service.task/artifact['path']/'presentation.md').read_text()
    assert not (service.task/artifact['path']/'presentation.md').stat().st_mode & 0o200


def test_uncertain_execution_never_restarts(compact_root):
    service=prepare(compact_root);register(service)
    attempt=service.bind(service.jobs()[0]['id'],'h1')
    service.uncertain(attempt['id'],'provider receipt lost')
    with pytest.raises(MPresError):service.bind(service.jobs()[0]['id'],'h1')
    with pytest.raises(MPresError):service.bind(service.jobs()[1]['id'],'h1')


def test_different_review_channels_cannot_share_one_handle(compact_root):
    service=prepare(compact_root);_,result=completed(service);aid=result['artifact_id']
    register(service,'review','reviewer','low')
    ids=[]
    with service.store.transaction() as c:
        for channel in CHANNELS:
            ids.append(service.ensure_job(c,key=f'review:{channel}',presentation='p01',kind='review',round=1,channel=channel,artifact=aid))
    a=service.bind(ids[0],'review');service.started(a['id'],'review-start')
    service.submit(a['id'],{'summary':'No issues','findings':[]})
    with pytest.raises(MPresError,match='independent'):service.bind(ids[1],'review')


def test_usage_unknown_is_not_zero(compact_root):
    service=prepare(compact_root);a,_=completed(service)
    service.record_usage(a['id'],'c1',{'input_tokens':100,'cached_input_tokens':90,'output_tokens':None})
    report=service.metrics()
    assert report['fields']['output_tokens']['total'] is None
    assert report['fields']['input_tokens']['total']==100
    assert report['record_field_coverage']==0
    service.record_usage(a['id'],'c1',{'input_tokens':100,'cached_input_tokens':90,'output_tokens':None})
    assert service.metrics()['calls_observed']==1
    with pytest.raises(MPresError):service.record_usage(a['id'],'c1',{'input_tokens':110})


def test_no_usage_is_unknown(compact_root):
    service=prepare(compact_root);completed(service)
    assert service.metrics()['attempt_coverage']==0
    assert service.metrics()['fields']['total_tokens']['total'] is None


def test_legacy_api_cannot_create_second_state_store(compact_root):
    service=prepare(compact_root)
    with pytest.raises(MPresError,match='compact SQLite'):task_path(compact_root,'sample')
    assert not (service.task/'state').exists()


def test_backup_is_consistent_and_not_overwritten(compact_root,tmp_path):
    service=prepare(compact_root);completed(service)
    target=tmp_path/'export.sqlite3';service.store.backup(target)
    conn=sqlite3.connect(target)
    assert conn.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
    assert conn.execute('SELECT count(*) FROM artifacts').fetchone()[0]==1
    conn.close()
    with pytest.raises(MPresError):service.store.backup(target)


def test_copy_semantics_and_path_escape(tmp_path):
    source=tmp_path/'source';source.mkdir();(source/'presentation.md').write_text('example');(source/'presentation.md').chmod(0o444)
    copy_tree(source,tmp_path/'edit',read_only=False)
    assert (tmp_path/'edit'/'presentation.md').stat().st_mode & 0o200
    with pytest.raises(MPresError):inside(tmp_path,'../escape')
    (source/'link').symlink_to(source/'presentation.md')
    with pytest.raises(MPresError):copy_tree(source,tmp_path/'bad',read_only=True)


def test_import_preserves_unverified_content_not_status(compact_root,tmp_path):
    old=tmp_path/'old';(old/'state').mkdir(parents=True)
    (old/'state'/'task.json').write_text(json.dumps({'title':'Old task','presentations':[{'id':'p01','title':'Old deck','content_units':[{'id':'l01','title':'Old unit','status':'handoff_ready'}]}]}))
    (old/'TASK.md').write_text('# Actual teaching requirements')
    source=old/'workers'/'lesson-authors'/'p01'/'l01'/'source';source.mkdir(parents=True)
    (source/'section.md').write_text('# Existing content')
    before={p.relative_to(old):p.read_bytes() for p in old.rglob('*') if p.is_file()}
    result=import_legacy(compact_root,old,'imported')
    service=Service(Path(result['task']))
    assert service.status()['status']=='draft'
    assert service.status()['artifacts'][0]['verified']==0
    assert service.store.rows('SELECT * FROM sessions')==[]
    assert before=={p.relative_to(old):p.read_bytes() for p in old.rglob('*') if p.is_file()}
    with pytest.raises(MPresError,match='semantic brief'):service.present()
