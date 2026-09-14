import json
from pathlib import Path
import pytest
from mpres.permissions import selection,choose,validate_tail,validate_flags
from mpres.util import MPresError
from test_interactive_start import launch_root,pty_run,invoke

@pytest.mark.parametrize('mode,network',[('read-only',None),('workspace','false'),('workspace-network','true'),('full',None)])
def test_explicit_modes_are_argv_not_prompt_permissions(mode,network):
    p=selection(mode,allow_full=mode=='full')
    assert '--sandbox' in p['argv'] and '--ask-for-approval' in p['argv']
    assert not p['production_authorized'] and not p['effective_host_policy_verified']
    assert '--dangerously-bypass-approvals-and-sandbox' not in p['argv']
    if network:assert 'sandbox_workspace_write.network_access='+network in p['argv']

@pytest.mark.parametrize('tail',[['--yolo'],['--full-auto'],['--config=approval_policy="never"'],['-sworkspace-write'],['--permission-profile','foo'],['--add-dir=/outside']])
def test_tail_cannot_override_explicit_choice(tail):
    with pytest.raises(MPresError):validate_tail(tail)

def test_full_access_needs_extra_ack_and_unknown_cli_never_falls_back():
    with pytest.raises(MPresError):selection('full')
    with pytest.raises(MPresError):validate_flags(selection('workspace'),['--cd'])
    answers=iter(['4','not-FULL'])
    with pytest.raises(EOFError):choose(read=lambda _:next(answers))

@pytest.mark.parametrize('answers',[['q'],['','q'],['4','cancel']])
def test_permission_cancel_never_starts_model(launch_root,answers):
    root,env=launch_root;rc,text=pty_run(root,env,permission_answers=answers)
    assert rc==0,text
    assert not Path(env['CAPTURE']).exists()

def test_cli_parameters_preview_without_terminal_or_model(launch_root):
    root,env=launch_root
    r=invoke(root,env,'--intent','keep','--permissions','workspace-network','--print-command')
    assert r.returncode==0,r.stderr
    d=json.loads(r.stdout)
    assert d['model_started'] is False and 'sandbox_workspace_write.network_access=true' in d['command']
    assert not Path(env['CAPTURE']).exists()

def test_noninteractive_permission_choice_does_not_create_headless_model(launch_root):
    root,env=launch_root;r=invoke(root,env,'--intent','keep','--permissions','workspace')
    assert r.returncode==2 and 'requires a terminal' in r.stderr
    assert not Path(env['CAPTURE']).exists()

def test_preview_does_not_infer_a_missing_choice(launch_root):
    root,env=launch_root;r=invoke(root,env,'--print-command','--permissions','workspace')
    assert r.returncode==2 and '--intent' in r.stderr

def test_explicit_interactive_choice_skips_permission_question(launch_root):
    root,env=launch_root;rc,text=pty_run(root,env,['--intent','keep','--permissions','read-only'])
    assert rc==0,text
    assert 'PERMISSION_SELECT>' not in text and 'TASK_INTENT>' not in text
    d=json.loads(Path(env['CAPTURE']).read_text())
    assert d['argv'][d['argv'].index('--sandbox')+1]=='read-only'

def test_no_silent_fallback_when_installed_cli_lacks_permission_flags(launch_root):
    root,env=launch_root;r=invoke(root,{**env,'FAKE_HELP':'--cd --model --config'},'--check','--permissions','workspace')
    assert r.returncode==2 and 'permission flags' in r.stderr
    assert not Path(env['CAPTURE']).exists()

@pytest.mark.parametrize('command',['storage','report','supervision','exercise','resource'])
def test_new_mechanical_commands_work_through_shell_without_codex(launch_root,command):
    root,env=launch_root
    for prefix in (['--cli'],[]):
        r=invoke(root,{**env,'CODEX_BIN':'/missing'},*prefix,command,'--help')
        assert r.returncode==0,r.stderr
    assert not Path(env['CAPTURE']).exists()
