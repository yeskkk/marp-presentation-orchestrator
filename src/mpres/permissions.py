"""Explicit local-launch permission choices, not task or production consent.

Flags are checked against the installed CLI help. The request is displayed before
launch; managed policy / OS enforcement is not claimed to have been observed.
"""
from __future__ import annotations
from mpres.util import MPresError

MODES=('read-only','workspace','workspace-network','full')
APPROVALS=('on-request','never')

def selection(mode: str, approval: str='on-request', *, allow_full: bool=False) -> dict:
    if mode not in MODES or approval not in APPROVALS:
        raise MPresError('Unsupported permission or approval selection')
    if mode=='full' and not allow_full:
        raise MPresError('Full access requires explicit --allow-full-access or the FULL confirmation')
    sandbox={'read-only':'read-only','workspace':'workspace-write','workspace-network':'workspace-write','full':'danger-full-access'}[mode]
    flags=['--sandbox',sandbox,'--ask-for-approval',approval]
    network='no additional shell-network grant' if mode=='read-only' else 'unrestricted by this sandbox' if mode=='full' else 'enabled' if mode=='workspace-network' else 'disabled'
    if sandbox=='workspace-write':
        # Prevent the user's saved workspace roots from silently widening this
        # selection. Standard temporary roots remain Codex's documented defaults.
        flags+=['--config','sandbox_workspace_write.network_access='+str(mode=='workspace-network').lower(),
                '--config','sandbox_workspace_write.writable_roots=[]']
    return {'mode':mode,'sandbox':sandbox,'approval':approval,'shell_network_requested':network,'argv':flags,
            'filesystem_requested':'workspace and standard temporary roots; no additional saved roots' if sandbox=='workspace-write' else sandbox,
            'scope':'new interactive main session only; existing worker and OS policies unchanged',
            'effective_host_policy_verified':False,'production_authorized':False}

def choose(approval='on-request', read=None) -> dict:
    read=read or input
    print('选择本次主会话权限（不是生产授权；空输入不会默认放行）')
    print('[1] 只读  [2] 工作区写入/不额外开放 shell 网络  [3] 工作区写入/开放 shell 网络  [4] 完整访问  [q] 退出')
    while True:
        value=read('PERMISSION_SELECT> ').strip()
        if value.lower()=='q':raise EOFError('Permission selection cancelled')
        if value in {'1','2','3','4'}:
            mode=MODES[int(value)-1]
            if mode=='full' and read('PERMISSION_CONFIRM> 输入 FULL 确认完整访问，其他输入取消：').strip()!='FULL':
                raise EOFError('Full access not confirmed')
            return selection(mode,approval,allow_full=mode=='full')
        print('请输入列出的编号或 q；空输入不表示同意。')

def validate_flags(value: dict, advertised: list[str]) -> None:
    required={'--sandbox','--ask-for-approval'}
    if '--config' in value['argv']:required.add('--config')
    missing=required-set(advertised)
    if missing:raise MPresError('Installed Codex does not advertise required permission flags: '+', '.join(sorted(missing))+'; no automatic fallback')

def validate_tail(tail: list[str]) -> None:
    forbidden={'--sandbox','--ask-for-approval','--dangerously-bypass-approvals-and-sandbox','--yolo','--full-auto','--permission-profile','--profile','--config','--add-dir'}
    for arg in tail:
        if arg.split('=',1)[0] in forbidden or (arg.startswith(('-s','-a','-c','-p','-P')) and not arg.startswith('--')):
            raise MPresError('Permission overrides after -- are forbidden; use the launcher permission selectors')
