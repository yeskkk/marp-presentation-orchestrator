"""Mechanical quality checks on immutable revisions. No AI-authored gate receipts.

All expensive work is outside SQLite transactions. Failures are durable results,
not exceptions disguised as success. A full pass requires native Marp + DOM +
math-renderer + PDF checks, never a task-selected mock or provider assertion.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from mpres.html_layout import inspect_marp_html_layout
from mpres.marp_source import lint_deck, parse_deck
from mpres.math_inspection import inspect_math_renderer, inspect_math_source
from mpres.pdf_inspection import inspect_pdf_file
from mpres.rendering import _marp_command
from mpres.toolchain import require_pinned_marp
from mpres.util import MPresError, run_command, utc_now
from .files import copy_tree, inside, remove_tree
from .service import Service, uid
from .store import encode, event
from .inspection import INSPECTION_POLICY_VERSION, normalize_check, normalize_report, page_check, warning_metadata


class Quality:
    def __init__(self, task: Path):
        self.service = Service(task)
        self.task = self.service.task
        self.store = self.service.store
        self.root = self.task.parent.parent

    def latest(self, artifact_id: str, level: str) -> dict | None:
        rows = self.store.rows('SELECT * FROM gate_runs WHERE artifact_id=? AND level=? ORDER BY sequence DESC LIMIT 1', (artifact_id, level))
        return rows[0] if rows else None

    def require_pass(self, artifact_id: str, level: str = 'full', conn=None) -> dict:
        query = 'SELECT * FROM gate_runs WHERE artifact_id=? AND level=? ORDER BY sequence DESC LIMIT 1'
        row = conn.execute(query, (artifact_id, level)).fetchone() if conn else self.latest(artifact_id, level)
        if not row or row['state'] != 'passed':
            raise MPresError(f'Revision {artifact_id} lacks a current successful {level} gate')
        from mpres.source_policy import POLICY_VERSION
        detail=json.loads(row['detail_json'] or '{}')
        if detail.get('source_policy_version') != POLICY_VERSION or detail.get('inspection_policy_version') != INSPECTION_POLICY_VERSION:
            raise MPresError('Gate predates the current source contract; run artifact inspect --retry before reuse')
        return dict(row)

    def inspect(self, artifact_id: str, level: str = 'source', *, retry: bool = False, _automatic: bool = False) -> dict:
        if level not in {'source', 'full'}:
            raise MPresError('Gate level must be source or full')
        with self.store.transaction() as conn:
            cfg = self.service.confirmed(conn)
            artifact = conn.execute('SELECT * FROM artifacts WHERE id=?', (artifact_id,)).fetchone()
            if not artifact:
                raise MPresError('Unknown source revision')
            artifact = dict(artifact)
            old = conn.execute('SELECT * FROM gate_runs WHERE artifact_id=? AND level=? ORDER BY sequence DESC LIMIT 1', (artifact_id, level)).fetchone()
            from mpres.source_policy import POLICY_VERSION
            current_policy = old and json.loads(old['detail_json'] or '{}').get('source_policy_version') == POLICY_VERSION and json.loads(old['detail_json'] or '{}').get('inspection_policy_version') == INSPECTION_POLICY_VERSION
            if old and (old['state'] == 'running' or (not retry and current_policy)):
                return {**dict(old), 'already_recorded': True}
            if _automatic:
                from .recovery import policy
                limit=policy(json.loads(cfg['settings_json']))['transient_tool_retries']
                failures=conn.execute("SELECT count(*) FROM gate_runs WHERE artifact_id=? AND level=? AND json_extract(detail_json,'$.failure_kind')='transient_tool'",(artifact_id,level)).fetchone()[0]
                if not old or old['state']!='failed' or json.loads(old['detail_json'] or '{}').get('failure_kind')!='transient_tool' or failures>limit:
                    return {**dict(old), 'already_recorded': True}
            gate_id = uid('g')
            conn.execute("INSERT INTO gate_runs(id,artifact_id,level,sequence,state,started_at) VALUES(?,?,?,?,'running',?)",
                         (gate_id, artifact_id, level, 1 if not old else old['sequence']+1, utc_now()))
            event(conn, 'gate.started', {'gate_id': gate_id, 'artifact_id': artifact_id, 'level': level})
            settings = json.loads(cfg['settings_json'])
        start = time.monotonic()
        try:
            report = self._run(artifact, gate_id, level, settings)
        except Exception as exc:
            from .recovery import transient
            report = {'success': False, 'checks': {}, 'errors': [f'{type(exc).__name__}: {exc}'],
                      'failure_kind': 'transient_tool' if transient(exc) else 'tool_or_input'}
        from mpres.source_policy import POLICY_VERSION
        report['source_policy_version'] = POLICY_VERSION
        report = normalize_report(report)
        report['seconds'] = time.monotonic()-start
        report['artifact_id'] = artifact_id
        report['gate_id'] = gate_id
        if level == 'full' and report['success']:
            report['warning_report'] = warning_metadata(report)
        state = 'passed' if report.get('success') is True else 'failed'
        with self.store.transaction() as conn:
            self.service.confirmed(conn)
            row = conn.execute('SELECT state FROM gate_runs WHERE id=?', (gate_id,)).fetchone()
            if row['state'] != 'running':
                raise MPresError('Gate was interrupted while executing; do not accept late results')
            conn.execute('UPDATE gate_runs SET state=?,finished_at=?,detail_json=?,pdf_path=? WHERE id=?',
                         (state, utc_now(), encode(report), report.get('pdf_path'), gate_id))
            for name, detail in report.get('checks', {}).items():
                conn.execute('INSERT INTO checks(artifact_id,name,success,detail_json,created_at) VALUES(?,?,?,?,?)',
                             (artifact_id, name, int(detail.get('success') is True), encode({'storage_schema':'gate-check-reference-v1','gate_id':gate_id,'check_name':name}), utc_now()))
            event(conn, 'gate.finished', {'gate_id': gate_id, 'artifact_id': artifact_id, 'state': state, 'seconds': report['seconds']})
        return {**self.latest(artifact_id, level), 'already_recorded': False}

    def inspect_recovering(self, artifact_id: str, level: str = 'source') -> dict:
        """Bounded same-revision local retries, outside write transactions.

        Counting durable gate rows prevents a fresh tick from resetting the budget.
        A running gate is never reclaimed just because an exception looked temporary.
        """
        from .recovery import policy
        with self.store.transaction() as conn:
            limit=policy(json.loads(self.service.confirmed(conn)['settings_json']))['transient_tool_retries']
        result=self.inspect(artifact_id,level)
        while result['state']=='failed' and json.loads(result.get('detail_json') or '{}').get('failure_kind')=='transient_tool':
            count=sum(json.loads(g['detail_json'] or '{}').get('failure_kind')=='transient_tool'
                      for g in self.store.rows('SELECT detail_json FROM gate_runs WHERE artifact_id=? AND level=?',(artifact_id,level)))
            if count>limit: break
            with self.store.transaction() as conn:
                event(conn,'gate.automatic_retry',{'artifact_id':artifact_id,'level':level,'previous_gate_id':result['id'],'retry':count,'limit':limit})
            result=self.inspect(artifact_id,level,retry=True,_automatic=True)
        return result

    def interrupt(self, gate_id: str, reason: str) -> None:
        """Explicit operator recovery only after confirming the local checker stopped."""
        from .service import require_text
        require_text(reason, 'Stopped-process verification')
        with self.store.transaction() as conn:
            self.service.confirmed(conn)
            row = conn.execute('SELECT state FROM gate_runs WHERE id=?', (gate_id,)).fetchone()
            if not row or row['state'] != 'running':
                raise MPresError('Only an outstanding mechanical gate can be interrupted')
            conn.execute("UPDATE gate_runs SET state='interrupted',finished_at=?,detail_json=? WHERE id=?", (utc_now(), encode({'reason': reason}), gate_id))
            event(conn, 'gate.interrupted', {'gate_id': gate_id, 'reason': reason})

    def _run(self, artifact: dict, gate_id: str, level: str, settings: dict) -> dict:
        source = inside(self.task, artifact['path'])
        try:
            checks = {'source': lint_deck(source, process_records=False), 'math_source': inspect_math_source(source)}
        except (MPresError, ValueError, UnicodeError) as exc:
            # Parsing invalid authored Markdown/TeX is not a broken browser.
            return {'success':False,'checks':{},'failure_kind':'content','errors':[str(exc)]}
        # Source lint already validates local image paths. CSS/SVG external loads
        # must also be caught before passing --allow-local-files to a browser.
        checks['asset_boundary'] = asset_boundary(source)
        checks['pages'] = page_check(len(parse_deck(source/'presentation.md').slides), 'draft')
        checks = {name: normalize_check(name, c) for name, c in checks.items()}
        if not all(c['success'] for c in checks.values()):
            return {'success': False, 'checks': checks, 'failure_kind': 'content'}
        if level == 'source':
            return {'success': True, 'checks': checks}
        quality = settings.get('quality', {'browser': 'auto', 'timeout_seconds': 1800})
        timeout = quality['timeout_seconds']
        policy = {'marp': {'browser': quality['browser']}}
        require_pinned_marp(self.root)
        build = self.task/'.mpres'/'gates'/gate_id
        build.mkdir(parents=True)
        work = build/'source'
        copy_tree(source, work, read_only=False)
        try:
            checks['html_layout'] = inspect_marp_html_layout(self.root, work, policy=policy, timeout=timeout)
            if checks['html_layout'].get('returncode', 0) != 0:
                return {'success': False, 'checks': checks, 'failure_kind': 'tool_or_input'}
            checks['math_renderer'] = inspect_math_renderer(checks['math_source'], checks['html_layout'])
            checks = {name: normalize_check(name, c) for name, c in checks.items()}
            if not all(c['success'] for c in checks.values()):
                return {'success': False, 'checks': checks, 'failure_kind': 'layout_or_renderer'}
            pdf = build/'presentation.pdf'
            cmd = _marp_command(self.root, work, pdf, policy)
            proc = run_command(cmd, cwd=work, timeout=timeout)
            checks['render'] = {'success': proc.returncode == 0 and pdf.is_file(), 'command': cmd,
                                'returncode': proc.returncode, 'stderr': proc.stderr[-4000:]}
            if not checks['render']['success']:
                if 'TargetClosedError:' in proc.stderr:
                    from mpres.util import TransientToolError
                    raise TransientToolError('Marp browser closed during PDF rendering: '+proc.stderr[-1000:])
                return {'success': False, 'checks': checks, 'failure_kind': 'tool_or_input'}
            checks['pdf'] = inspect_pdf_file(pdf, expected_pages=len(parse_deck(work/'presentation.md').slides))
            checks = {name: normalize_check(name, c) for name, c in checks.items()}
            ok = all(c['success'] for c in checks.values())
            if ok:
                pdf.chmod(0o444)
            return {'success': ok, 'checks': checks, 'pdf_path': pdf.relative_to(self.task).as_posix() if ok else None,
                    'failure_kind': None if ok else 'pdf'}
        finally:
            remove_tree(work)


def asset_boundary(source: Path) -> dict:
    """Reject active content and non-local resource loads; this is not an OS sandbox."""
    import re
    from urllib.parse import unquote, urlsplit
    from bs4 import BeautifulSoup
    errors = []
    def resource(raw, parent):
        raw = unquote(raw.strip().strip('\"\''))
        if not raw or raw.startswith('#'):
            return
        parsed = urlsplit(raw)
        if parsed.scheme or parsed.netloc or raw.startswith('/'):
            errors.append(f'External or absolute resource: {raw}')
            return
        try:
            target = inside(source, parent.relative_to(source).joinpath(parsed.path).as_posix())
            if not target.is_file():
                errors.append(f'Missing resource: {raw}')
        except (MPresError, ValueError):
            errors.append(f'Resource escapes source: {raw}')
    for path in source.rglob('*'):
        if path.is_symlink():
            errors.append(f'Symlink: {path.name}')
        if not path.is_file() or path.suffix.lower() not in {'.md', '.css', '.svg', '.html'}:
            continue
        text = path.read_text(encoding='utf-8')
        if path.suffix.lower()!='.md' and re.search(r'@import|expression\s*\(', text, re.I):
            errors.append(f'CSS import/active expression forbidden: {path.name}')
        for ref in ([] if path.suffix.lower()=='.md' else re.findall(r'url\(\s*([^)]*?)\s*\)', text, re.I)):
            resource(ref, path.parent)
        if path.suffix.lower()=='.md':
            continue  # parsed Markdown/source policy owns HTML and image detection
        html = BeautifulSoup(text, 'html.parser')
        for element in html.find_all(True):
            if element.name.lower() in {'script', 'iframe', 'object', 'embed', 'base', 'link', 'foreignobject'}:
                errors.append(f'Active HTML/SVG element: {element.name}')
            for attr, value in element.attrs.items():
                if attr.lower().startswith('on') or attr.lower() in {'srcset'}:
                    errors.append(f'Active/unsupported resource attribute: {attr}')
                if attr in {'src', 'xlink:href'} or (attr == 'href' and element.name.lower() not in {'a'}):
                    resource(str(value), path.parent)
    return {'success': not errors, 'errors': errors}
