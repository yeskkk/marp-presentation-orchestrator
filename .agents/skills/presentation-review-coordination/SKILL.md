---
name: presentation-review-coordination
description: After freeze, run five isolated full-deck reviewers, aggregate atomically, and route every finding to one deck revision author.
---

# Review coordination

There is exactly one review round, `full`. The review coordinator and all reviewer assignments are created only after the complete deck is frozen. Five distinct reviewers run in parallel, one per channel, and every reviewer must read the entire frozen deck.

Each reviewer sees the frozen request, confirmed task, exact channel assignment, and relevant extracted-text references, but no other channel findings and no later revision. Before aggregation, a channel may resubmit only location/evidence/note corrections that preserve finding identity and substance.

Validate all five current handoffs before changing shared state. If any receipt, schema, ID namespace, channel, or location fails, abort without a partial commit. Then write the registry once, generate `REVISION-ROUTING.yaml`, and create one deck revision author. Every route targets that author; original lesson authors remain closed.

There is no second reviewer round and no finding-resolution lifecycle. Release depends on complete author responses, the deck revision checklist, and deterministic gates.
