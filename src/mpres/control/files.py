from __future__ import annotations

import os
import shutil
import stat
import uuid
from pathlib import Path

from mpres.util import MPresError


def inside(root: Path, relative: str) -> Path:
    value = Path(relative)
    if value.is_absolute() or '..' in value.parts:
        raise MPresError(f'Unsafe relative path: {relative}')
    resolved = (root / value).resolve()
    if not resolved.is_relative_to(root.resolve()):
        raise MPresError(f'Path escaped its allowed root: {relative}')
    # Resolve containment is not enough: even inward-pointing links are forbidden.
    current = root
    for part in value.parts:
        current = current / part
        if current.is_symlink():
            raise MPresError(f'Symlink is forbidden: {relative}')
    return resolved


def writable(root: Path) -> None:
    for path in [root, *root.rglob('*')]:
        path.chmod(path.stat().st_mode | stat.S_IWUSR | (stat.S_IXUSR if path.is_dir() else 0))


def remove_tree(root: Path) -> None:
    if root.exists():
        writable(root)
        shutil.rmtree(root)


def copy_tree(source: Path, target: Path, *, read_only: bool) -> None:
    if source.is_symlink() or not source.is_dir():
        raise MPresError('Source must be a real directory, not a symlink')
    for path in source.rglob('*'):
        if path.is_symlink() or not (path.is_file() or path.is_dir()):
            raise MPresError(f'Only regular source files/directories may be copied: {path}')
    shutil.copytree(source, target)
    writable(target)
    if read_only:
        for path in [*target.rglob('*'), target]:
            path.chmod(path.stat().st_mode & ~(stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH))


def snapshot(task: Path, source: Path, *, fixed_theme: bool = False) -> tuple[str, str]:
    """Prepare a revision outside a DB transaction; caller removes it on rollback.

    UUID revision identities replace hashes. Directory permissions are an accident
    guard, not a security sandbox against the operating-system owner.
    """
    artifact_id = 'r-' + uuid.uuid4().hex
    relative = f'.mpres/artifacts/{artifact_id}'
    parent = task / '.mpres' / 'artifacts'
    parent.mkdir(parents=True, exist_ok=True)
    stage = parent / (artifact_id + '.pending')
    target = task / relative
    try:
        copy_tree(source, stage, read_only=not fixed_theme)
        if fixed_theme:
            from mpres.source_policy import install_theme, require_source
            require_source(stage)
            install_theme(stage)
            for path in [*stage.rglob('*'),stage]:
                path.chmod(path.stat().st_mode & ~(stat.S_IWUSR|stat.S_IWGRP|stat.S_IWOTH))
        os.replace(stage, target)
    except Exception:
        remove_tree(stage)
        raise
    return artifact_id, relative


def prepare_edit_source(task: Path, source: Path, target: Path, *, entrypoint: str = 'presentation.md') -> dict:
    """Prepare a NEW author work copy and regenerate declared figures there.

    The original immutable artifact is never modified. Existing nonempty author
    output is deliberately not refreshed (including unsubmitted user edits).
    A complete staged directory is renamed into place; interrupted staging is
    disposable, not an excuse to rewrite the original source or trust old SVGs.
    """
    from .input_packet import safe_file
    from mpres.geometry import build, mathematical_model, inspect_figures
    from mpres.source_policy import install_theme, inspect_markdown
    import json
    import errno
    if not isinstance(entrypoint,str) or Path(entrypoint).name!=entrypoint or not entrypoint.endswith('.md'):
        raise MPresError('Invalid source Markdown entrypoint')
    if not target.resolve().is_relative_to((task/'.mpres/work').resolve()):
        raise MPresError('Automatic figure preparation is restricted to a task author work directory')
    target = inside(task,target.relative_to(task).as_posix())
    source = inside(task,source.relative_to(task).as_posix())
    if target == source or target.is_relative_to(source):
        raise MPresError('Author work copy must be distinct from source evidence')
    if target.exists() and any(target.iterdir()):
        return {'state':'existing_output_preserved','regenerated':[]}
    files=[]
    for entry in source.rglob('*'):
        if entry.is_symlink(): raise MPresError('Cannot prepare an author copy from symlinked evidence')
        relative=entry.relative_to(source)
        if entry.is_file() and (relative.as_posix() in {entrypoint,'exercises.json'} or relative.parts[0]=='assets'):
            safe_file(task,entry);files.append((entry,Path('presentation.md') if relative.as_posix()==entrypoint else relative))
    # Validate all mathematical inputs first. Unknown versions require explicit implementation,
    # never a downgrade, removal of the .plot.json, or execution of submitted Python.
    for entry,relative in files:
        if entry.name.endswith('.plot.json'):
            if entry.stat().st_size>32768: raise MPresError('Mathematical figure input is too large')
            mathematical_model(json.loads(entry.read_text(encoding='utf-8')))
    stage=target.parent/(target.name+'.prepare-'+uuid.uuid4().hex)
    stage.mkdir(parents=True)
    regenerated=[]
    try:
        for entry,relative in files:
            dst=stage/relative;dst.parent.mkdir(parents=True,exist_ok=True);dst.write_bytes(entry.read_bytes())
        for spec in sorted(stage.rglob('*.plot.json')):
            result=build(spec)
            regenerated.append({'input':spec.relative_to(stage).as_posix(),
                                'version':json.loads(spec.read_text())['version'],'model':result['model']})
        checked=inspect_figures(stage)
        if not checked['success']: raise MPresError('Prepared mathematical figures failed validation: '+str(checked['errors']))
        install_theme(stage)
        remaining=inspect_markdown((stage/'presentation.md').read_text(encoding='utf-8'))['errors']
        try:
            # POSIX replaces an empty directory atomically but refuses a populated one.
            # On Windows an existing empty directory may need to be removed first.
            if os.name=='nt' and target.exists(): target.rmdir()
            os.replace(stage,target)
        except OSError as exc:
            if exc.errno not in {errno.EEXIST,errno.ENOTEMPTY,errno.EACCES}: raise
            if target.is_dir() and any(target.iterdir()):
                return {'state':'concurrent_output_preserved','regenerated':[]}
            raise
        return {'state':'prepared','regenerated':regenerated,'remaining_source_errors':remaining,
                'instruction':'Correct remaining legacy Markdown directives in this work copy; this report is internal, not student-visible content. Preparation is not a gate pass.',
                'evidence_modified':False,'validation':'Recomputed from closed mathematical inputs in current renderer; normal submission gates still required.'}
    finally:
        remove_tree(stage)
