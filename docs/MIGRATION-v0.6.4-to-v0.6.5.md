# Migration from v0.6.4 to v0.6.5

v0.6.5 changes only workflow-engine incident recurrence and operational mitigation. Existing
incident YAML files import as one deterministic occurrence on first status/record access. No manual
database migration and no additional hash are required.

The first incident creates the existing policy amendment and a workaround draft. Fill the exact
reversible plan, set status to `proposed`, revise/present/reconfirm TASK, confirm the amendment, and
run `engine workaround-approve`. Further deterministic occurrences under the same ID increment
automatically; the default second occurrence blocks normal production. An operator executes and
verifies the approved plan, then records the attestation with `engine workaround-apply`.

Slide-subset diagnostics, assignment idempotency, and canonical YAML handoff hardening remain later
milestones.
