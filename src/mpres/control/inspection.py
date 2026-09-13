"""Normalize mechanical diagnostics without conflating warnings and execution.

Old checker payloads remain evidence. A warning alone is not a failed gate;
an unexecuted or unclassified failed check is not a successful check. Current
warning exports are derived from one exact gate, never a mutable second ledger.
"""
from __future__ import annotations
from copy import deepcopy
from pathlib import Path
from mpres.util import MPresError
from .store import encode

INSPECTION_POLICY_VERSION = 1
PLANNED_PAGES = 100
DELIVERY_PAGES = 120
DRAFT_ERROR_ABOVE = 130


def normalize_check(name: str, raw: dict) -> dict:
    out = deepcopy(raw)
    execution = out.get('execution_state', 'completed')
    if out.get('returncode', 0) != 0:
        execution = 'failed'
    if execution not in {'completed', 'failed', 'not_run', 'interrupted'}:
        execution = 'failed'
    issues = []
    for item in out.get('issues', []):
        if not isinstance(item, dict) or item.get('severity') not in {'error', 'warning'} or not isinstance(item.get('message'), str) or not item['message'].strip():
            raise MPresError(f'Malformed mechanical issue in {name}')
        issues.append({**item, 'code': item.get('code', f'{name}.{item["severity"]}')})
    for field, severity in (('errors', 'error'), ('warnings', 'warning')):
        for item in out.get(field, []):
            issue = dict(item) if isinstance(item, dict) else {'message': str(item)}
            issue.update(severity=severity)
            issue.setdefault('code', f'{name}.{severity}')
            if not any(i['severity'] == severity and i['message'] == issue.get('message') for i in issues):
                issues.append(issue)
    if execution != 'completed' and not any(i['severity'] == 'error' for i in issues):
        issues.append({'code': f'{name}.execution', 'severity': 'error', 'message': f'Required check {name} did not complete: {execution}'})
    if execution == 'completed' and out.get('success', out.get('ok')) is False and not issues:
        issues.append({'code': f'{name}.unclassified_failure', 'severity': 'error', 'message': f'Checker {name} failed without a classified explanation; investigate the tool.'})
    out.update(execution_state=execution, issues=issues,
               errors=[i['message'] for i in issues if i['severity'] == 'error'],
               warnings=[i['message'] for i in issues if i['severity'] == 'warning'],
               success=execution == 'completed' and not any(i['severity'] == 'error' for i in issues))
    return out


def page_check(count: int, stage: str = 'draft') -> dict:
    if type(count) is not int or count < 1:
        raise MPresError('Page count must be a positive integer')
    if stage not in {'plan', 'draft', 'delivery'}:
        raise MPresError('Unknown page-check stage')
    maximum = {'plan': PLANNED_PAGES, 'draft': DRAFT_ERROR_ABOVE, 'delivery': DELIVERY_PAGES}[stage]
    issues = []
    if count > maximum:
        issues.append({'code': f'pages.{stage}.limit', 'severity': 'error',
                       'message': f'{count} pages exceed the {stage} limit {maximum}. Split at a learning boundary; do not shrink the theme.',
                       'page_count': count, 'limit': maximum})
    elif stage == 'draft' and count > DELIVERY_PAGES:
        issues.append({'code': 'pages.draft.headroom', 'severity': 'warning',
                       'message': f'{count} draft pages; delivery allows at most {DELIVERY_PAGES}. Reduce or split before publication.',
                       'page_count': count, 'limit': DELIVERY_PAGES})
    return normalize_check('pages', {'execution_state': 'completed', 'issues': issues,
                                    'success': not any(i['severity'] == 'error' for i in issues),
                                    'page_count': count, 'stage': stage})


def plan_checks(settings: dict) -> dict:
    result = {}
    for deck in settings['presentations']:
        count = deck.get('estimated_pages')
        if count is None:
            result[deck['id']] = normalize_check('plan', {
                'success': True, 'warnings': ['No page estimate recorded; estimate and split in planning before authoring.'],
                'estimated_pages': None})
        else:
            result[deck['id']] = page_check(count, 'plan')
    return result


def normalize_report(raw: dict) -> dict:
    report = deepcopy(raw)
    checks = {name: normalize_check(name, value) for name, value in report.get('checks', {}).items()}
    top = normalize_check('gate', {k: v for k, v in report.items() if k in {'errors', 'warnings', 'execution_state'}})
    # An explicit unexplained pipeline failure cannot be rescued by unrelated
    # successful subchecks. A warning-only legacy checker can be normalized.
    warning_only = any(v.get('success') is False and checks[k]['success'] and checks[k]['warnings'] for k, v in raw.get('checks', {}).items())
    if (report.get('success') is False and not warning_only and all(c['success'] for c in checks.values()) and not top['issues']) or not checks:
        top = normalize_check('gate', {'success': False, 'errors': top['errors'], 'warnings': top['warnings'],
                                      'issues': [{'code':'gate.incomplete','severity':'error','message':'The gate did not complete all required checks.'}]})
    report['checks'] = checks
    report['issues'] = [{**i, 'check': name} for name, value in checks.items() for i in value['issues']]
    report['issues'].extend({**i, 'check': 'gate'} for i in top['issues'])
    report['success'] = top['success'] and bool(checks) and all(c['success'] for c in checks.values())
    report['error_count'] = sum(i['severity'] == 'error' for i in report['issues'])
    report['warning_count'] = sum(i['severity'] == 'warning' for i in report['issues'])
    report['inspection_policy_version'] = INSPECTION_POLICY_VERSION
    if report['success']:
        report['failure_kind'] = None
    return report


def warning_record(report: dict) -> dict:
    warnings = []
    seen = set()
    for issue in report.get('issues', []):
        if issue['severity'] != 'warning':
            continue
        key = encode(issue)
        if key in seen:
            continue
        seen.add(key)
        warnings.append({'id': f"{report['gate_id']}:w{len(warnings)+1}", **issue, 'status': 'open'})
    return {'schema_version': 1, 'artifact_id': report['artifact_id'], 'gate_id': report['gate_id'],
            'scope': 'current_revision_mechanical_checks', 'coverage': 'recorded_checks_only',
            'unresolved_count': len(warnings), 'warnings': warnings,
            'note': 'Only current-gate warnings are counted. Older reports remain in SQLite. This is not a semantic quality certificate.'}


def warning_metadata(report: dict) -> dict:
    record = warning_record(report)
    prefix = f".mpres/gates/{report['gate_id']}"
    return {'unresolved_count': record['unresolved_count'], 'coverage': record['coverage'],
            'json_path': prefix+'/WARNINGS.json', 'markdown_path': prefix+'/WARNINGS.md'}


def _write_view(path: Path, text: str) -> None:
    import os, tempfile
    data = text.encode('utf-8')
    if path.is_file() and path.read_bytes() == data:
        return
    fd, tmp = tempfile.mkstemp(prefix='.warnings-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as f:
            f.write(data); f.flush(); os.fsync(f.fileno())
        os.replace(tmp, path)
    finally:
        Path(tmp).unlink(missing_ok=True)


def write_warning_report(task: Path, report: dict) -> dict:
    record = warning_record(report)
    folder = task / '.mpres' / 'gates' / report['gate_id']
    folder.mkdir(parents=True, exist_ok=True)
    data = folder / 'WARNINGS.json'; human = folder / 'WARNINGS.md'
    _write_view(data, encode(record) + '\n')
    lines = ['# 交付警告记录', '', f"源码修订：`{record['artifact_id']}`  ", f"检查：`{record['gate_id']}`", '',
             f"**未处理 warning：{record['unresolved_count']} 条。**", '',
             '本记录供用户查看，不进入学生课件。仅统计本次检查中当前修订的机械警告；旧稿记录不重复计入，未知检查不写成零。', '']
    for item in record['warnings']:
        lines.extend([f"## {item['id']}", f"检查：{item['check']}；代码：`{item['code']}`", '', item['message'], ''])
        if item.get('slide_ids'):
            lines.append('页面：' + ', '.join(item['slide_ids']))
    if not record['warnings']:
        lines.append('当前记录的机械检查没有遗留 warning；这不等同于独立教学质量证明。')
    _write_view(human, '\n'.join(lines) + '\n')
    return {'unresolved_count': record['unresolved_count'], 'coverage': record['coverage'],
            'json_path': data.relative_to(task).as_posix(), 'markdown_path': human.relative_to(task).as_posix()}
