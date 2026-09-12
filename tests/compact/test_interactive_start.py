"""Actual shell + PTY integration, with an explicitly fake Codex executable."""
from __future__ import annotations

import json
import os
from pathlib import Path
import select
import shutil
import signal
import subprocess
import sys
import time

import pytest

from mpres.startup import build_command, preflight, task_runtime
from mpres.util import MPresError, read_yaml, write_yaml_atomic
from test_relational_control import prepare

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def launch_root(tmp_path):
    root = tmp_path/'a project 空格'
    root.mkdir()
    for name in ('AGENTS.md','pyproject.toml','package.json','start.sh','start-safe.sh'):
        shutil.copy2(ROOT/name,root/name)
    shutil.copytree(ROOT/'src',root/'src',ignore=shutil.ignore_patterns('__pycache__'))
    shutil.copytree(ROOT/'templates/compact',root/'templates/compact')
    codex=tmp_path/'fake codex'
    codex.write_text('#!'+sys.executable+'\n'+'''import os,sys,json,signal,time
from pathlib import Path
if '--help' in sys.argv:
    print(os.environ.get('FAKE_HELP','Codex fixture: --cd --model --config --no-alt-screen'))
    raise SystemExit(int(os.environ.get('FAKE_HELP_EXIT','0')))
Path(os.environ['CAPTURE']).write_text(json.dumps({'argv':sys.argv[1:],'cwd':os.getcwd(),
    'tty':[os.isatty(0),os.isatty(1)],'pid':os.getpid(),'task':os.environ.get('MPRES_TASK_SLUG')}))
if os.environ.get('WAIT_SIGNAL'):
    signal.signal(signal.SIGINT,lambda *_:sys.exit(130))
print('CODEX_FIXTURE_STARTED',flush=True)
if os.environ.get('WAIT_SIGNAL'):
    while True:time.sleep(.05)
raise SystemExit(int(os.environ.get('FAKE_EXIT','0')))
''')
    codex.chmod(0o755)
    env={**os.environ,'CODEX_BIN':str(codex),'PYTHON_BIN':sys.executable,'CAPTURE':str(tmp_path/'capture.json')}
    return root,env


def invoke(root,env,*args):
    return subprocess.run(['bash',str(root/'start.sh'),*args],cwd=root.parent,
                          env=env,text=True,capture_output=True,timeout=20)


def pty_run(root,env,args=(),interrupt=False):
    import pty
    master,slave=pty.openpty()
    p=None;output=b''
    try:
        p=subprocess.Popen(['bash',str(root/'start.sh'),*args],cwd=root.parent,env=env,
                           stdin=slave,stdout=slave,stderr=slave)
        os.close(slave);slave=-1
        deadline=time.monotonic()+20
        while time.monotonic()<deadline:
            if select.select([master],[],[],.1)[0]:
                try:chunk=os.read(master,65536)
                except OSError:break
                if not chunk:break
                output+=chunk
                if interrupt and b'CODEX_FIXTURE_STARTED' in output:
                    # exec must ensure the directly launched PID is the host.
                    captured=json.loads(Path(env['CAPTURE']).read_text())
                    assert captured['pid']==p.pid
                    p.send_signal(signal.SIGINT);interrupt=False
            if p.poll() is not None:break
        return p.wait(timeout=3),output.decode(errors='replace')
    finally:
        if p is not None and p.poll() is None:p.kill();p.wait()
        if slave>=0:os.close(slave)
        os.close(master)


def test_no_arguments_really_launch_interactive_codex(launch_root):
    root,env=launch_root
    code,text=pty_run(root,env)
    assert code==0,text
    captured=json.loads(Path(env['CAPTURE']).read_text())
    assert captured['tty']==[True,True]
    assert captured['cwd']==str(root)
    assert captured['argv']==['--cd',str(root)]
    assert captured['task'] is None
    assert 'CODEX_FIXTURE_STARTED' in text


def test_interactive_exit_code_and_signals_are_preserved(launch_root):
    root,env=launch_root
    assert pty_run(root,{**env,'FAKE_EXIT':'17'})[0]==17
    assert pty_run(root,{**env,'WAIT_SIGNAL':'yes'},interrupt=True)[0]==130


def test_selected_confirmed_task_uses_user_planner_override(launch_root):
    root,env=launch_root
    service=prepare(root)
    # User-defined role override BEFORE confirmation, not mutation of a running task.
    from mpres.control.service import Service
    other=Service.create(root,'custom','Custom task')
    settings=read_yaml(service.task/'task.yaml');write_yaml_atomic(other.task/'task.yaml',settings)
    profile=read_yaml(other.task/'TASK-RUNTIME-PROFILE.yaml')
    profile['role_overrides']['main-planner']={'model':'user-model-terra','reasoning_effort':'high'}
    write_yaml_atomic(other.task/'TASK-RUNTIME-PROFILE.yaml',profile)
    other.present();other.confirm('user')
    before=(other.task/'.mpres/task.sqlite3').read_bytes()
    code,text=pty_run(root,env,['--task','custom','--','--no-alt-screen'])
    assert code==0,text
    args=json.loads(Path(env['CAPTURE']).read_text())['argv']
    assert args[args.index('--model')+1]=='user-model-terra'
    assert 'model_reasoning_effort="high"' in args
    assert 'tasks/custom' in args[-1]
    assert (other.task/'.mpres/task.sqlite3').read_bytes()==before


def test_changed_confirmed_runtime_cannot_launch(launch_root):
    root,env=launch_root
    service=prepare(root)
    profile=read_yaml(service.task/'TASK-RUNTIME-PROFILE.yaml');profile['defaults']['planner']['reasoning_effort']='low'
    write_yaml_atomic(service.task/'TASK-RUNTIME-PROFILE.yaml',profile)
    result=invoke(root,env,'--check','--task','sample')
    assert result.returncode==2 and 'Confirmed task configuration changed' in result.stderr
    assert not Path(env['CAPTURE']).exists()


def test_draft_task_can_plan_without_fake_confirmation(launch_root):
    root,env=launch_root
    from mpres.control.service import Service
    service=Service.create(root,'draft','Draft')
    before=(service.task/'.mpres/task.sqlite3').read_bytes()
    report=task_runtime(root,'draft')
    assert not report['confirmed'] and report['reasoning_effort']=='high'
    assert (service.task/'.mpres/task.sqlite3').read_bytes()==before


@pytest.mark.parametrize('args',[['--cli','workflow','--help'],['workflow','--help']])
def test_mechanical_path_needs_no_codex_and_no_terminal(launch_root,args):
    root,env=launch_root;env['CODEX_BIN']='/no/such/codex'
    result=invoke(root,env,*args)
    assert result.returncode==0 and 'retry-publish' in result.stdout
    assert not Path(env['CAPTURE']).exists()


def test_check_is_read_only_and_never_starts_host(launch_root):
    root,env=launch_root
    result=invoke(root,env,'--check')
    assert result.returncode==0,result.stderr
    report=json.loads(result.stdout)
    assert report['success'] and not report['native_render_verified']
    assert any('Marp' in text for text in report['warnings'])
    assert not Path(env['CAPTURE']).exists() and not (root/'tasks').exists()


def test_missing_codex_is_actionable(launch_root):
    root,env=launch_root;env['CODEX_BIN']='/no/such/codex'
    result=invoke(root,env,'--check')
    assert result.returncode==2
    assert 'CODEX_BIN' in json.loads(result.stdout)['errors'][0]


@pytest.mark.parametrize('changes',[{'FAKE_HELP':'old fixture without required flags'}, {'FAKE_HELP_EXIT':'3'}])
def test_incompatible_codex_help_is_not_ignored(launch_root,changes):
    root,env=launch_root
    result=invoke(root,{**env,**changes},'--check')
    assert result.returncode==2 and json.loads(result.stdout)['errors']
    assert not Path(env['CAPTURE']).exists()


def test_non_terminal_is_not_changed_to_exec_mode(launch_root):
    root,env=launch_root
    result=invoke(root,env)
    assert result.returncode==2 and 'requires a terminal' in result.stderr
    assert not Path(env['CAPTURE']).exists()


@pytest.mark.parametrize('tail', [['--model','other'],['-mother'],['--config=x'],['--profile','other'],['--cd=/tmp'],['-C/tmp']])
def test_task_runtime_or_root_cannot_be_overridden(tmp_path,tail):
    with pytest.raises(MPresError):
        build_command(tmp_path,{'codex':'codex','runtime':{'model':'chosen','reasoning_effort':'high','task':'t'}},tail)


def test_unsafe_or_missing_task_rejected(launch_root):
    root,env=launch_root
    for slug in ('../outside','missing'):
        result=invoke(root,env,'--check','--task',slug)
        assert result.returncode==2 and not Path(env['CAPTURE']).exists()


def test_safe_wrapper_is_same_entry(launch_root):
    root,env=launch_root
    result=subprocess.run(['bash',str(root/'start-safe.sh'),'--cli','--help'],env=env,cwd=root.parent,capture_output=True,text=True,timeout=20)
    assert result.returncode==0 and 'workflow' in result.stdout
    assert not Path(env['CAPTURE']).exists()


def test_uninstalled_yaml_reports_install_action_not_traceback(launch_root):
    env = {**os.environ, 'PYTHONPATH': str(ROOT/'src')}
    result = subprocess.run([sys.executable, '-S', '-m', 'mpres.startup', '--root', str(launch_root), '--check'],
                            text=True, capture_output=True, env=env)
    assert result.returncode == 2
    assert 'scripts/bootstrap.py' in result.stderr
    assert 'Traceback' not in result.stderr
