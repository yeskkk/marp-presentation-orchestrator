# Thread states

`active`, `idle_reusable`, `close_requested`, `closed`, `failed`, `unknown_runtime_state`.

A thread can be reused only when its independence tags and role capability match the new planner-owned assignment. A lesson assignment may have been expanded from an approved batch plan. One lesson-author handle remains stable across that lesson's profile-selected stages, then may close after durable handoff. Five reviewer handles are distinct and independent from every author of the deck. The post-review deck revision author is a separate handle and is created only after atomic aggregation. Reviewer, revision, release, and hold threads are never created speculatively.
