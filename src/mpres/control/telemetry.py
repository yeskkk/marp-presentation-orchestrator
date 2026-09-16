"""Immutable dispatch scope and observed control-state transitions.

No provider is invoked, no old task is reclassified by its present-day purpose,
and no human activity is inferred. This module is not a semantic worker input.
"""
from __future__ import annotations

import json
import uuid
from typing import Any

from mpres.util import utc_now
from .store import encode, event


def pin_job(conn, job: dict) -> dict:
    """Reserve-time scope, in the same transaction as the first real attempt.

    Existing pins (including unknown values) never change. A pre-upgrade retry
    may use explicit repair links, but cannot attribute old attempts to today's
    batch or to a new campaign on the same presentation.
    """
    old = conn.execute('SELECT * FROM job_cost_context WHERE job_id=?', (job['id'],)).fetchone()
    if old:
        return dict(old)
    links = conn.execute('SELECT case_id FROM repair_jobs WHERE job_id=?', (job['id'],)).fetchall()
    prior = conn.execute('SELECT 1 FROM attempts WHERE job_id=? LIMIT 1', (job['id'],)).fetchone()
    case = links[0][0] if len(links) == 1 else None
    source = 'explicit_repair_job' if case else 'historical_retry_unassigned' if prior else 'dispatch_without_active_repair'
    if not case:
        # This exact, delimited key was created by Repairs.confirm, not a
        # substring/date match against a mutable current presentation.
        fields = (job.get('key') or '').split(':')
        if len(fields) == 4 and fields[0] == 'repair-review' and job['kind'] == 'review':
            linked = conn.execute('SELECT id FROM repair_cases WHERE id=?', (fields[1],)).fetchone()
            if linked:
                case, source = linked[0], 'explicit_review_first_job_key'
    if not case and not prior:
        rows = conn.execute("""SELECT c.id FROM decks d JOIN repair_cases c ON c.id=d.repair_case
            JOIN repair_targets t ON t.case_id=c.id AND t.presentation=d.presentation
            WHERE d.presentation=? AND c.state='running'""", (job['presentation'],)).fetchall()
        if len(rows) == 1:
            case, source = rows[0][0], 'confirmed_repair_at_reservation'
    batch = None
    if not prior:
        rows = conn.execute("""SELECT b.id FROM production_batches b JOIN production_batch_targets t
            ON t.batch_id=b.id WHERE b.state='running' AND t.presentation=?""", (job['presentation'],)).fetchall()
        if len(rows) == 1:
            batch = rows[0][0]
    conn.execute('INSERT INTO job_cost_context VALUES(?,?,?,?,?)',
                 (job['id'], case, batch, source, utc_now()))
    return dict(conn.execute('SELECT * FROM job_cost_context WHERE job_id=?', (job['id'],)).fetchone())


def context(service, job: dict) -> dict:
    """Idempotent helper for explicitly reserving/testing job metadata."""
    with service.store.transaction() as conn:
        return pin_job(conn, job)


def control_scope(conn, *, presentation: str | None = None) -> dict:
    """Scope observed now; never used to relabel historical model usage."""
    cases = conn.execute("SELECT id FROM repair_cases WHERE state IN ('diagnosing','proposed','presented','running')").fetchall()
    batches = conn.execute("SELECT id FROM production_batches WHERE state='running'").fetchall()
    case = cases[0][0] if len(cases) == 1 else None
    batch = batches[0][0] if len(batches) == 1 else None
    targets = []
    if case:
        targets = [r[0] for r in conn.execute('SELECT presentation FROM repair_targets WHERE case_id=? ORDER BY presentation', (case,))]
    elif batch:
        targets = [r[0] for r in conn.execute('SELECT presentation FROM production_batch_targets WHERE batch_id=? ORDER BY ordinal', (batch,))]
    if presentation:
        if case and presentation not in targets:
            case = None
        if batch and not conn.execute('SELECT 1 FROM production_batch_targets WHERE batch_id=? AND presentation=?', (batch, presentation)).fetchone():
            batch = None
        targets = [presentation]
    return {'repair_case_id': case, 'batch_id': batch,
            'presentations': targets, 'presentation': targets[0] if len(targets) == 1 else None}


def _classify(result: dict, in_flight: frozenset | set) -> tuple[str | None, dict]:
    status = result.get('status')
    outstanding = result.get('outstanding') or {}
    executions = outstanding.get('creations', []) + outstanding.get('executions', [])
    detail: dict[str, Any] = {'status': status}
    if result.get('reason'):
        detail['control_reason'] = str(result['reason'])[:2000]
    if result.get('pending_responses') or any(r.get('state') == 'uncertain' for r in executions):
        return 'provider_reconciliation', detail
    if status == 'awaiting_confirmation':
        return 'user_decision', detail
    if status == 'needs_host_observation':
        return 'host_observation', detail
    if outstanding.get('local_input_blocks'):
        detail['blocked_attempt_ids'] = [r.get('id') for r in outstanding['local_input_blocks']]
        return 'local_input_or_resource', detail
    if status == 'blocked':
        capacity = result.get('capacity') or {}
        if capacity.get('ok') is False:
            detail['control_reason'] = capacity.get('reason') or detail.get('control_reason')
            return 'capacity', detail
        return 'blocked_unclassified', detail
    if status == 'idle_or_waiting' and not in_flight:
        active = [r.get('id') for r in executions if r.get('state') in {'reserved', 'running', 'creating'}]
        if active:
            detail['outstanding_ids'] = active
            return 'external_execution_observed', detail
        return 'scheduling_or_dependency', detail
    # Issued work, foreground provider activity and an intentional pause are not
    # automatically labelled wasted waiting. A prior observed block is closed.
    return None, detail


def observed_wait(service, result: dict, *, in_flight=(), origin='runner.tick') -> None:
    """One event per state transition, not per poll. Open duration stays unknown.

    A closed interval measures the time between two observations of the control
    state, not continuous monitoring or proof that a person/provider was idle.
    """
    reason, detail = _classify(result, frozenset(in_flight))
    detail['origin'] = origin
    with service.store.transaction() as conn:
        detail.update(control_scope(conn))
        old = conn.execute('SELECT * FROM scheduler_observation WHERE singleton=1').fetchone()
        previous = json.loads(old['detail_json']) if old else {}
        identity = ('status', 'repair_case_id', 'batch_id', 'presentations', 'control_reason')
        if old and old['reason'] == reason and all(previous.get(k) == detail.get(k) for k in identity):
            return
        now = utc_now()
        if old and old['reason']:
            event(conn, 'scheduler.wait_closed', {
                'wait_id': previous.get('wait_id'), 'reason': old['reason'],
                'started_at': old['started_at'], 'finished_at': now,
                'evidence': 'observed_control_state_transition',
                'previous': previous, 'next': detail,
            })
        if reason:
            detail['wait_id'] = 'scheduler-wait-' + uuid.uuid4().hex
            event(conn, 'scheduler.wait_opened', {
                'wait_id': detail['wait_id'], 'reason': reason, 'started_at': now,
                'evidence': 'observed_control_state_transition', 'detail': detail,
            })
        conn.execute('''INSERT INTO scheduler_observation VALUES(1,?,?,?,?)
            ON CONFLICT(singleton) DO UPDATE SET reason=excluded.reason,
            started_at=excluded.started_at,detail_json=excluded.detail_json,updated_at=excluded.updated_at''',
            (reason, now if reason else None, encode(detail), now))
