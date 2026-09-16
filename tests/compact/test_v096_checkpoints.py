from pathlib import Path
from contextlib import closing
import json
import shutil
import sqlite3
import pytest
from mpres.util import MPresError
from mpres.control.checkpoints import plan,apply,resume,status,policy,maybe_run,directory_usage
from mpres.control.compatibility import current_state,open_task
from mpres.control.delivery import Delivery
from mpres.control.maintenance_lock import Lease
from mpres.control.cost_report import report
from mpres.control.codex_index import WireIndex
from mpres.control.wire_checkpoint import build,prune,evidence,read_seed
from mpres.control.repairs import Repairs
from test_relational_control import compact_root
from test_deck_workflow import native_double
from test_confirmed_repairs import completed,confirm
from test_v092_storage import finished


def prepare_gc(root):
    s,h,r=completed(root,decks=1)
    source=s.task/'sources';source.mkdir(exist_ok=True);(source/'future-course.md').write_text('User reference must survive')
    backup=s.task/'.mpres/maintenance-backups/old';backup.mkdir(parents=True)
    (backup/'task.sqlite3').write_bytes(b'previous backup '*10000)
    return s,h,r


def test_collect_preserves_current_usage_and_next_repair(compact_root,native_double):
    s,h,r=prepare_gc(compact_root);before=current_state(s.task)
    usage=s.store.rows('SELECT * FROM usage');cost_before=report(s.task)
    p=plan(s.task);assert p['safe_to_apply'],p['blocked_reasons']
    assert p['managed_file_bytes_to_remove']>100000
    assert any(x['kind']=='obsolete_artifact' for x in p['candidates'])
    receipt=apply(s.task,p['plan_id'],by='user')
    assert receipt['net_reclaimed_bytes']>0 and receipt['usage_unchanged']
    assert receipt['archives_created']==0
    assert current_state(s.task)==before
    assert (s.task/'sources/future-course.md').is_file()
    assert not (s.task/'.mpres/maintenance-backups/old').exists()
    assert s.store.rows('SELECT * FROM usage')==usage
    assert report(s.task)['counters']==cost_before['counters']
    assert report(s.task)['calls_observed']==cost_before['calls_observed']
    assert Delivery(s.task).ensure()['state']=='ready'
    rid=s.store.rows("SELECT request_id FROM host_requests WHERE operation='run' LIMIT 1")[0]['request_id']
    assert r.replay(rid)['body_pruned'] and r.replay(rid)['model_calls']==0
    case=Repairs(s.task).open('改善全稿表达。',['p01'],'user',focus='student-expression')
    r.run(cycles=80,interval=0);confirm(Repairs(s.task),case['case_id'])
    r.run(cycles=100,interval=0)
    assert Repairs(s.task).case(case['case_id'])['state']=='completed'
    assert Delivery(s.task).ensure()['state']=='ready'


@pytest.mark.parametrize('where',['after_rename','after_files_committed','after_logs_committed'])
def test_interruption_has_finite_recovery_and_blocks_production(compact_root,native_double,where):
    s,h,r=prepare_gc(compact_root);p=plan(s.task);before=current_state(s.task)
    def fault(stage,index):
        if stage==where:raise RuntimeError('power failure fixture')
    with pytest.raises(RuntimeError):apply(s.task,p['plan_id'],by='user',fault=fault)
    pending=status(s.task)['checkpoints'][-1]
    with pytest.raises(MPresError,match='recovery required'):open_task(s.task)
    out=resume(s.task,pending['id'],by='user')
    assert out['state']=='completed' and current_state(s.task)==before
    assert resume(s.task,pending['id'],by='user')['id']==out['id']
    assert not list((s.task/'.mpres/checkpoint-staging').iterdir())


def test_stale_plan_symlink_and_live_lock_refused(compact_root,native_double):
    s,h,r=prepare_gc(compact_root);p=plan(s.task)
    (s.task/'sources/another.md').write_text('new user material')
    with pytest.raises(MPresError,match='changed'):apply(s.task,p['plan_id'],by='user')
    p=plan(s.task)
    with Lease(s.task):
        with pytest.raises(MPresError,match='in use'):apply(s.task,p['plan_id'],by='user')
    target=s.task/p['candidates'][0]['path'];(target/'escape').symlink_to(s.task/'sources')
    with pytest.raises(MPresError,match='Symlink'):plan(s.task)


def test_unresolved_attempt_and_open_repair_protected(compact_root,native_double):
    s,h,r=prepare_gc(compact_root)
    case=Repairs(s.task).open('修改术语',['p01'],'user')
    p=plan(s.task);assert not p['safe_to_apply']
    assert any('repair case' in x for x in p['blocked_reasons'])


def test_missing_pdf_is_not_fabricated_or_silently_accepted(compact_root,native_double):
    s,h,r=prepare_gc(compact_root);mds=current_state(s.task)['current_releases']
    pdf=s.task/mds[0]['pdf'];pdf.unlink()
    assert not plan(s.task)['safe_to_apply']
    p=plan(s.task,allow_missing_pdf=True)
    assert p['safe_to_apply']
    done=apply(s.task,p['plan_id'],by='archive-test',allow_missing_pdf=True)
    assert not done['delivery_ready_claimed'] and not pdf.exists()
    assert open_task(s.task)['warnings'][0]['code']=='current_pdf_missing'


def test_auto_policy_only_at_confirmed_safe_boundary(compact_root,native_double):
    s,h,r=prepare_gc(compact_root)
    assert maybe_run(s.task)['state']=='manual_only'
    policy(s.task,True,by='user')
    result=maybe_run(s.task);assert result['state']=='completed'
    assert maybe_run(s.task)['state']=='current_baseline_already_collected'
    policy(s.task,False,by='user');assert maybe_run(s.task)['state']=='manual_only'


def test_wire_seed_rebuild_move_and_next_turn_without_old_history(compact_root,tmp_path):
    s,q=finished(compact_root);journal=s.task/'.mpres/codex-bridge.sqlite3'
    before=build(journal);out=prune(journal,'unit-checkpoint')
    assert out['wire_rows_after']<out['wire_rows_before']
    assert build(journal)==before
    index=s.task/'.mpres/codex-index.sqlite3';index.unlink()
    rebuilt=WireIndex(journal);assert rebuilt.sync()['rows_read']==0
    with closing(rebuilt.connect()) as c:
        from mpres.control.wire_checkpoint import projection
        assert projection(c,before['highwater'])==before
    target=tmp_path/'moved';shutil.copytree(s.task,target)
    moved=WireIndex(target/'.mpres/codex-bridge.sqlite3');assert moved.sync()['cursor']==before['highwater']
    from test_codex_incremental import start,finish
    start(target/'.mpres/codex-bridge.sqlite3','new-request','new-thread',99999,'new-turn')
    finish(target/'.mpres/codex-bridge.sqlite3','new-thread','new-turn','new genuine fixture response',10)
    assert moved.sync()['rows_read']==6
    assert moved.turns(request_id='new-request')[0]['final_text']=='new genuine fixture response'
    assert evidence(journal,3)['state']=='body_pruned'
    with sqlite3.connect(journal) as c:c.execute("UPDATE wire_checkpoint SET sha256='corrupted'")
    with pytest.raises(MPresError,match='checksum'):WireIndex(journal)
