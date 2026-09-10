"""A derived, cumulative delivery ZIP; releases/artifacts remain the source of truth.

Only committed releases are exported. Compression happens outside the writer
transaction; publication rechecks the release set so an older exporter cannot
replace a newer bundle. No new manifests, hashes, skills or DB schema are needed.
"""
from __future__ import annotations

import json
import os
import shutil
import stat
import tempfile
import zipfile
from pathlib import Path, PurePosixPath

from mpres.util import MPresError, safe_id
from .files import inside
from .store import Store, event


_RELEASES = """SELECT r.presentation,r.artifact_id,r.gate_id,r.pdf_path,
                     a.path AS source_path,g.pdf_path AS checked_pdf_path
              FROM releases r JOIN artifacts a ON a.id=r.artifact_id
              JOIN gate_runs g ON g.id=r.gate_id
              WHERE r.state='committed' ORDER BY r.presentation"""
_CHUNK = 1024 * 1024


def _same_stream(a, b) -> bool:
    while True:
        left, right = a.read(_CHUNK), b.read(_CHUNK)
        if left != right:
            return False
        if not left:
            return True


def _same_file(a: Path, b: Path) -> bool:
    if a.stat().st_size != b.stat().st_size:
        return False
    with a.open('rb') as left, b.open('rb') as right:
        return _same_stream(left, right)


class Delivery:
    def __init__(self, task: Path):
        self.task = task.resolve()
        safe_id(self.task.name, label='task slug')
        self.store = Store(self.task)
        self.folder = self.task.name + '-delivery'
        self.relative = f'deliverables/{self.folder}.zip'

    def _releases(self, conn=None) -> list[dict]:
        if conn is not None:
            return [dict(row) for row in conn.execute(_RELEASES)]
        return self.store.rows(_RELEASES)

    def status(self) -> dict:
        """Cheap view of a generated ZIP, not another canonical release record."""
        releases = self._releases()
        base = {'path': str(self.task / self.relative),
                'presentations': [r['presentation'] for r in releases]}
        if not releases:
            return {**base, 'state': 'not_applicable'}
        rows = self.store.rows(
            "SELECT detail_json FROM events WHERE kind='delivery.bundled' AND json_extract(detail_json,'$.path')=? ORDER BY id DESC LIMIT 1", (self.relative,))
        last = json.loads(rows[0]['detail_json']) if rows else {}
        try:
            path = inside(self.task, self.relative)
        except MPresError as exc:
            return {**base, 'state': 'failed', 'error': str(exc)}
        if path.is_file() and last.get('releases') == releases:
            info = path.stat()
            if last.get('bytes') == info.st_size and last.get('mtime_ns') == info.st_mtime_ns:
                return {**base, 'state': 'ready', 'bytes': info.st_size,
                        'file_count': last['file_count']}
        return {**base, 'state': 'pending'}

    def ensure(self) -> dict:
        """Normal runner path: unchanged published content needs no repeated ZIP I/O."""
        try:
            current = self.status()
            if current['state'] != 'pending':
                return current
            return self.bundle()
        except (MPresError, OSError, ValueError, zipfile.BadZipFile) as exc:
            # The PDF release stays committed; packaging is independently retryable.
            return {'state': 'failed', 'path': str(self.task / self.relative),
                    'error': str(exc), 'retry_command': f'workflow bundle {self.task.name}'}

    def _entries(self, releases: list[dict]) -> list[tuple[str, Path]]:
        entries: list[tuple[str, Path]] = []
        used: set[str] = set()

        def add(name: str, source: Path) -> None:
            # ZIPs are often extracted on Windows; reject ambiguous/colliding names.
            parts = PurePosixPath(name).parts
            if any('\\' in p or ':' in p or p.endswith((' ', '.')) for p in parts):
                raise MPresError(f'Unsafe delivery archive name: {name}')
            key = name.casefold()
            if key in used:
                raise MPresError(f'Delivery archive filename collision: {name}')
            if not source.is_file() or source.is_symlink():
                raise MPresError(f'Missing/unsafe delivery input: {source}')
            used.add(key)
            entries.append((name, source))

        for release in releases:
            presentation = safe_id(release['presentation'], label='presentation ID')
            pdf = inside(self.task, release['pdf_path'])
            checked = inside(self.task, release['checked_pdf_path'])
            if not pdf.is_file() or not checked.is_file() or not _same_file(pdf, checked):
                raise MPresError(f'Committed PDF is missing or changed: {presentation}')
            source = inside(self.task, release['source_path'])
            markdown = inside(source, 'presentation.md')
            if not source.is_dir() or not markdown.is_file():
                raise MPresError(f'Committed source presentation.md is missing: {presentation}')
            prefix = f'{self.folder}/{presentation}'
            add(f'{prefix}/{presentation}.pdf', pdf)
            for item in sorted(source.rglob('*')):
                relative = item.relative_to(source).as_posix()
                file = inside(source, relative)  # Reject even inward-pointing symlinks.
                if file.is_dir():
                    continue
                name = f'{presentation}.md' if relative == 'presentation.md' else relative
                add(f'{prefix}/{name}', file)
        return sorted(entries)

    @staticmethod
    def _matches(path: Path, entries: list[tuple[str, Path]]) -> bool:
        try:
            with zipfile.ZipFile(path) as archive:
                if archive.namelist() != [name for name, _ in entries]:
                    return False
                for name, source in entries:
                    if archive.getinfo(name).file_size != source.stat().st_size:
                        return False
                    with archive.open(name) as exported, source.open('rb') as original:
                        if not _same_stream(exported, original):
                            return False
            return True
        except (zipfile.BadZipFile, EOFError, RuntimeError):
            return False

    @staticmethod
    def _write(path: Path, entries: list[tuple[str, Path]]) -> None:
        # Fixed metadata avoids encoding workspace timestamps/read-only permissions
        # into the user-facing archive. The original files are never renamed.
        with zipfile.ZipFile(path, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
            for name, source in entries:
                info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
                info.compress_type = zipfile.ZIP_DEFLATED
                info.create_system = 3
                info.external_attr = (stat.S_IFREG | 0o644) << 16
                with source.open('rb') as original, archive.open(info, 'w', force_zip64=True) as exported:
                    shutil.copyfileobj(original, exported, length=_CHUNK)
        with path.open('rb') as written:
            os.fsync(written.fileno())

    def bundle(self) -> dict:
        """Explicit export also verifies existing archive bytes; no rerender or AI call."""
        releases = self._releases()
        if not releases:
            raise MPresError('No committed deliveries to bundle; drafts/prepared releases are not deliverables')
        entries = self._entries(releases)
        target = inside(self.task, self.relative)
        target.parent.mkdir(parents=True, exist_ok=True)
        unchanged = target.is_file() and self._matches(target, entries)
        stage = None
        try:
            if not unchanged:
                pending = inside(self.task, '.mpres/delivery-staging')
                pending.mkdir(parents=True, exist_ok=True)
                fd, filename = tempfile.mkstemp(prefix='bundle-', suffix='.zip', dir=pending)
                os.close(fd)
                stage = Path(filename)
                self._write(stage, entries)
                if not self._matches(stage, entries):
                    raise MPresError('Delivery ZIP verification failed; previous ZIP was preserved')
            with self.store.transaction() as conn:
                if self._releases(conn) != releases:
                    raise MPresError('Committed releases changed during packaging; retry bundle')
                # All generated ZIP replacements are serialized by this short transaction.
                if stage is not None:
                    inside(self.task, self.relative)
                    os.replace(stage, target)
                info = target.stat()
                receipt = {'path': self.relative, 'releases': releases,
                           'file_count': len(entries), 'bytes': info.st_size, 'mtime_ns': info.st_mtime_ns}
                old = conn.execute("SELECT detail_json FROM events WHERE kind='delivery.bundled' AND json_extract(detail_json,'$.path')=? ORDER BY id DESC LIMIT 1", (self.relative,)).fetchone()
                if not old or json.loads(old['detail_json']) != receipt:
                    event(conn, 'delivery.bundled', receipt)
            return {'state': 'ready', 'path': str(target), 'bytes': info.st_size,
                    'file_count': len(entries), 'presentations': [r['presentation'] for r in releases],
                    'already_bundled': unchanged}
        finally:
            if stage is not None:
                stage.unlink(missing_ok=True)
