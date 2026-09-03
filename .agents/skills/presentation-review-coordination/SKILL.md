---
name: presentation-review-coordination
description: After freeze, run five isolated full-deck reviewers, aggregate their receipts mechanically, and route every finding to one deck revision author.
---

# Mechanical review coordination

There is exactly one review round, `full`. Five distinct specialist reviewers are created only after the complete deck is frozen, one per channel, and every reviewer reads the entire frozen deck. There is no review-coordinator model, assignment, agent configuration, or thread.

Each reviewer sees the frozen request, confirmed task, exact channel assignment, and relevant extracted-text references, but no other channel findings and no later revision. Before aggregation, a channel may resubmit only location/evidence/note corrections that preserve finding identity and substance.

The Python control plane validates all five current handoffs. If any receipt, schema, ID namespace, channel, or location fails, aggregation aborts. Otherwise it generates the aggregate report deterministically, writes the registry, generates `REVISION-ROUTING.yaml`, and creates one deck revision author. Every route targets that author; original lesson authors remain closed. The control job records `model_runtime: null` and a durable receipt.

There is no second reviewer round and no finding-resolution lifecycle. Release depends on complete author responses, the deck revision checklist, and deterministic gates.

## v0.6.4 concurrent submission state

The five isolated reviewer submissions may complete concurrently. Each submission updates task state inside the shared task transaction, so every channel receipt is preserved. Reviewers and agents must not edit `state/task.json` directly.
