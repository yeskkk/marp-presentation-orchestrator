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


def task_runtime(root: Path, slug: str) -> dict:
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
    runtime = normalize_runtime_profile(read_yaml(task/'TASK-RUNTIME-PROFILE.yaml'))
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
        if row is not None:
            from mpres.control.service import settings_document
            if (json.loads(row['runtime_json']) != runtime or
                json.loads(row['settings_json']) != settings_document(read_yaml(task/'task.yaml')) or
                row['task_text'] != (task/'TASK.md').read_text(encoding='utf-8')):
                raise MPresError('Confirmed task configuration changed; restore it before launching')
    except sqlite3.Error as exc:
        raise MPresError(f'Cannot read task confirmation: {exc}') from exc
    finally:
        conn.close()
    return {**resolve_runtime(runtime,'main-planner'), 'confirmed':row is not None, 'task':slug}


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
            'runtime':runtime,'render_dependencies_present':render_ready,
            'native_render_verified':False,'errors':errors,'warnings':warnings}


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
        command += [f"Continue task tasks/{rt['task']}; read AGENTS.md and its confirmed database state. Do not infer user confirmation."]
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
        report = preflight(root,slug=parsed.task)
        tail = parsed.codex_args
        if tail[:1] == ['--']:tail=tail[1:]
        if parsed.check:
            print(json.dumps(report,ensure_ascii=False,indent=2))
            return 0 if report['success'] else 2
        if report['errors']:
            raise MPresError('\n'.join(report['errors']))
        if not sys.stdin.isatty() or not sys.stdout.isatty():
            raise MPresError('Interactive launch requires a terminal. Use --check or --cli in scripts; no automatic noninteractive model call.')
        command = build_command(root,report,tail)
        for message in report['warnings']:
            print('Preflight: '+message,file=sys.stderr)
        if report['runtime']:
            rt=report['runtime']
            print(f"Task {rt['task']}: {rt['model']} / {rt['reasoning_effort']}; no runtime fallback",file=sys.stderr)
        else:
            print('Planning session uses your Codex configuration. Before production choose a task and reopen with --task.',file=sys.stderr)
        env={**os.environ,'MPRES_ROOT':str(root)}
        if parsed.task:env['MPRES_TASK_SLUG']=parsed.task
        else:env.pop('MPRES_TASK_SLUG',None)
        if os.name == 'posix':
            os.chdir(root)
            os.execvpe(command[0],command,env)  # inherit terminal and signals
        # Native Windows does not replace the console process; inherited handles
        # and the exact child exit code are preserved instead.
        return subprocess.call(command,cwd=root,env=env)
    except (MPresError,OSError,sqlite3.Error) as exc:
        print(f'Start failed: {exc}',file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
