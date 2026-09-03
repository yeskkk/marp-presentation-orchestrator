# Transactional Workflow State

## Purpose

Prevent concurrent control-plane commands from losing task-state or thread-registry updates while keeping the existing JSON/YAML files readable to operators.

## Canonical boundary

- Canonical mutable store: `tasks/<slug>/state/mutable-state.sqlite3`.
- Canonical documents: `task-state` and `thread-registry`.
- Human-readable projections: `state/task.json` and `THREAD-REGISTRY.yaml`.
- Internal writer serialization: SQLite `BEGIN IMMEDIATE`.
- No agent-visible lock file or manual lock protocol.

## Required behavior

1. Every public command that modifies task state or thread lifecycle runs in `transactional_task_mutation`.
2. Nested calls for the same task reuse the outer transaction; switching task roots or slugs inside it is forbidden.
3. Normal commands load, validate, and save within one transaction.
4. Direct snapshot saves use the embedded revision; stale revisions raise `ConcurrentStateUpdateError`.
5. Projections are written after commit and only when the queued revision is still current.
6. Missing or stale projections are repaired from the database.
7. A pre-v0.6.4 task is imported from its projections on first access.
8. Never delete or edit the SQLite database during a task. Never treat projections as independent editable truth.

## Acceptance checks

- parallel state increments preserve every increment;
- parallel thread registrations preserve every handle;
- five review-channel submissions preserve all channels;
- a forced exception rolls back canonical state and leaves projections unchanged;
- an old projection imports with revision zero;
- `mpres task transaction-status` reports both canonical documents and valid projections.
