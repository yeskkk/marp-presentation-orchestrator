"""Actual terminal question, not just an instruction in a model prompt."""
from pathlib import Path
import json
import pytest
from mpres.startup import task_runtime, choose_intent
from mpres.util import MPresError
from test_interactive_start import launch_root, pty_run, invoke
from test_relational_control import prepare


def test_every_interactive_task_launch_asks_again_without_rewriting_database(launch_root):
    root,env=launch_root;s=prepare(root);before=(s.task/'.mpres/task.sqlite3').read_bytes()
    for _ in range(2):
        rc,text=pty_run(root,env,['--task','sample'])
        assert rc==0,text
        assert text.count('本次启动是否修改')==1
        capture=json.loads(Path(env['CAPTURE']).read_text())
        assert capture['intent']=='keep'
        assert 'NOT approval of a new delivery batch' in capture['argv'][-1]
        assert 'Do not ask that same startup question again' in capture['argv'][-1]
    assert (s.task/'.mpres/task.sqlite3').read_bytes()==before


def test_edit_mode_opens_changed_task_with_confirmed_not_disk_runtime(launch_root):
    root,env=launch_root;s=prepare(root)
    expected=task_runtime(root,'sample');before=(s.task/'.mpres/task.sqlite3').read_bytes()
    (s.task/'TASK.md').write_text('New task draft that is not yet approved.')
    (s.task/'task.yaml').write_text('invalid: [')
    (s.task/'TASK-RUNTIME-PROFILE.yaml').write_text('invalid: [')
    rc,text=pty_run(root,env,['--task','sample'],answers=['1'])
    assert rc==0,text
    capture=json.loads(Path(env['CAPTURE']).read_text());args=capture['argv']
    assert capture['intent']=='edit'
    assert args[args.index('--model')+1]==expected['model']
    assert 'do not dispatch production' in args[-1]
    assert (s.task/'.mpres/task.sqlite3').read_bytes()==before
    assert (s.task/'TASK.md').read_text().startswith('New task draft')


def test_keep_changed_task_fails_without_automatic_acceptance(launch_root):
    root,env=launch_root;s=prepare(root);(s.task/'TASK.md').write_text('Unconfirmed change')
    rc,text=pty_run(root,env,['--task','sample'],answers=['2'])
    assert rc==2 and 'Confirmed task configuration changed' in text
    assert not Path(env['CAPTURE']).exists()


@pytest.mark.parametrize('answer',['3','EOF'])
def test_cancel_or_eof_does_not_launch(launch_root,answer):
    root,env=launch_root;prepare(root)
    rc,text=pty_run(root,env,['--task','sample'],answers=[answer])
    assert rc==0,text
    assert not Path(env['CAPTURE']).exists()


def test_empty_answer_is_not_consent(launch_root):
    root,env=launch_root;prepare(root)
    rc,text=pty_run(root,env,['--task','sample'],answers=['','3'])
    assert rc==0 and '必须明确选择' in text
    assert not Path(env['CAPTURE']).exists()


def test_without_task_selects_before_asking_about_the_task(launch_root):
    root,env=launch_root;prepare(root)
    rc,text=pty_run(root,env,answers=['1','2'])
    assert rc==0,text
    assert text.index('TASK_SELECT>') < text.index('TASK_INTENT>')
    assert json.loads(Path(env['CAPTURE']).read_text())['task']=='sample'


def test_task_selection_cancellation_does_not_launch(launch_root):
    root,env=launch_root;prepare(root)
    rc,text=pty_run(root,env,answers=['q'])
    assert rc==0 and not Path(env['CAPTURE']).exists()


def test_mechanical_check_never_asks_question(launch_root):
    root,env=launch_root;prepare(root)
    p=invoke(root,env,'--check','--task','sample')
    assert p.returncode==0 and 'TASK_INTENT>' not in p.stdout
    assert not Path(env['CAPTURE']).exists()


def test_new_unconfirmed_task_does_not_invent_a_runtime_for_broken_yaml(launch_root):
    root,env=launch_root
    from mpres.control.service import Service
    s=Service.create(root,'draft','Draft');(s.task/'TASK-RUNTIME-PROFILE.yaml').write_text('invalid: [')
    with pytest.raises(Exception): task_runtime(root,'draft',editing=True)


def test_task_context_module_unchanged_by_startup_intent():
    # State of read_full/reuse/apply_delta is tested by the retained 15 tests.
    # Startup choices never declare that TASK has been read or grant new scope.
    from mpres.startup import build_command
    cmd=build_command(Path('/project'),{'codex':'codex','startup_intent':'edit',
        'runtime':{'model':'fixed','reasoning_effort':'low','task':'x'}},[])
    assert 'once in this session' in cmd[-1] and 'If already read' in cmd[-1]
