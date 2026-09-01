---
name: context-packet-compilation
description: Compile compact durable lesson and deck context from canonical records so completed authors can close safely.
---

# Context packet compilation

A unit context packet contains only the exact assignment provenance, approved text sources, legacy ranges, course registry links, invariants, delta, risks, and forbidden context needed by that fixed lesson author.

At integration, compile `AUTHOR-CONTEXT-PACKET.yaml` from the accepted integrated unit snapshots, batch-plan semantics, stage completion records, course registries, and continuity map. Do not point a later worker at live lesson-author scratch space.

After review aggregation, enrich the packet with the frozen source, `REVIEW-PLAN.yaml`, finding registry, finding IDs, and mechanical gates to rerun. This packet lets one deck revision author revise coherently while original lesson authors remain closed.
