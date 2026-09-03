---
name: operational-incident-mitigation
description: Count repeated workflow-engine incidents, stop deterministic recurrence with a circuit breaker, and apply only an exact user-preapproved reversible workaround.
---

# Operational incident mitigation

Use the stable incident ID as the recurrence key; do not create another hash. Every occurrence
records presentation, operation, reproduction, evidence, and whether it is deterministic. Suspected
occurrences remain evidence but do not count toward the default threshold of two.

The first occurrence still creates a `workflow_engine_technical_fix` policy amendment and an
`OPERATIONAL-WORKAROUND.yaml` draft. An agent may document evidence, but may not invent, select,
broaden, or edit workaround semantics after user confirmation.

The exact reversible plan must be presented with the revised TASK and explicitly reconfirmed by the
user. At the recurrence threshold, task production is circuit-broken. The control plane never runs
arbitrary workaround commands: an operator executes the exact approved steps and records a
substantive verification attestation before the circuit closes.
