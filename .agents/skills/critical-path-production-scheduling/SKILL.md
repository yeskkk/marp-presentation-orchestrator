---
name: critical-path-production-scheduling
description: Keep model work on the current delivery path with lazy unit materialization, bounded WIP, and just-in-time review/revision/release roles.
---

# Critical-path scheduling

Use `PRESENTATION-WORK-PLAN.yaml` as a projection of task state, not a second source of truth. Keep at most one current presentation plus one next authoring presentation active, and at most one presentation in review.

Priority order is fixed: finish current review/revision/release; finish current presentation; start the next ready presentation; prepare future metadata without model workers. Queue a unit only after the batch plan is approved and the presentation is active. Materialize its files only when queued.

Never pre-create reviewer, deck revision, or release workers. Alert when a ready unit exceeds the configured wait threshold and reclaim noncritical capacity rather than expanding speculative work.
