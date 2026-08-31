# Design notes — v0.5.0

## Main changes from v0.4.1

- Replaced per-role JSONL logs with a persistent project-level logging daemon and one append-only task log.
- Unified each lesson's authoring stages under one planner-approved assignment and one continuous lesson-author thread.
- Added deterministic current author/review launch plans without an orchestration journal.
- Added thread runtime verification and reserved-capacity preflight.
- Added atomic five-channel aggregation and narrowly constrained pre-aggregation resubmission.
- Added mechanical finding routing back to original lesson units or coordinator reconciliation.
- Added course-level terminology, semantic-object and cross-deck continuity validation.
- Added principal-teaching-move density audit.
- Added source and disposable-HTML mathematics inspection; deliberately omitted PDF-math evidence.
- Added numbered targeted/full-review corrective maintenance without overwriting historical releases.
- Added contextual language finding templates.

## Why one log daemon

Many agents may report progress concurrently, but they should not know about filesystem locking or write coordination. A long-running Python daemon receives requests, serializes them through its own queue and writes one `project.jsonl`. Startup coordination and socket details remain hidden under `.mpres/` and are implementation details, not part of the worker protocol.

## Why internal stages, not stage workers

The six-stage method improves author attention, but repeated assignment approval and respawn add cost without improving semantics. A whole lesson now has one planner-owned contract; stage artifacts/checkpoints preserve structure while the same thread continues.

## Why source + HTML math checks only

Source lint catches delimiter/environment/command errors. Disposable HTML reveals renderer failures and raw-marker leakage. A separate PDF-math evidence layer would add cost while still not proving mathematical correctness; general PDF structural inspection and domain review are sufficient boundaries.

## Why no crash-recovery subsystem

The user explicitly rejected a heavier recovery design. v0.5.0 preserves durable state, one project log, checkpoints, handoffs and thread registry, but recovery decisions remain planner work rather than a new workflow/skill/template system.

## Why no workflow freeze

The project does not implement engine-generation locks or migration transactions. Material policy changes still require TASK reconfirmation; ordinary source-code maintenance relies on normal testing and careful task supervision.

## Why token accounting remains limited

Exact counters can still be imported and reported. v0.5.0 does not add orchestration-attempt attribution or budget automation.
