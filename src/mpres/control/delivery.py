"""Direct, derived delivery directories, never a second release authority.

The private committed PDF and immutable source revision are paired in one staging
folder. A short SQLite writer transaction rechecks the release and swaps each
complete presentation directory. The deterministic previous-directory path makes
an interrupted rename recoverable. No automatic ZIPs, new tables or checksums.
"""
from __future__ import annotations

import json
import os
import shutil
import tempfile
from pathlib import Path, PurePosixPath

from mpres.util import MPresError, safe_id
from .files import inside, remove_tree
from .store import Store, event

_RELEASES = """SELECT r.presentation,r.artifact_id,r.gate_id,r.pdf_path,
                     a.path AS source_path,g.pdf_path AS checked_pdf_path
              FROM releases r JOIN artifacts a ON a.id=r.artifact_id
              JOIN gate_runs g ON g.id=r.gate_id
              WHERE r.state='committed' AND NOT EXISTS (SELECT 1 FROM delivery_parts p WHERE p.parent=r.presentation AND p.presentation<>p.parent) ORDER BY r.presentation"""
_CHUNK = 1024 * 1024


def _same_file(a: Path, b: Path) -> bool:
    if a.stat().st_size != b.stat().st_size:
        return False
    with a.open('rb') as left, b.open('rb') as right:
        while True:
            x, y = left.read(_CHUNK), right.read(_CHUNK)
            if x != y:
                return False
            if not x:
                return True


def _inventory(folder: Path) -> list[dict]:
    if folder.is_symlink():
        raise MPresError(f'Symlink is forbidden: {folder}')
    if not folder.exists():
        return []
    if not folder.is_dir():
        raise MPresError(f'Delivery destination must be a directory: {folder}')
    result = []
    for item in sorted(folder.rglob('*')):
        rel = item.relative_to(folder).as_posix()
        path = inside(folder, rel)
        if path.is_dir():
            continue
        if not path.is_file():
            raise MPresError(f'Only regular delivery files are allowed: {item}')
        st = path.stat()
        result.append({'path': rel, 'bytes': st.st_size, 'mtime_ns': st.st_mtime_ns})
    return result


class Delivery:
    def __init__(self, task: Path):
        self.task = task.resolve()
        safe_id(self.task.name, label='task slug')
        self.store = Store(self.task)
        self.relative = 'deliverables'

    def _releases(self, conn=None) -> list[dict]:
        if conn is not None:
            return [dict(row) for row in conn.execute(_RELEASES)]
        return self.store.rows(_RELEASES)

    def _receipt(self, presentation: str, conn=None) -> dict:
        query = "SELECT detail_json FROM events WHERE kind='delivery.materialized' AND json_extract(detail_json,'$.presentation')=? ORDER BY id DESC LIMIT 1"
        rows = list(conn.execute(query, (presentation,))) if conn else self.store.rows(query, (presentation,))
        return json.loads(rows[0]['detail_json']) if rows else {}

    def _description(self, release: dict) -> dict:
        pid = safe_id(release['presentation'], label='presentation ID')
        folder = inside(self.task, f'deliverables/{pid}')
        gate = self.store.rows('SELECT detail_json FROM gate_runs WHERE id=?', (release['gate_id'],))
        report = json.loads(gate[0]['detail_json'] or '{}').get('warning_report') if gate else None
        warning = {'unresolved_count': report['unresolved_count'], 'path': str(folder/'WARNINGS.md'), 'json_path': str(folder/'WARNINGS.json'), 'coverage': report['coverage']} if report else {'unresolved_count': None, 'coverage': 'legacy_not_recorded'}
        return {'warning_report': warning, 'presentation': pid, 'artifact_id': release['artifact_id'],
                'path': str(folder), 'pdf': str(folder / f'{pid}.pdf'),
                'markdown': str(folder / f'{pid}.md')}

    def status(self) -> dict:
        releases = self._releases()
        base = {'format': 'directory', 'path': str(self.task / self.relative),
                'presentations': [r['presentation'] for r in releases], 'entries': []}
        if not releases:
            return {**base, 'state': 'not_applicable'}
        try:
            for release in releases:
                entry = self._description(release)
                receipt = self._receipt(release['presentation'])
                files = _inventory(Path(entry['path']))
                entry['state'] = ('ready' if receipt.get('release') == release and files
                                  and receipt.get('files') == files else 'pending')
                entry['file_count'] = len(files)
                base['entries'].append(entry)
            return {**base, 'state': 'ready' if all(x['state'] == 'ready' for x in base['entries']) else 'pending',
                    'file_count': sum(x['file_count'] for x in base['entries'])}
        except (MPresError, OSError) as exc:
            return {**base, 'state': 'failed', 'error': str(exc)}

    def ensure(self) -> dict:
        try:
            current = self.status()
            if current['state'] != 'pending':
                return current
            return self.materialize()
        except (MPresError, OSError, ValueError) as exc:
            return {'state': 'failed', 'format': 'directory', 'path': str(self.task / self.relative),
                    'error': str(exc), 'retry_command': f'workflow materialize {self.task.name}'}

    def _entries(self, release: dict) -> list[tuple[str, Path]]:
        pid = safe_id(release['presentation'], label='presentation ID')
        pdf = inside(self.task, release['pdf_path'])
        checked = inside(self.task, release['checked_pdf_path'])
        if not pdf.is_file() or not checked.is_file() or not _same_file(pdf, checked):
            raise MPresError(f'Committed PDF is missing or changed: {pid}')
        source = inside(self.task, release['source_path'])
        markdown = inside(source, 'presentation.md')
        if not source.is_dir() or not markdown.is_file():
            raise MPresError(f'Committed source presentation.md is missing: {pid}')
        entries = [(f'{pid}.pdf', pdf)]
        for item in sorted(source.rglob('*')):
            relative = item.relative_to(source).as_posix()
            file = inside(source, relative)
            if file.is_dir():
                continue
            entries.append((f'{pid}.md' if relative == 'presentation.md' else relative, file))
        gate = self.store.rows('SELECT detail_json FROM gate_runs WHERE id=?', (release['gate_id'],))
        warning = json.loads(gate[0]['detail_json'] or '{}').get('warning_report') if gate else None
        if warning:
            from .inspection import write_warning_report
            write_warning_report(self.task, json.loads(gate[0]['detail_json']))
            entries.extend([('WARNINGS.md', inside(self.task, warning['markdown_path'])), ('WARNINGS.json', inside(self.task, warning['json_path']))])
        used = set()
        for name, file in entries:
            parts = PurePosixPath(name).parts
            if any('\\' in p or ':' in p or p.endswith((' ', '.')) or
                   p.split('.')[0].upper() in {'CON','PRN','AUX','NUL', *('COM'+str(i) for i in range(1,10)), *('LPT'+str(i) for i in range(1,10))} for p in parts):
                raise MPresError(f'Unsafe delivery filename: {name}')
            key = name.casefold()
            if key in used:
                raise MPresError(f'Delivery filename collision: {name}')
            if not file.is_file() or file.is_symlink():
                raise MPresError(f'Missing/unsafe delivery input: {file}')
            used.add(key)
        return sorted(entries)

    @staticmethod
    def _matches(folder: Path, entries: list[tuple[str, Path]]) -> bool:
        files = _inventory(folder)
        if [r['path'] for r in files] != [name for name, _ in entries]:
            return False
        return all(_same_file(inside(folder, name), source) for name, source in entries)

    @staticmethod
    def _write(folder: Path, entries: list[tuple[str, Path]]) -> None:
        folder.mkdir(parents=True, exist_ok=False)
        for name, source in entries:
            target = inside(folder, name)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
            target.chmod(0o644)  # Generated view is convenient to read/version, not canonical.
            with target.open('rb') as stream:
                os.fsync(stream.fileno())

    def materialize(self) -> dict:
        """Export committed pairs without models, rerendering, or configuration changes.

        Unmanaged/edited files are never overwritten. Move the edited directory
        aside (or import it as a new source revision), then retry. Removing an
        entire generated presentation directory is safe: it can be regenerated.
        """
        releases = self._releases()
        if not releases:
            raise MPresError('No committed deliveries to materialize; drafts/prepared releases are not deliverables')
        pending = inside(self.task, '.mpres/delivery-staging')
        pending.mkdir(parents=True, exist_ok=True)
        staging = Path(tempfile.mkdtemp(prefix='view-', dir=pending))
        prepared = []
        changed = False
        try:
            # Validate every input before changing any public directory.
            for release in releases:
                pid = release['presentation']
                target = inside(self.task, f'deliverables/{pid}')
                entries = self._entries(release)
                stage = staging / pid
                if not self._matches(target, entries):
                    self._write(stage, entries)
                    if not self._matches(stage, entries):
                        raise MPresError(f'Delivery directory verification failed: {pid}')
                prepared.append((release, entries, target, stage))
            with self.store.transaction() as conn:
                current={r['presentation']:r for r in Delivery(self.task)._releases(conn)}
                if self._releases(conn) != releases or any(current.get(r['presentation']) != r for r in releases):
                    raise MPresError('Committed releases changed during export; retry materialize')
                for release, entries, target, stage in prepared:
                    pid = release['presentation']
                    target = inside(self.task, f'deliverables/{pid}')
                    previous = inside(self.task, f'.mpres/delivery-staging/previous-{pid}')
                    receipt = self._receipt(pid, conn)
                    if previous.exists() and not target.exists():
                        # Crash after moving the old directory but before installing new.
                        target.parent.mkdir(parents=True, exist_ok=True)
                        os.replace(previous, target)
                    if not self._matches(target, entries):
                        if target.exists():
                            old = receipt.get('release')
                            if not old or not self._matches(target, self._entries(old)):
                                raise MPresError(f'Delivery directory has modified/unmanaged files: {target}; preserve edits elsewhere before retrying')
                        if not stage.is_dir():
                            raise MPresError('Delivery changed concurrently; retry materialize')
                        if previous.exists():
                            old = receipt.get('release')
                            if not old or not self._matches(previous, self._entries(old)):
                                raise MPresError('Unrecognized previous delivery directory; preserve it and reconcile')
                            remove_tree(previous)
                        target.parent.mkdir(parents=True, exist_ok=True)
                        if target.exists():
                            os.replace(target, previous)
                        try:
                            os.replace(stage, target)
                        except OSError:
                            if previous.exists() and not target.exists():
                                os.replace(previous, target)
                            raise
                        changed = True
                    record = {'presentation': pid, 'release': release,
                              'path': str(target.relative_to(self.task)), 'files': _inventory(target)}
                    if record != receipt:
                        event(conn, 'delivery.materialized', record)
                    # If the last process died after installing a complete directory,
                    # matching exact committed bytes is enough to finish its receipt.
                    if previous.exists():
                        remove_tree(previous)
            return {**self.status(), 'already_materialized': not changed,
                    'already_bundled': not changed, 'archive_created': False}
        finally:
            remove_tree(staging)

    def bundle(self) -> dict:
        """Deprecated CLI/API alias: now materializes directories, never a ZIP."""
        return self.materialize()
