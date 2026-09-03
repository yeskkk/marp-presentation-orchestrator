from __future__ import annotations

import errno
import json
import os
import shutil
import stat
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping

import yaml

from mpres.util import DEFAULT_COPY_EXCLUDES, MPresError, require_no_symlinks


@dataclass
class ScaffoldReport:
    """Files created or deliberately preserved by one idempotent scaffold pass."""

    created: list[str] = field(default_factory=list)
    preserved: list[str] = field(default_factory=list)

    @property
    def changed(self) -> bool:
        return bool(self.created)

    def merge(self, other: "ScaffoldReport") -> "ScaffoldReport":
        self.created.extend(other.created)
        self.preserved.extend(other.preserved)
        return self

    def as_dict(self) -> dict[str, Any]:
        return {
            "created": list(self.created),
            "preserved": list(self.preserved),
            "changed": self.changed,
        }


def _display(path: Path) -> str:
    return path.as_posix()


def _write_complete_file_once(path: Path, payload: bytes) -> bool:
    """Publish a complete file without replacing an existing path.

    A fully written temporary file is hard-linked into place, which gives the
    destination create-if-absent semantics.  The fallback uses O_EXCL on
    platforms/filesystems that do not support hard links.  Neither path ever
    replaces an existing file.
    """

    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if not path.is_file():
            raise MPresError(f"Scaffold destination exists but is not a file: {path}")
        return False

    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temp = Path(temp_name)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(temp, path)
            return True
        except FileExistsError:
            return False
        except OSError as exc:
            if exc.errno not in {
                errno.EPERM,
                errno.EACCES,
                errno.ENOTSUP,
                errno.EOPNOTSUPP,
                errno.EXDEV,
            }:
                raise
            flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
            try:
                target_fd = os.open(path, flags, 0o666)
            except FileExistsError:
                return False
            try:
                with os.fdopen(target_fd, "wb") as handle:
                    handle.write(payload)
                    handle.flush()
                    os.fsync(handle.fileno())
            except Exception:
                try:
                    path.unlink()
                except OSError:
                    pass
                raise
            return True
    finally:
        try:
            temp.unlink()
        except FileNotFoundError:
            pass


def ensure_bytes(path: Path, payload: bytes) -> ScaffoldReport:
    report = ScaffoldReport()
    if _write_complete_file_once(path, payload):
        report.created.append(_display(path))
    else:
        report.preserved.append(_display(path))
    return report


def ensure_text(path: Path, text: str, *, newline: str = "\n") -> ScaffoldReport:
    if newline != "\n":
        text = text.replace("\n", newline)
    return ensure_bytes(path, text.encode("utf-8"))


def ensure_yaml(path: Path, value: Any) -> ScaffoldReport:
    text = yaml.safe_dump(value, allow_unicode=True, sort_keys=False, width=1000)
    return ensure_text(path, text)


def ensure_json(path: Path, value: Any) -> ScaffoldReport:
    text = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    return ensure_text(path, text)


def ensure_copy(source: Path, destination: Path) -> ScaffoldReport:
    if not source.is_file():
        raise MPresError(f"Scaffold source file does not exist: {source}")
    report = ensure_bytes(destination, source.read_bytes())
    if report.changed:
        try:
            shutil.copystat(source, destination)
        except OSError:
            pass
    return report


def ensure_tree(
    source: Path,
    destination: Path,
    *,
    exclude_names: Iterable[str] = DEFAULT_COPY_EXCLUDES,
    exclude_suffixes: Iterable[str] = (".pdf", ".log"),
) -> ScaffoldReport:
    """Copy only missing files from a source tree; never replace destination files."""

    source = source.resolve()
    if not source.is_dir():
        raise MPresError(f"Scaffold source directory does not exist: {source}")
    require_no_symlinks(source)
    if destination.exists() and not destination.is_dir():
        raise MPresError(f"Scaffold destination exists but is not a directory: {destination}")
    destination.mkdir(parents=True, exist_ok=True)

    excluded = set(exclude_names)
    suffixes = tuple(suffix.lower() for suffix in exclude_suffixes)
    report = ScaffoldReport()
    for item in sorted(source.rglob("*")):
        relative = item.relative_to(source)
        if any(part in excluded for part in relative.parts):
            continue
        target = destination / relative
        if item.is_dir():
            target.mkdir(parents=True, exist_ok=True)
            continue
        if not item.is_file():
            continue
        if item.suffix.lower() in suffixes or item.name.startswith(
            ("render-report-", "inspection-report-")
        ):
            continue
        report.merge(ensure_copy(item, target))
    return report


def make_files_read_only(paths: Iterable[Path]) -> None:
    """Best-effort guardrail; API lifecycle checks remain authoritative."""

    for path in paths:
        if not path.is_file():
            continue
        try:
            mode = path.stat().st_mode
            path.chmod(mode & ~stat.S_IWUSR & ~stat.S_IWGRP & ~stat.S_IWOTH)
        except OSError:
            pass


def make_files_writable(paths: Iterable[Path]) -> None:
    for path in paths:
        if not path.is_file():
            continue
        try:
            path.chmod(path.stat().st_mode | stat.S_IWUSR)
        except OSError:
            pass


def ensure_mapping_identity(
    value: Mapping[str, Any],
    expected: Mapping[str, Any],
    *,
    path: Path,
) -> None:
    mismatches: list[str] = []
    for key, expected_value in expected.items():
        if value.get(key) != expected_value:
            mismatches.append(
                f"{key}: expected {expected_value!r}, found {value.get(key)!r}"
            )
    if mismatches:
        raise MPresError(
            f"Existing scaffold identity conflicts with the requested assignment at {path}: "
            + "; ".join(mismatches)
        )
