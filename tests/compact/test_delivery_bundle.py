"""Delivery ZIP correctness; native_double is not a real browser acceptance."""
from __future__ import annotations

import json
import subprocess
import zipfile
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
    service = full_task(root, decks=decks, delivery=delivery)
    runner, result = run_host(service, Host(findings=True))
    return service, runner, result


def test_runner_automatically_bundles_committed_pdf_and_exact_source(compact_root, native_double):
    service, _, last = delivered(compact_root, decks=2)
    package = last['workflow']['delivery_package']
    assert package['state'] == 'ready' and package['presentations'] == ['p01', 'p02']
    assert service.status()['delivery_package']['path'] == package['path']
    source_before = {p: p.read_bytes() for p in (service.task/'.mpres/artifacts').rglob('presentation.md')}
    with zipfile.ZipFile(package['path']) as archive:
        assert archive.testzip() is None
        for release in service.store.rows('SELECT * FROM releases'):
            pid = release['presentation']
            source = service.store.rows('SELECT path FROM artifacts WHERE id=?', (release['artifact_id'],))[0]['path']
            assert archive.read(f'full-delivery/{pid}/{pid}.pdf') == (service.task/release['pdf_path']).read_bytes()
            assert archive.read(f'full-delivery/{pid}/{pid}.md') == (service.task/source/'presentation.md').read_bytes()
            assert archive.read(f'full-delivery/{pid}/theme.css') == (service.task/source/'theme.css').read_bytes()
        assert all('presentation.md' not in n for n in archive.namelist())
        assert all('.mpres' not in n and 'task.yaml' not in n for n in archive.namelist())
    assert all(p.read_bytes() == text for p, text in source_before.items())


@pytest.mark.parametrize('mode', ['pilot', 'each'])
def test_incremental_bundle_at_feedback_pause_then_cumulative(compact_root, native_double, mode):
    service, runner, result = delivered(compact_root, decks=2, delivery=mode)
    assert result['status'] == 'paused'
    target = Path(result['workflow']['delivery_package']['path'])
    with zipfile.ZipFile(target) as archive:
        assert all('/p01/' in n for n in archive.namelist())
    Workflow(service.task).continue_delivery('user', 'Continue with the confirmed plan')
    final = runner.run(cycles=60, interval=0)
    assert final['status'] == 'completed'
    assert final['workflow']['delivery_package']['path'] == str(target)
    with zipfile.ZipFile(target) as archive:
        assert any('/p02/' in n for n in archive.namelist())
    assert list((service.task/'deliverables').glob('*.zip')) == [target]


def test_assets_and_chinese_filenames_keep_relative_paths(compact_root, native_double):
    service = full_task(compact_root, decks=1)
    host = Host()
    def with_asset(request):
        response = host(request)
        if request['operation'] == 'run' and request['packet']['kind'] == 'write':
            out = Path(request['packet']['writable_directory'])
            (out/'assets').mkdir()
            (out/'assets/向量.svg').write_text('<svg xmlns="http://www.w3.org/2000/svg" width="80" height="60"><rect width="80" height="60"/></svg>')
            with (out/'presentation.md').open('a') as source:
                source.write('\n![Vector](assets/向量.svg)\n')
        return response
    _, last = run_host(service, with_asset)
    assert last['status'] == 'completed', last
    with zipfile.ZipFile(last['workflow']['delivery_package']['path']) as archive:
        assert archive.read('full-delivery/p01/assets/向量.svg')
        assert 'assets/向量.svg' in archive.read('full-delivery/p01/p01.md').decode()


def test_repeat_bundle_no_file_or_event_churn_and_no_model_calls(compact_root, native_double):
    service, runner, result = delivered(compact_root)
    target = Path(result['workflow']['delivery_package']['path'])
    data, mtime = target.read_bytes(), target.stat().st_mtime_ns
    events = service.store.rows("SELECT * FROM events WHERE kind='delivery.bundled'")
    attempts = service.store.rows('SELECT * FROM attempts')
    (service.task/'content/presentation.md').write_text('Unpublished changed draft')
    assert Delivery(service.task).bundle()['already_bundled'] is True
    runner.run(cycles=2, interval=0)
    assert target.read_bytes() == data and target.stat().st_mtime_ns == mtime
    assert service.store.rows("SELECT * FROM events WHERE kind='delivery.bundled'") == events
    assert service.store.rows('SELECT * FROM attempts') == attempts


def test_no_delivery_does_not_package_drafts(compact_root):
    service = full_task(compact_root, decks=1)
    (service.task/'content/presentation.md').write_text('draft')
    assert Delivery(service.task).ensure()['state'] == 'not_applicable'
    with pytest.raises(MPresError, match='No committed deliveries'):
        Delivery(service.task).bundle()
    assert not list((service.task/'deliverables').iterdir())


def test_prepared_release_is_not_exported(compact_root, native_double, monkeypatch):
    import mpres.control.workflow as module
    service = full_task(compact_root, decks=1)
    original = module.event
    def interrupted(conn, kind, detail, job=None):
        if kind == 'deck.delivered':
            raise OSError('Publication interrupted before commit')
        return original(conn, kind, detail, job)
    monkeypatch.setattr(module, 'event', interrupted)
    run_host(service, Host())
    assert (service.task/'deliverables/p01.pdf').is_file()
    assert service.store.rows('SELECT state FROM releases')[0]['state'] == 'prepared'
    assert Delivery(service.task).ensure()['state'] == 'not_applicable'
    assert not list((service.task/'deliverables').glob('*.zip'))


def test_bundle_write_failure_does_not_undo_publication(compact_root, native_double, monkeypatch):
    original = Delivery._write
    def fail(*args):
        raise OSError('Injected ZIP write failure')
    monkeypatch.setattr(Delivery, '_write', staticmethod(fail))
    service, runner, last = delivered(compact_root)
    assert service.status()['status'] == 'completed'  # PDF commit is not undone.
    assert last['status'] == 'blocked'
    assert last['workflow']['delivery_package']['state'] == 'failed'
    assert not list((service.task/'deliverables').glob('*.zip'))
    assert not list((service.task/'.mpres/delivery-staging').glob('*.zip'))
    before = service.store.rows('SELECT * FROM attempts')
    monkeypatch.setattr(Delivery, '_write', staticmethod(original))
    result = runner.run(cycles=2, interval=0)
    assert result['status'] == 'completed'
    assert result['workflow']['delivery_package']['state'] == 'ready'
    assert service.store.rows('SELECT * FROM attempts') == before


@pytest.mark.parametrize('missing', ['pdf', 'markdown'])
def test_missing_pair_preserves_previous_zip(compact_root, native_double, missing):
    service, _, last = delivered(compact_root)
    target = Path(last['workflow']['delivery_package']['path'])
    old = target.read_bytes()
    if missing == 'pdf':
        victim = service.task/'deliverables/p01.pdf'
    else:
        row = Delivery(service.task)._releases()[0]
        victim = service.task/row['source_path']/'presentation.md'
    victim.parent.chmod(0o755)
    victim.unlink()
    with pytest.raises(MPresError, match='missing'):
        Delivery(service.task).bundle()
    assert target.read_bytes() == old


def test_changed_pdf_or_symlink_cannot_be_exported(compact_root, native_double):
    service, _, last = delivered(compact_root)
    target = Path(last['workflow']['delivery_package']['path'])
    old = target.read_bytes()
    pdf = service.task/'deliverables/p01.pdf'
    saved = pdf.read_bytes()
    pdf.chmod(0o644); pdf.write_bytes(b'Not the published PDF')
    with pytest.raises(MPresError, match='changed'):
        Delivery(service.task).bundle()
    assert target.read_bytes() == old
    pdf.write_bytes(saved)
    release = Delivery(service.task)._releases()[0]
    source = service.task/release['source_path']
    source.chmod(0o755)
    (source/'leak.txt').symlink_to(service.task/'TASK.md')
    with pytest.raises(MPresError, match='[Ss]ymlink|escaped'):
        Delivery(service.task).bundle()
    assert target.read_bytes() == old


def test_corrupted_or_missing_zip_can_be_rebuilt(compact_root, native_double):
    service, runner, last = delivered(compact_root)
    target = Path(last['workflow']['delivery_package']['path'])
    original = target.read_bytes()
    target.write_bytes(b'interrupted older archive')
    assert Delivery(service.task).status()['state'] == 'pending'
    runner.run(cycles=2, interval=0)
    assert target.read_bytes() == original
    target.unlink()
    assert Delivery(service.task).bundle()['state'] == 'ready'
    assert target.read_bytes() == original


def test_cli_repackages_old_committed_task_without_new_approval(compact_root, native_double, capsys):
    service, _, last = delivered(compact_root)
    target = Path(last['workflow']['delivery_package']['path'])
    target.unlink()
    configs = service.store.rows('SELECT * FROM configs')
    assert main(['--root', str(compact_root), 'workflow', 'bundle', 'full']) == 0
    assert json.loads(capsys.readouterr().out)['path'] == str(target)
    assert target.is_file() and service.store.rows('SELECT * FROM configs') == configs


def test_concurrent_bundlers_publish_complete_archive(compact_root, native_double):
    service, _, last = delivered(compact_root)
    target = Path(last['workflow']['delivery_package']['path'])
    target.unlink()
    with ThreadPoolExecutor(max_workers=3) as pool:
        result = list(pool.map(lambda _: Delivery(service.task).bundle(), range(3)))
    assert all(r['state'] == 'ready' for r in result)
    assert Delivery(service.task).bundle()['already_bundled'] is True
    assert not list((service.task/'.mpres/delivery-staging').glob('*.zip'))


def test_gitignore_ignores_delivery_bundles_not_source_releases(tmp_path):
    root = Path(__file__).resolve().parents[2]
    (tmp_path/'.gitignore').write_bytes((root/'.gitignore').read_bytes())
    subprocess.run(['git', 'init', '-q', str(tmp_path)], check=True)
    for name in ['tasks/demo/deliverables/demo-delivery.zip', 'elsewhere/deliverables/demo-delivery.zip']:
        result = subprocess.run(['git', '-C', str(tmp_path), 'check-ignore', name], capture_output=True)
        assert result.returncode == 0
    for name in ['marp-presentation-orchestrator-v0.6.13-source.zip', 'sources/textbook.zip', 'tasks/demo/deliverables/p01.md']:
        assert subprocess.run(['git', '-C', str(tmp_path), 'check-ignore', name], capture_output=True).returncode == 1


def test_renamed_source_collision_is_rejected_without_overwriting_bundle(compact_root, native_double):
    service, _, last = delivered(compact_root)
    target = Path(last['workflow']['delivery_package']['path'])
    before = target.read_bytes()
    row = Delivery(service.task)._releases()[0]
    source = service.task/row['source_path']
    source.chmod(0o755)
    (source/'P01.md').write_text('Would collide on a case-insensitive extraction target')
    with pytest.raises(MPresError, match='collision'):
        Delivery(service.task).bundle()
    assert target.read_bytes() == before


def test_symlink_bundle_destination_never_overwrites_external_file(compact_root, native_double):
    service, runner, last = delivered(compact_root)
    target = Path(last['workflow']['delivery_package']['path'])
    outside = compact_root/'do-not-change.zip'
    outside.write_bytes(b'not a generated bundle')
    target.unlink(); target.symlink_to(outside)
    with pytest.raises(MPresError, match='escaped|[Ss]ymlink'):
        Delivery(service.task).bundle()
    result = runner.run(cycles=2, interval=0)
    assert result['status'] == 'blocked'
    assert result['workflow']['delivery_package']['state'] == 'failed'
    assert outside.read_bytes() == b'not a generated bundle'
