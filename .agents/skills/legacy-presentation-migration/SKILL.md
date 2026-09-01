---
name: legacy-presentation-migration
description: Migrate a mature Marp deck by auditing a baseline, making explicit deltas, and integrating semantically without rerunning greenfield discovery.
---

# Legacy migration

Use one fixed author per lesson and exactly three stages:

1. `m01_baseline_audit`: establish the trusted baseline and classify slide ranges as keep, modify, move, delete, or add; identify numbering, interaction, continuity, core/support, and toolchain risks.
2. `m02_delta_design_patch`: change only the approved deltas, preserving strong legacy explanations and examples.
3. `m03_integration_semantic_check`: reconcile the lesson with deck/course terminology, objects, timing, interactions, and Marp constraints; produce the durable handoff.

`UNIT-DELTA.yaml` is the canonical migration record. Continuous unchanged ranges may be recorded compactly; do not duplicate the same legacy decision in multiple prose artifacts. The six greenfield stages are forbidden for this profile.
