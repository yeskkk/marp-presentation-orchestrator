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


def snapshot(task: Path, source: Path) -> tuple[str, str]:
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
        copy_tree(source, stage, read_only=True)
        os.replace(stage, target)
    except Exception:
        remove_tree(stage)
        raise
    return artifact_id, relative
