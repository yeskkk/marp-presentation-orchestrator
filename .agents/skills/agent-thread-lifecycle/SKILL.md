---
name: agent-thread-lifecycle
description: Maintain a bounded role-compatible thread registry, reuse idle handles, preserve reviewer independence, and record validated handoffs and real closure attempts.
---

# Thread lifecycle

Use `mpres thread` commands and `THREAD-REGISTRY.yaml`. Before spawning, inventory all known handles and reuse a compatible `idle_reusable` handle. One handle has at most one active assignment.

A handle that authored a presentation may not review it. Five review channels require five distinct active handles. After a validated handoff, attempt a genuine runtime close/remove operation. If capacity is not actually released, record `idle_reusable`; a retaining interrupt is not closure.
