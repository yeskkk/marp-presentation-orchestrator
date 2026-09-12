"""Direct delivery correctness. Host/full renderer here are marked test doubles.

The previous ZIP tests are migrated to the replacement directory contract, not
removed: committed pairing, pause/resume, assets, idempotence, failures, CLI,
concurrency, path boundaries and Git visibility all remain covered.
"""
from __future__ import annotations
import json
import os
import shutil
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import pytest
from mpres.control.cli import main
from mpres.control.delivery import Delivery
from mpres.control.workflow import Workflow
from mpres.util import MPresError
from test_relational_control import compact_root
from test_deck_workflow import full_task, Host, run_host, native_double


def delivered(root, decks=1, delivery='all'):
    service=full_task(root,decks=decks,delivery=delivery)
    runner,last=run_host(service,Host(findings=True))
    assert last['status'] in {'completed','paused','blocked'},last
    return service,runner,last


def tree(folder):
    return {p.relative_to(folder).as_posix():p.read_bytes() for p in folder.rglob('*') if p.is_file()}


def canonical_pdf(service):
    return service.task/Delivery(service.task)._releases()[0]['pdf_path']


def test_runner_materializes_committed_pdf_and_exact_source(compact_root,native_double):
    service,_,last=delivered(compact_root,decks=2)
    view=last['workflow']['delivery_package']
    assert view['state']=='ready' and view['format']=='directory'
    assert view['presentations']==['p01','p02']
    assert service.status()['delivery_package']['path']==view['path']
    before={p:p.read_bytes() for p in (service.task/'.mpres/artifacts').rglob('presentation.md')}
    for release in Delivery(service.task)._releases():
        pid=release['presentation']; public=service.task/'deliverables'/pid
        assert (public/f'{pid}.pdf').read_bytes()==(service.task/release['pdf_path']).read_bytes()
        assert (public/f'{pid}.md').read_bytes()==(service.task/release['source_path']/'presentation.md').read_bytes()
        assert (public/'theme.css').read_bytes()==(service.task/release['source_path']/'theme.css').read_bytes()
        assert not (public/'presentation.md').exists()
        assert release['pdf_path'].startswith('.mpres/releases/')
    assert all(p.read_bytes()==text for p,text in before.items())
    assert sorted(p.name for p in Path(view['path']).iterdir())==['p01','p02']
    assert not list((service.task/'deliverables').rglob('*.zip'))


@pytest.mark.parametrize('mode',['pilot','each'])
def test_incremental_view_at_feedback_pause_then_cumulative(compact_root,native_double,mode):
    service,runner,result=delivered(compact_root,decks=2,delivery=mode)
    assert result['status']=='paused'
    target=Path(result['workflow']['delivery_package']['path'])
    assert sorted(p.name for p in target.iterdir())==['p01']
    before=tree(target/'p01')
    Workflow(service.task).continue_delivery('user','Continue the confirmed plan')
    final=runner.run(cycles=60,interval=0)
    assert final['status']=='completed'
    assert final['workflow']['delivery_package']['path']==str(target)
    assert sorted(p.name for p in target.iterdir())==['p01','p02']
    assert tree(target/'p01')==before


def test_assets_and_chinese_filenames_keep_relative_paths(compact_root,native_double):
    service=full_task(compact_root,decks=1);host=Host()
    def with_asset(request):
        response=host(request)
        if request['operation']=='run' and request['packet']['kind']=='write':
            out=Path(request['packet']['writable_directory']);(out/'assets').mkdir()
            (out/'assets/向量.svg').write_text('<svg xmlns="http://www.w3.org/2000/svg" width="80" height="60"><rect width="80" height="60"/></svg>')
            with (out/'presentation.md').open('a') as s:s.write('\n![Vector](assets/向量.svg)\n')
        return response
    _,last=run_host(service,with_asset)
    assert last['status']=='completed',last
    target=Path(last['workflow']['delivery_package']['path'])/'p01'
    assert (target/'assets/向量.svg').is_file()
    assert 'assets/向量.svg' in (target/'p01.md').read_text()


def test_repeat_materialize_no_file_or_event_churn_or_model_calls(compact_root,native_double):
    service,runner,last=delivered(compact_root);target=Path(last['workflow']['delivery_package']['path'])
    before=tree(target);mtimes={p:p.stat().st_mtime_ns for p in target.rglob('*')}
    events=service.store.rows("SELECT * FROM events WHERE kind='delivery.materialized'")
    attempts=service.store.rows('SELECT * FROM attempts')
    (service.task/'content/presentation.md').write_text('unpublished draft')
    assert Delivery(service.task).materialize()['already_materialized']
    runner.run(cycles=2,interval=0)
    assert tree(target)==before and all(p.stat().st_mtime_ns==t for p,t in mtimes.items())
    assert service.store.rows("SELECT * FROM events WHERE kind='delivery.materialized'")==events
    assert service.store.rows('SELECT * FROM attempts')==attempts


def test_no_delivery_does_not_export_drafts(compact_root):
    service=full_task(compact_root,decks=1)
    (service.task/'content/presentation.md').write_text('draft')
    assert Delivery(service.task).ensure()['state']=='not_applicable'
    with pytest.raises(MPresError,match='No committed deliveries'):Delivery(service.task).materialize()
    assert not list((service.task/'deliverables').iterdir())


def test_prepared_release_is_not_visible(compact_root,native_double,monkeypatch):
    import mpres.control.workflow as module
    service=full_task(compact_root,decks=1);original=module.event
    def interrupted(conn,kind,detail,job=None):
        if kind=='deck.delivered':raise OSError('Publication interrupted before commit')
        return original(conn,kind,detail,job)
    monkeypatch.setattr(module,'event',interrupted)
    run_host(service,Host())
    assert (service.task/'.mpres/releases/p01/r001/p01.pdf').is_file()
    assert service.store.rows('SELECT state FROM releases')[0]['state']=='prepared'
    assert Delivery(service.task).ensure()['state']=='not_applicable'
    assert not list((service.task/'deliverables').iterdir())


def test_directory_write_failure_does_not_undo_committed_release(compact_root,native_double,monkeypatch):
    original=Delivery._write
    def fail(*args):raise OSError('Injected copy failure')
    monkeypatch.setattr(Delivery,'_write',staticmethod(fail))
    service,runner,last=delivered(compact_root)
    assert service.status()['status']=='completed' and last['status']=='blocked'
    assert last['workflow']['delivery_package']['state']=='failed'
    assert not list((service.task/'deliverables').iterdir())
    assert not list((service.task/'.mpres/delivery-staging').iterdir())
    before=service.store.rows('SELECT * FROM attempts')
    monkeypatch.setattr(Delivery,'_write',staticmethod(original))
    final=runner.run(cycles=2,interval=0)
    assert final['status']=='completed' and final['workflow']['delivery_package']['state']=='ready'
    assert service.store.rows('SELECT * FROM attempts')==before


@pytest.mark.parametrize('missing',['pdf','markdown'])
def test_missing_input_preserves_previous_directory(compact_root,native_double,missing):
    service,_,last=delivered(compact_root);target=Path(last['workflow']['delivery_package']['path']);before=tree(target)
    row=Delivery(service.task)._releases()[0]
    victim=canonical_pdf(service) if missing=='pdf' else service.task/row['source_path']/'presentation.md'
    victim.parent.chmod(0o755);victim.unlink()
    with pytest.raises(MPresError,match='missing'):Delivery(service.task).materialize()
    assert tree(target)==before


def test_changed_pdf_and_symlink_source_cannot_be_exported(compact_root,native_double):
    service,_,last=delivered(compact_root);target=Path(last['workflow']['delivery_package']['path']);before=tree(target)
    pdf=canonical_pdf(service);saved=pdf.read_bytes();pdf.chmod(0o644);pdf.write_bytes(b'changed')
    with pytest.raises(MPresError,match='changed'):Delivery(service.task).materialize()
    assert tree(target)==before;pdf.write_bytes(saved)
    release=Delivery(service.task)._releases()[0];source=service.task/release['source_path'];source.chmod(0o755)
    (source/'leak.txt').symlink_to(service.task/'TASK.md')
    with pytest.raises(MPresError,match='[Ss]ymlink|escaped'):Delivery(service.task).materialize()
    assert tree(target)==before


def test_edited_directory_preserved_missing_directory_rebuilds(compact_root,native_double):
    service,runner,last=delivered(compact_root);target=Path(last['workflow']['delivery_package']['path'])/'p01'
    original=tree(target);(target/'p01.md').write_text('user edits, do not overwrite')
    assert Delivery(service.task).status()['state']=='pending'
    assert runner.run(cycles=2,interval=0)['status']=='blocked'
    assert (target/'p01.md').read_text()=='user edits, do not overwrite'
    shutil.rmtree(target)
    assert Delivery(service.task).materialize()['state']=='ready'
    assert tree(target)==original


def test_cli_materializes_old_committed_task_without_new_approval(compact_root,native_double,capsys):
    service,_,last=delivered(compact_root);target=Path(last['workflow']['delivery_package']['path'])
    shutil.rmtree(target/'p01');configs=service.store.rows('SELECT * FROM configs')
    assert main(['--root',str(compact_root),'workflow','materialize','full'])==0
    assert json.loads(capsys.readouterr().out)['path']==str(target)
    assert (target/'p01/p01.md').is_file() and service.store.rows('SELECT * FROM configs')==configs
    assert main(['--root',str(compact_root),'workflow','bundle','full'])==0
    assert json.loads(capsys.readouterr().out)['archive_created'] is False


def test_concurrent_exports_publish_complete_directories(compact_root,native_double):
    service,_,last=delivered(compact_root);target=Path(last['workflow']['delivery_package']['path'])
    shutil.rmtree(target/'p01')
    with ThreadPoolExecutor(max_workers=3) as pool:
        results=list(pool.map(lambda _:Delivery(service.task).materialize(),range(3)))
    assert all(r['state']=='ready' for r in results)
    assert Delivery(service.task).materialize()['already_materialized']
    assert not list((service.task/'.mpres/delivery-staging').iterdir())


def test_gitignore_tracks_delivery_source_not_pdf_or_zip(tmp_path):
    root=Path(__file__).resolve().parents[2]
    (tmp_path/'.gitignore').write_bytes((root/'.gitignore').read_bytes())
    subprocess.run(['git','init','-q',str(tmp_path)],check=True)
    for name in ['tasks/demo/deliverables/p01/p01.pdf','tasks/demo/deliverables/old.zip','elsewhere/deliverables/x.zip']:
        assert subprocess.run(['git','-C',str(tmp_path),'check-ignore',name],capture_output=True).returncode==0
    for name in ['marp-presentation-orchestrator-v0.7.1-source.zip','sources/textbook.zip','tasks/demo/deliverables/p01/p01.md','tasks/demo/deliverables/p01/theme.css','tasks/demo/deliverables/p01/assets/g.plot.json','tasks/demo/deliverables/p01/assets/g.svg','tasks/demo/deliverables/p01/assets/g.py']:
        assert subprocess.run(['git','-C',str(tmp_path),'check-ignore',name],capture_output=True).returncode==1


def test_renamed_source_collision_preserves_directory(compact_root,native_double):
    service,_,last=delivered(compact_root);target=Path(last['workflow']['delivery_package']['path']);before=tree(target)
    row=Delivery(service.task)._releases()[0];source=service.task/row['source_path'];source.chmod(0o755)
    (source/'P01.md').write_text('case insensitive collision')
    with pytest.raises(MPresError,match='collision'):Delivery(service.task).materialize()
    assert tree(target)==before


def test_symlink_destination_never_overwrites_external_data(compact_root,native_double):
    service,runner,last=delivered(compact_root);target=Path(last['workflow']['delivery_package']['path'])/'p01'
    outside=compact_root/'do-not-change';outside.mkdir();(outside/'memo.md').write_text('keep')
    shutil.rmtree(target);target.symlink_to(outside,target_is_directory=True)
    with pytest.raises(MPresError,match='escaped|[Ss]ymlink'):Delivery(service.task).materialize()
    assert runner.run(cycles=2,interval=0)['status']=='blocked'
    assert (outside/'memo.md').read_text()=='keep'


def test_recover_crash_between_directory_renames(compact_root,native_double):
    service,_,last=delivered(compact_root);target=Path(last['workflow']['delivery_package']['path'])/'p01'
    original=tree(target);backup=service.task/'.mpres/delivery-staging/previous-p01'
    os.replace(target,backup)
    assert Delivery(service.task).materialize()['state']=='ready'
    assert tree(target)==original and not backup.exists()


def test_lost_projection_receipt_reconciles_exact_bytes(compact_root,native_double):
    service,_,last=delivered(compact_root);target=Path(last['workflow']['delivery_package']['path']);before=tree(target)
    with service.store.transaction() as conn:conn.execute("DELETE FROM events WHERE kind='delivery.materialized'")
    assert Delivery(service.task).materialize()['state']=='ready'
    assert tree(target)==before


def test_existing_legacy_pdf_and_zip_are_preserved(compact_root,native_double):
    service,_,last=delivered(compact_root);release=Delivery(service.task)._releases()[0]
    old=service.task/'deliverables/p01.pdf';old.write_bytes(canonical_pdf(service).read_bytes())
    oldzip=service.task/'deliverables/full-delivery.zip';oldzip.write_bytes(b'legacy archive left unchanged')
    with service.store.transaction() as conn:
        conn.execute("UPDATE releases SET pdf_path='deliverables/p01.pdf'")
        conn.execute("UPDATE release_versions SET pdf_path='deliverables/p01.pdf' WHERE revision=1")
    configs=service.store.rows('SELECT * FROM configs')
    assert Delivery(service.task).materialize()['state']=='ready'
    assert old.read_bytes()==(service.task/release['checked_pdf_path']).read_bytes()
    assert oldzip.read_bytes()==b'legacy archive left unchanged'
    assert service.store.rows('SELECT * FROM configs')==configs


def test_unmanaged_extra_file_is_not_pruned(compact_root,native_double):
    service,_,last=delivered(compact_root);target=Path(last['workflow']['delivery_package']['path'])/'p01'
    (target/'my-notes.md').write_text('private annotation')
    with pytest.raises(MPresError,match='modified/unmanaged'):Delivery(service.task).materialize()
    assert (target/'my-notes.md').read_text()=='private annotation'


def test_changed_release_set_aborts_before_replacement(compact_root,native_double,monkeypatch):
    service,_,last=delivered(compact_root);target=Path(last['workflow']['delivery_package']['path'])/'p01'
    shutil.rmtree(target);export=Delivery(service.task);original=export._releases
    monkeypatch.setattr(export,'_releases',lambda conn=None: [] if conn else original())
    with pytest.raises(MPresError,match='changed during export'):export.materialize()
    assert not target.exists()


def test_partial_copy_never_becomes_public(compact_root,native_double,monkeypatch):
    service,_,last=delivered(compact_root);target=Path(last['workflow']['delivery_package']['path'])/'p01'
    shutil.rmtree(target)
    def partial(folder,entries):
        folder.mkdir();(folder/'p01.pdf').write_bytes(b'partial');raise OSError('disk full')
    monkeypatch.setattr(Delivery,'_write',staticmethod(partial))
    assert Delivery(service.task).ensure()['state']=='failed'
    assert not target.exists() and not list((service.task/'.mpres/delivery-staging').iterdir())
