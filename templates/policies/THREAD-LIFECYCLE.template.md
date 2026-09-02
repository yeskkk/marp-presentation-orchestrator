# Worker thread lifecycle

Assignments are logical jobs; runtime threads are scarce handles. Before spawning, inspect `THREAD-REGISTRY.yaml`, reuse a compatible `idle_reusable` handle when safe, and preserve the configured reserve. One handle has at most one active assignment.

Lifecycle states are `active`, `idle_reusable`, `terminal_not_releasable`, and `closed`. A retaining interrupt is not closure. A worker that authored or revised any part of a deck may never review that deck. The five review channels require five distinct handles.

One fixed lesson-author handle completes the entire profile-selected stage sequence. After its durable handoff is validated, it may close or become reusable; it is not retained for review-time edits. The author coordinator may also close after freeze. One separate deck-revision-author handles all post-review changes from `AUTHOR-CONTEXT-PACKET.yaml`.

Reviewers are created only after freeze. The release job is a Python control-plane operation registered only at `release_ready`; it is not a thread. Prospective hold threads and speculative future-deck workers are forbidden. Reuse requires a new planner-approved assignment and an explicit prompt declaring prior job content out of scope.
