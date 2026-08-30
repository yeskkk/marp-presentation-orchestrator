# Worker thread lifecycle

Assignments are logical jobs; threads are scarce handles. The owning coordinator inventories the complete thread tree before spawning, reuses compatible idle handles, preserves reserve capacity, and records every handle in `THREAD-REGISTRY.yaml`.

Lifecycle states are `active`, `idle_reusable`, `terminal_not_releasable`, and `closed`. A retaining interrupt is not closure. A worker that authored any part of a presentation may never review that presentation. The five review channels use five distinct handles. Reuse requires a new planner-written exact assignment and a prompt declaring prior job content out of scope.

After handoff validation, the coordinator attempts a genuine runtime close/remove operation. If the runtime cannot release capacity, the handle becomes `idle_reusable`. Checkpoints record assignment, state, independence restrictions, handoff validation, close attempt and permitted reuse.
