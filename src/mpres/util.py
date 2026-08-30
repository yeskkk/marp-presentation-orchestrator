from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import tempfile
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

PLACEHOLDER_RE = re.compile(r"\[\[[A-Z0-9_]+\]\]")
SAFE_ID_RE = re.compile(r"[A-Za-z][A-Za-z0-9._-]{0,63}")


class MPresError(RuntimeError):
    """A user-facing workflow error."""


def utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def parse_utc(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)


def find_repo_root(start: Path | None = None) -> Path:
    override = os.environ.get("MPRES_ROOT")
    if override:
        root = Path(override).expanduser().resolve()
        if not (root / "pyproject.toml").exists():
            raise MPresError(f"MPRES_ROOT does not look like the project root: {root}")
        return root

    candidates: list[Path] = []
    if start is not None:
        candidates.append(start.resolve())
    candidates.extend([Path.cwd().resolve(), Path(__file__).resolve().parents[2]])
    seen: set[Path] = set()
    for base in candidates:
        for path in (base, *base.parents):
            if path in seen:
                continue
            seen.add(path)
            if (
                (path / "pyproject.toml").exists()
                and (path / "package.json").exists()
                and (path / "templates").is_dir()
            ):
                return path
    raise MPresError("Cannot locate repository root. Run inside the project or set MPRES_ROOT.")


def safe_id(value: str, *, label: str = "identifier") -> str:
    value = value.strip()
    if not SAFE_ID_RE.fullmatch(value):
        raise MPresError(f"Unsafe {label}: {value!r}")
    return value


def task_path(root: Path, slug: str) -> Path:
    safe_id(slug, label="task slug")
    path = (root / "tasks" / slug).resolve()
    tasks_root = (root / "tasks").resolve()
    if tasks_root not in path.parents:
        raise MPresError("Task path escaped tasks directory.")
    return path


def read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise MPresError(f"Missing JSON file: {path}") from exc
    except json.JSONDecodeError as exc:
        raise MPresError(f"Invalid JSON in {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise MPresError(f"Expected a JSON object in {path}.")
    return value


def write_json_atomic(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=path.parent, delete=False, newline="\n"
    ) as handle:
        handle.write(text)
        temp_path = Path(handle.name)
    os.replace(temp_path, path)


def read_yaml(path: Path) -> Any:
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise MPresError(f"Missing YAML file: {path}") from exc
    except yaml.YAMLError as exc:
        raise MPresError(f"Invalid YAML in {path}: {exc}") from exc


def write_yaml_atomic(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = yaml.safe_dump(data, allow_unicode=True, sort_keys=False, width=1000)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=path.parent, delete=False, newline="\n"
    ) as handle:
        handle.write(text)
        temp_path = Path(handle.name)
    os.replace(temp_path, path)


def task_sha256(path: Path) -> str:
    """Hash only ``tasks/<slug>/TASK.md`` for the user-confirmation gate."""

    resolved = path.expanduser().resolve()
    if (
        resolved.name != "TASK.md"
        or resolved.parent.parent.name != "tasks"
        or resolved.parent.name in {"", ".", ".."}
    ):
        raise MPresError("Only top-level TASK.md at tasks/<slug>/TASK.md may be hashed by this workflow.")
    path = resolved
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def text_placeholders(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8")
    return sorted(set(PLACEHOLDER_RE.findall(text)))


DEFAULT_COPY_EXCLUDES = {
    ".DS_Store",
    "Thumbs.db",
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
    "build",
}


def source_tree_symlinks(directory: Path) -> list[str]:
    directory = directory.resolve()
    if not directory.is_dir():
        raise MPresError(f"Source directory does not exist: {directory}")
    return [
        path.relative_to(directory).as_posix()
        for path in sorted(directory.rglob("*"))
        if path.is_symlink()
    ]


def require_no_symlinks(directory: Path) -> None:
    symlinks = source_tree_symlinks(directory)
    if symlinks:
        sample = ", ".join(symlinks[:8])
        extra = " ..." if len(symlinks) > 8 else ""
        raise MPresError(
            "Presentation source trees may not contain symlinks; copy actual files instead: "
            f"{sample}{extra}"
        )


def directory_inventory(
    directory: Path,
    *,
    exclude_names: Iterable[str] = DEFAULT_COPY_EXCLUDES,
    exclude_suffixes: Iterable[str] = (".pdf", ".log"),
) -> dict[str, Any]:
    """Return a non-cryptographic file inventory for diagnostics."""

    directory = directory.resolve()
    if not directory.is_dir():
        raise MPresError(f"Directory does not exist: {directory}")
    excluded = set(exclude_names)
    suffixes = tuple(exclude_suffixes)
    entries: list[dict[str, Any]] = []
    for path in sorted(directory.rglob("*")):
        rel = path.relative_to(directory)
        if any(part in excluded for part in rel.parts):
            continue
        if path.is_symlink():
            entries.append(
                {"path": rel.as_posix(), "type": "symlink", "target": os.readlink(path)}
            )
            continue
        if not path.is_file():
            continue
        if path.suffix.lower() in suffixes or path.name.startswith("render-report-"):
            continue
        stat_result = path.stat()
        entries.append(
            {
                "path": rel.as_posix(),
                "type": "file",
                "size": stat_result.st_size,
                "mtime_ns": stat_result.st_mtime_ns,
            }
        )
    return {"root": str(directory), "entries": entries, "file_count": len(entries)}


def make_tree_read_only(path: Path) -> None:
    if not path.exists():
        return
    for item in [*sorted(path.rglob("*"), reverse=True), path]:
        try:
            mode = item.stat().st_mode
            item.chmod(mode & ~stat.S_IWUSR & ~stat.S_IWGRP & ~stat.S_IWOTH)
        except OSError:
            pass


def make_tree_writable(path: Path) -> None:
    if not path.exists():
        return
    for item in [path, *sorted(path.rglob("*"))]:
        try:
            item.chmod(item.stat().st_mode | stat.S_IWUSR)
        except OSError:
            pass


def copy_source_tree(source: Path, destination: Path, *, read_only: bool = False) -> None:
    require_no_symlinks(source)
    if destination.exists():
        make_tree_writable(destination)
        shutil.rmtree(destination)
    excluded = set(DEFAULT_COPY_EXCLUDES)

    def ignore(directory: str, names: list[str]) -> set[str]:
        ignored: set[str] = set()
        for name in names:
            path = Path(directory) / name
            if name in excluded:
                ignored.add(name)
            elif path.is_file() and (
                path.suffix.lower() in {".pdf", ".log"}
                or name.startswith("render-report-")
                or name.startswith("inspection-report-")
            ):
                ignored.add(name)
        return ignored

    shutil.copytree(source, destination, ignore=ignore)
    if read_only:
        make_tree_read_only(destination)


def latest_mtime(path: Path) -> float | None:
    if not path.exists():
        return None
    mtimes = [path.stat().st_mtime]
    if path.is_dir():
        mtimes.extend(item.stat().st_mtime for item in path.rglob("*") if item.exists())
    return max(mtimes) if mtimes else None


def ensure_within(path: Path, parent: Path, *, label: str = "path") -> Path:
    resolved = path.expanduser().resolve()
    parent_resolved = parent.expanduser().resolve()
    if resolved != parent_resolved and parent_resolved not in resolved.parents:
        raise MPresError(f"{label} must be inside {parent_resolved}: {resolved}")
    return resolved


def run_command(
    command: list[str],
    *,
    cwd: Path | None = None,
    env: dict[str, str] | None = None,
    timeout: int | None = None,
) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            command,
            cwd=cwd,
            env=env,
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            timeout=timeout,
            check=False,
        )
    except FileNotFoundError as exc:
        raise MPresError(f"Command not found: {command[0]}") from exc
    except subprocess.TimeoutExpired as exc:
        raise MPresError(f"Command timed out after {timeout}s: {' '.join(command)}") from exc


def executable(name: str) -> str | None:
    return shutil.which(name)


def virtualenv_python(root: Path) -> Path | None:
    candidates = [root / ".venv" / "bin" / "python", root / ".venv" / "Scripts" / "python.exe"]
    for candidate in candidates:
        if candidate.exists():
            return candidate.absolute()
    return None


def local_marp_binary(root: Path) -> Path | None:
    candidates = [
        root / "node_modules" / ".bin" / "marp",
        root / "node_modules" / ".bin" / "marp.cmd",
        root / "node_modules" / "@marp-team" / "marp-cli" / "marp-cli.js",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate.absolute()
    found = shutil.which("marp")
    return Path(found).absolute() if found else None


def relative_display(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return str(path.resolve())
