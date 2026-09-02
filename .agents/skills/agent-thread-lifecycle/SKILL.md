---
name: agent-thread-lifecycle
description: Allocate role-compatible handles just in time, preserve reviewer independence, close lesson authors after handoff, and forbid speculative hold threads.
---

# Thread lifecycle

Resolve each handle's model and reasoning effort from the confirmed task-local `TASK-RUNTIME-PROFILE.yaml`. Project configuration and agent TOML files do not select runtimes. Channel- or presentation-specific refinements are valid only when the user wrote them before confirmation; thread registration and assignment must match them exactly.

Use `THREAD-REGISTRY.yaml` and deterministic capacity preflight. Reuse a compatible `idle_reusable` handle before spawning, keep one active assignment per handle, and preserve the configured unallocated capacity.

Create model workers only when their gate opens:

- lesson author after an approved batch plan is queued for that unit;
- reviewers only after full-deck freeze;
- deck revision author only after atomic review aggregation;
- release coordinator only in `release_ready`.

One handle that authored any part of a deck may not review it. The five review channels require five distinct independent handles. A lesson author may close immediately after durable handoff and is not retained for later findings. Post-review revision uses one separate deck revision author and the compiled context packet.

After handoff, attempt a real runtime close/remove. If capacity remains allocated, record `idle_reusable`; an interrupt that retains the handle is not closure. Never create prospective release holds or speculative pre-freeze reviewer threads.
