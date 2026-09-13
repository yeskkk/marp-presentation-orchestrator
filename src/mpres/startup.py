"""Interactive Codex entry; never a scheduler, installer or authorization source.

All probes are local. The launcher never mutates a task, calls a model during
preflight, or asserts a provider capability from a configuration file.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys

try:
    from mpres.runtime_profile import normalize_runtime_profile, resolve_runtime
    from mpres.util import MPresError, read_yaml, safe_id
except ModuleNotFoundError as exc:
    # A clean/partial venv must report the install action, not fail importing
    # the preflight machinery before it can tell the user what is missing.
    if exc.name != 'yaml':
        raise
    print('Start failed: Missing Python runtime module yaml. Run python scripts/bootstrap.py.', file=sys.stderr)
    raise SystemExit(2) from None

# Compatibility with explicit v0.6.15 mechanical invocations. No arguments now
# means interactive work, never --help. Unknown tokens must not become CLI jobs.
CLI_COMMANDS = {'task','runner','artifact','workflow','repair','feedback','toolchain','legacy','source','session','job'}
CORE_MODULES = ('yaml','jsonschema','fitz','playwright','bs4','PIL','requests','pypdf','markdown_it')


def _executable(name: str) -> str | None:
    return shutil.which(name)


def task_runtime(root: Path, slug: str, *, editing: bool = False) -> dict:
    """Read the selected task's planner runtime without migrating or writing it."""
    safe_id(slug, label='task slug')
    task = root / 'tasks' / slug
    if task.is_symlink() or not task.is_dir():
        raise MPresError('Selected task is missing or a symlink; use task init first')
    task = task.resolve()
    if not task.is_relative_to((root/'tasks').resolve()):
        raise MPresError('Selected task escaped the project tasks directory')
    for name in ('TASK.md','task.yaml','TASK-RUNTIME-PROFILE.yaml'):
        if not (task/name).is_file() or (task/name).is_symlink():
            raise MPresError(f'Missing or unsafe task input: {name}')
    db = task/'.mpres/task.sqlite3'
    if not db.is_file():
        raise MPresError('Selected task is not a compact task; import legacy tasks before launching')
    if db.is_symlink():
        raise MPresError('Task database may not be a symlink')
    # sqlite mode=ro is intentional. A launcher must not upgrade or initialize it.
    conn = sqlite3.connect(db.resolve().as_uri()+'?mode=ro', uri=True, timeout=10)
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute('SELECT configs.* FROM configs JOIN task ON configs.id=task.config_id').fetchone()
        changed = []
        if row is not None:
            # The edit branch uses the CONFIRMED profile even if disk YAML is
            # malformed. A task-edit request never authorizes a runtime change.
            runtime = json.loads(row['runtime_json'])
            from mpres.control.service import settings_document
            from mpres.control.policy import resolve
            effective=resolve(conn,row,readonly=True)
            expected = {'TASK.md': effective['task_text'], 'task.yaml': json.loads(row['settings_json']),
                        'TASK-RUNTIME-PROFILE.yaml': runtime}
            for name, value in expected.items():
                try:
                    actual = ((task/name).read_text(encoding='utf-8') if name == 'TASK.md' else
                              settings_document(read_yaml(task/name)) if name == 'task.yaml' else
                              normalize_runtime_profile(read_yaml(task/name)))
                except Exception as exc:
                    if not editing:
                        raise MPresError(f'Confirmed task configuration changed or is invalid ({name}); restart and choose 修改任务要求') from exc
                    changed.append(name)
                    continue
                if actual != value:
                    changed.append(name)
            if changed and not editing:
                raise MPresError('Confirmed task configuration changed; restart and choose 修改任务要求, or restore the confirmed files')
        else:
            runtime = normalize_runtime_profile(read_yaml(task/'TASK-RUNTIME-PROFILE.yaml'))
    except sqlite3.Error as exc:
        raise MPresError(f'Cannot read task confirmation: {exc}') from exc
    finally:
        conn.close()
    return {**resolve_runtime(runtime,'main-planner'), 'confirmed':row is not None, 'task':slug, 'changed_inputs':changed, 'runtime_source':'confirmed_snapshot' if row is not None else 'unconfirmed_draft'}


def preflight(root: Path, *, slug: str | None = None) -> dict:
    errors: list[str] = []
    warnings: list[str] = []
    missing = [name for name in CORE_MODULES if importlib.util.find_spec(name) is None]
    if missing:
        errors.append('Missing Python runtime modules: '+', '.join(missing)+'. Run python scripts/bootstrap.py.')
    if sys.version_info < (3,11):
        errors.append('Python 3.11+ is required')
    codex = _executable(os.environ.get('CODEX_BIN','codex'))
    help_text = ''
    if not codex:
        errors.append('Codex executable not found; install/login to Codex separately or set CODEX_BIN to its executable path')
    else:
        try:
            result = subprocess.run([codex,'--help'], cwd=root, text=True,
                                    capture_output=True, timeout=15)
            help_text = result.stdout+'\n'+result.stderr
            if result.returncode:
                errors.append(f'Codex --help failed (exit {result.returncode}): {help_text[-1000:]}')
            required = ['--cd'] + (['--model','--config'] if slug else [])
            for flag in required:
                if flag not in help_text:
                    errors.append(f'Installed Codex does not advertise {flag}; update/verify its CLI before launching')
        except (OSError, subprocess.TimeoutExpired) as exc:
            errors.append(f'Codex probe failed: {exc}')
    runtime = task_runtime(root,slug) if slug else None
    node = _executable('node')
    marp = root/'node_modules/@marp-team/marp-cli/package.json'
    render_ready = bool(node and marp.is_file())
    if not node:
        warnings.append('Node.js missing: planning is available, rendering is not')
    if not marp.is_file():
        warnings.append('Pinned local Marp missing: run npm install before production')
    else:
        try:
            expected = json.loads((root/'package.json').read_text())['devDependencies']['@marp-team/marp-cli']
            actual = json.loads(marp.read_text())['version']
            if actual != expected:
                render_ready = False
                warnings.append(f'Marp version mismatch: expected {expected}, installed {actual}')
        except (KeyError,ValueError,OSError):
            render_ready = False
            warnings.append('Cannot verify installed Marp version; run toolchain doctor before production')
    figures = [name for name in ('numpy','sympy','matplotlib') if importlib.util.find_spec(name) is None]
    if figures:
        warnings.append('Optional drawing modules missing: '+', '.join(figures)+'; install .[figures] before plotting')
    return {'success':not errors,'root':str(root),'python':sys.executable,'codex':codex,
            'runtime':runtime,'codex_flags':[flag for flag in ('--cd','--model','--config') if flag in help_text], 'render_dependencies_present':render_ready,
            'native_render_verified':False,'errors':errors,'warnings':warnings}


def choose_task(root: Path, selected: str | None, read=None) -> str | None:
    """Local routing only; no memory, model call, database write or default consent."""
    if selected:
        safe_id(selected, label='task slug')
        return selected
    read = read or input
    folder = root/'tasks'
    tasks = sorted(p.name for p in folder.iterdir() if p.is_dir() and not p.is_symlink() and (p/'.mpres/task.sqlite3').is_file()) if folder.is_dir() else []
    if not tasks:
        return None
    print('选择本次任务（0：新建/进入会话后再选择；q：退出）')
    for index, slug in enumerate(tasks, 1):
        print(f'[{index}] {slug}')
    while True:
        value = read('TASK_SELECT> ').strip()
        if value.lower() == 'q':
            raise EOFError('User cancelled task selection')
        if value == '0':
            return None
        if value.isdigit() and 1 <= int(value) <= len(tasks):
            return tasks[int(value)-1]
        print('请输入一个列出的编号；空输入不表示同意继续。')


def choose_intent(slug: str | None, read=None) -> str:
    read = read or input
    subject = f'tasks/{slug}/TASK.md' if slug else '本次任务要求（尚未选择或创建 TASK.md）'
    print(f'本次启动是否修改 {subject}？')
    print('[1] 修改/先规划任务要求  [2] 不修改，进入会话  [3] 退出')
    while True:
        value = read('TASK_INTENT> ').strip()
        if value in {'1','2','3'}:
            return {'1':'edit', '2':'keep', '3':'exit'}[value]
        print('必须明确选择1、2或3；空输入不会自动续跑。')


def build_command(root: Path, report: dict, tail: list[str]) -> list[str]:
    # Forward terminal/preferences flags, but never allow task/model/workspace
    # selectors to override the confirmed task. No shell/eval is involved.
    for arg in tail:
        if arg == '--cd' or arg.startswith('--cd=') or arg.startswith('-C'):
            raise MPresError('Working directory is fixed by the launcher')
        if report['runtime'] and (arg in {'--model','--config','--profile'} or
                arg.startswith(('--model=','--config=','--profile=')) or
                (arg.startswith(('-m','-c','-p')) and not arg.startswith('--'))):
            raise MPresError('With --task, model/config/profile overrides are forbidden; edit the task runtime before confirmation')
    command = [report['codex'],'--cd',str(root)]
    rt = report['runtime']
    if rt:
        command += ['--model',rt['model'],'--config',
                    'model_reasoning_effort='+json.dumps(rt['reasoning_effort'])]
    command += tail
    # A task pointer only, not another workflow prompt. Durable instructions live
    # in AGENTS.md. Resume means continue database work, not guess a session ID.
    if rt:
        if any(not value.startswith('-') for value in tail):
            # Arbitrary positional strings might already be a prompt; require a
            # clear route rather than merge it into a second positional prompt.
            raise MPresError('With --task use only value-free Codex flags (e.g. --no-alt-screen); give instructions interactively')
        intent=report.get('startup_intent')
        if intent == 'edit':
            direction='The local user chose to amend TASK requirements. Do not ask that same startup question again and do not dispatch production. Disk drafts are not authorization; the selected model remains the confirmed runtime.'
        elif intent == 'keep':
            direction='The local user chose to keep TASK requirements. Do not ask that same startup question again; this is NOT approval of a new delivery batch, repair scope or permission.'
        else:
            direction='First establish whether the user wants to amend the task, plan, or resume; do not automatically start production.'
        command += [f"Selected task: tasks/{rt['task']}. {direction} Do not automatically start production. Once the task and current direction are established, read TASK.md in full once in this session before substantive role work. If already read, use that context and only subsequent authorized changes. Follow AGENTS.md and inspect actual state; never infer user confirmation."]
    return command


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    parser = argparse.ArgumentParser(description='Start interactive Codex work; --cli executes only mpres commands.')
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument('--task', help='Continue an existing compact task using its fixed planner runtime')
    parser.add_argument('--check', action='store_true', help='Local preflight only; no model session or task changes')
    parser.add_argument('codex_args', nargs=argparse.REMAINDER, help='Codex flags after -- (no task/runtime overrides)')
    # Mechanical operations must remain possible without Codex or a terminal.
    if '--cli' in args:
        pos = args.index('--cli')
        prefix = parser.parse_args(args[:pos])
        if prefix.task or prefix.check:
            parser.error('--cli cannot be combined with --task or --check')
        from mpres.cli import main as cli
        return cli(['--root',str(prefix.root.resolve()),*args[pos+1:]])
    # Backwards compatible form: start.sh workflow --help.
    prefix_count = 2 if args[:1] == ['--root'] else 0
    if len(args)>prefix_count and args[prefix_count] in CLI_COMMANDS:
        from mpres.cli import main as cli
        return cli(args)
    parsed = parser.parse_args(args)
    root = parsed.root.resolve()
    try:
        if not (root/'AGENTS.md').is_file() or not (root/'pyproject.toml').is_file():
            raise MPresError('Launch from an intact project source tree')
        tail = parsed.codex_args
        if tail[:1] == ['--']:tail=tail[1:]
        if parsed.check:
            report = preflight(root,slug=parsed.task)
            print(json.dumps(report,ensure_ascii=False,indent=2))
            return 0 if report['success'] else 2
        if not sys.stdin.isatty() or not sys.stdout.isatty():
            raise MPresError('Interactive launch requires a terminal. Use --check or --cli in scripts; no automatic noninteractive model call.')
        # Environment checks do not read/validate a possibly edited TASK first.
        report = preflight(root)
        if report['errors']:
            raise MPresError('\n'.join(report['errors']))
        slug = choose_task(root, parsed.task)
        intent = choose_intent(slug)
        if intent == 'exit':
            print('已退出；未启动模型，未修改任务。')
            return 0
        report['startup_intent'] = intent
        if slug:
            report['runtime'] = task_runtime(root, slug, editing=intent=='edit')
            for flag in ('--model','--config'):
                if flag not in report['codex_flags']:
                    raise MPresError(f'Installed Codex does not advertise {flag}; cannot enforce the selected task runtime')
            if report['runtime']['changed_inputs']:
                print('未确认的文件改动：'+', '.join(report['runtime']['changed_inputs'])+'；仍使用数据库已确认的模型与强度。',file=sys.stderr)
        command = build_command(root,report,tail)
        for message in report['warnings']:
            print('Preflight: '+message,file=sys.stderr)
        if report['runtime']:
            rt=report['runtime']
            print(f"Task {rt['task']}: {rt['model']} / {rt['reasoning_effort']}; no runtime fallback",file=sys.stderr)
        else:
            print('Planning session uses your Codex configuration. Before production choose a task and reopen with --task.',file=sys.stderr)
        env={**os.environ,'MPRES_ROOT':str(root)}
        env['MPRES_STARTUP_INTENT']=intent
        if slug:env['MPRES_TASK_SLUG']=slug
        else:env.pop('MPRES_TASK_SLUG',None)
        if os.name == 'posix':
            os.chdir(root)
            os.execvpe(command[0],command,env)  # inherit terminal and signals
        # Native Windows does not replace the console process; inherited handles
        # and the exact child exit code are preserved instead.
        return subprocess.call(command,cwd=root,env=env)
    except (EOFError,KeyboardInterrupt):
        print('启动已取消；未把中断解释为继续授权。',file=sys.stderr)
        return 0
    except (MPresError,OSError,sqlite3.Error) as exc:
        print(f'Start failed: {exc}',file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
