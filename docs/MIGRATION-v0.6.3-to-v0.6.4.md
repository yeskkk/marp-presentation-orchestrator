# Migration from v0.6.3 to v0.6.4

v0.6.4 changes only shared mutable-state persistence. Runtime policy, mechanical review/release jobs, and current-plus-next scheduling remain unchanged.

## Existing tasks

No manual conversion command is required. On the first v0.6.4 read of an existing task:

1. `state/task.json` is imported as canonical document `task-state`;
2. `THREAD-REGISTRY.yaml` is imported as canonical document `thread-registry`;
3. absent `state_revision` and `registry_revision` fields default to zero;
4. `state/mutable-state.sqlite3` is created; and
5. both projections are rewritten in normalized form.

After import, keep the SQLite file. JSON/YAML files are projections and manual edits are overwritten by canonical state.

## New tasks

`mpres task init` initializes both documents in the transaction store and emits the familiar projections. All public state-mutating and thread-lifecycle commands run under one task-local, reentrant writer transaction.

## Operator checks

```bash
mpres task transaction-status <slug>
mpres policy audit <slug>
```

A stale direct snapshot raises `ConcurrentStateUpdateError`. Reload current state and rerun the complete operation; do not force-write or delete the database.

## Deliberately unchanged

- no new hash is generated;
- only top-level `TASK.md` keeps its confirmation digest;
- runtime selection remains fixed by the user before confirmation;
- review aggregation and release remain mechanical jobs;
- current-plus-next scheduling remains the v0.6.3 behavior;
- incident circuit breakers and slide-subset diagnostics are not part of v0.6.4.
