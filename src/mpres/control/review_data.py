"""Normalize review problem identities; model output is not a database copier.

Raw audience-step results remain immutable execution evidence. `findings` is the
canonical accepted problem table. New accepted review results reference those
rows instead of retaining another independently editable problem-body array.
"""
from __future__ import annotations
from copy import deepcopy
import json
from mpres.util import MPresError, SubmissionRejected
from .store import encode


def step_catalog(service, attempt_id: str) -> list[dict]:
    rows = service.store.rows('SELECT sequence,phase,state,result_json FROM audience_steps WHERE attempt_id=? ORDER BY sequence', (attempt_id,))
    if any(row['state'] != 'completed' for row in rows):
        raise MPresError('Student reading and attention passes must finish before synthesis')
    result = []
    for row in rows:
        data = json.loads(row['result_json'])
        for i, finding in enumerate(data.get('findings', []), 1):
            result.append({'ref': f"step:{row['sequence']}:{i}", 'phase': row['phase'], 'finding': finding})
    return result


def prepare(service, job: dict, attempt_id: str, submitted: dict) -> dict:
    """Resolve explicit problem links; never infer severity or invent evidence."""
    value = deepcopy(submitted)
    if job['kind'] != 'review':
        return value
    catalog = step_catalog(service, attempt_id) if job['channel'] == 'audience' else []
    findings = []
    aliases = {}
    exact = {}
    def add(alias, finding):
        key = encode(finding)
        if key not in exact:
            exact[key] = len(findings)
            findings.append(deepcopy(finding))
        aliases[alias] = f"{job['id']}:{exact[key]+1}"
    for entry in catalog:
        add(entry['ref'], entry['finding'])
    for i, finding in enumerate(value.get('findings', []), 1):
        add(f'new:{i}', finding)
    # Optional explicit references are assertions of identity, not a selection
    # that may silently drop an accepted earlier issue.
    for ref in value.pop('finding_refs', []):
        if ref not in aliases:
            raise SubmissionRejected(f'Unknown or foreign review finding reference: {ref}')
    for field, bad_status in (('feedback_checks', 'issue'), ('repair_checks', 'needs_decision')):
        for row in value.get(field, []):
            refs = row.get('finding_refs')
            if refs is None:
                continue
            if row['status'] != bad_status or not refs or len(set(refs)) != len(refs):
                raise SubmissionRejected('Problem references require an actual issue/needs_decision and unique nonempty refs')
            resolved = []
            for ref in refs:
                if ref not in aliases:
                    raise SubmissionRejected(f'Unknown or foreign review finding reference: {ref}')
                if aliases[ref] not in resolved:
                    resolved.append(aliases[ref])
            row['finding_refs'] = resolved
            row.setdefault('explanation', 'See the referenced review problems; no separate semantic claim is added.')
            row.setdefault('evidence' if field == 'feedback_checks' else 'slide_ids', [])
    value['findings'] = findings
    return value


def referenced_findings(job: dict, result: dict, refs: list[str]) -> list[dict]:
    known = {f"{job['id']}:{i}": f for i, f in enumerate(result.get('findings', []), 1)}
    if not isinstance(refs, list) or not refs or len(set(refs)) != len(refs) or any(r not in known for r in refs):
        raise SubmissionRejected('Finding reference is outside this review job/current source')
    return [known[r] for r in refs]


def storage_result(job: dict, result: dict) -> dict:
    if job['kind'] != 'review':
        return result
    value = deepcopy(result)
    value['finding_ids'] = [f"{job['id']}:{i}" for i, _ in enumerate(value.pop('findings'), 1)]
    value['storage_schema'] = 'review-references-v1'
    return value
