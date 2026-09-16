"""Bounded foreground execution of already-authorized, exact requests.

Only admission decides dependencies/capacity. No retries, fabricated cancellation,
model choice or semantic judgement are performed here. The controller must make
admission and result acceptance atomic with respect to its own workflow state.
"""
from __future__ import annotations

from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from typing import Callable

from mpres.util import MPresError


def drive(admit: Callable, execute: Callable, *, workers: int, cycles: int) -> dict:
    if type(workers) is not int or workers < 1:
        raise MPresError('workers must be a positive integer')
    if type(cycles) is not int or cycles < 1:
        raise MPresError('cycles must be a positive integer')
    pending: dict = {}
    seen: set[str] = set()
    results: list[dict] = []
    last: dict = {}
    admissions = 0
    failed = False
    budget = False
    stopped = False
    admission_error = None

    def collect(done) -> None:
        nonlocal failed
        for future in done:
            rid = pending.pop(future)
            try:
                value = future.result()
                if not isinstance(value, dict) or value.get('request_id') != rid:
                    raise MPresError('Executor returned a conflicting/missing request identity')
            except Exception as exc:
                value = {'request_id': rid, 'status': 'executor_failed',
                         'error': f'{type(exc).__name__}: {exc}'}
            results.append(value)
            if value.get('status') != 'accepted':
                failed = True

    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix='mpres-provider') as pool:
        while True:
            # Do not overlook another failure that completed while a peer's
            # successful result was being consumed.
            collect([future for future in pending if future.done()])
            if not failed and not stopped and admissions < cycles:
                admissions += 1
                try:
                    last = admit(frozenset(pending.values()))
                    if not isinstance(last, dict):
                        raise MPresError('Admission must return a structured result')
                    requests = last.get('requests', [])
                    if not isinstance(requests, list):
                        raise MPresError('Admission requests must be a list')
                    identities = [q.get('request_id') if isinstance(q, dict) else None for q in requests]
                    if any(not isinstance(rid, str) or not rid for rid in identities):
                        raise MPresError('Rolling admission returned a missing request identity; no resend')
                    if len(set(identities)) != len(identities) or seen.intersection(identities):
                        raise MPresError('Rolling admission returned a duplicate request identity; no resend')
                    terminal = last.get('status') in {'blocked', 'paused', 'completed', 'awaiting_confirmation'}
                    if terminal and requests:
                        raise MPresError('Terminal admission may not contain new work')
                    stopped = terminal
                    # Validate the entire group before starting any member.
                    for q, rid in zip(requests, identities):
                        seen.add(rid)
                        pending[pool.submit(execute, q)] = rid
                except Exception as exc:
                    admission_error = f'{type(exc).__name__}: {exc}'
                    failed = True
            elif not failed and not stopped:
                budget = True
            if not pending:
                # A final result may have consumed the last admission allowance.
                if not failed and not stopped and admissions >= cycles:
                    budget = True
                break
            done, _ = wait(pending, return_when=FIRST_COMPLETED)
            collect(done)
            # Failures, terminal results and exhausted budgets drain every
            # already-issued operation, without admitting or retrying more work.
    if failed:
        last = {**last, 'status': 'blocked', 'requests': [],
                'reason': admission_error or 'A request requires main-agent attention; no further admissions'}
    return {**last, 'results': results, 'rolling': {
        'admission_ticks': admissions, 'worker_limit': workers,
        'requests_executed': len(results), 'whole_batch_barrier': False,
        'budget_exhausted': budget, 'stopped_on_failure': failed,
        'drained_issued_requests': True,
    }}
