# Changelog

## 0.8.3

- Five independent full review skills, same specialist-reviewer agent and fixed runtime family.
- General teaching principles and role methods replace task-specific examples.
- Maintenance/calibration fixtures are outside runtime guidance.
- Audience receives its complete method first, then bounded step and synthesis instructions.
- No skill lint, extra model role, repair-verification review or database schema change.


## 0.8.2

- Determine amend/plan/resume intent before work; do not force automatic continuation.
- Supply confirmed TASK once per actual session in the existing semantic request.
- Reuse session context across jobs/retries/audience chunks; authorized edits are deltas.
- Keep the existing agent definitions and all runtime/approval boundaries.


## 0.7.0

- First v0.7.x milestone: project-owned, offline Gaia/lead-style default based on
  the user's 1-1.md styling. Preserve the requested typography and utility palette.
- Add explicit table borders/padding and a fixed heading/image/caption box model;
  do not position MathJax SVGs or auto-shrink overfull slides.
- Source policy 4 invalidates old theme gate passes without rewriting artifacts.
- Fix the toolchain specimen's quoted 16:9 value and test it against the real source contract.
- Add a five-page regression specimen, native verification command and ten tests.
- No changes to model selection, database schema, review count or old user tasks.


## 0.6.9

Mechanical semantic-job runner with observed host inventory, persistent pool admission, fixed runtime execution receipts, bounded packets, no blind external retries, and JSON-stdio/bridge adapters. Full deck release pipeline remains disabled pending gate migration.

## 0.6.8

Compact relational task/config/job/attempt storage, fixed runtime binding, immutable content revisions, token null handling and read-only legacy import. New default CLI; no duplicate writable state for compact tasks. Automated runner remains the next stage.


## 0.6.7

- Added create-if-absent assignment taskbooks and structured contract scaffolds; retries preserve existing planner and worker bytes.
- Made exact repeated approval a no-op and required explicit assignment or batch-plan revocation before revision and reapproval.
- Preserved first approval metadata and introduced monotonic approval sequences.
- Separated operational batch expansion history from the approved semantic batch plan.
- Made author, lesson, reviewer, revision, maintenance, diagnostic, and mechanical control-job workspace preparation repair missing generated files without resetting existing work.
- Added the idempotent-assignment-lifecycle skill, schema-v4 assignment templates, migration guidance, CLI support, and focused concurrency/recovery tests.

Not included yet: canonical YAML handoff strengthening or broader reference-plus-delta context compaction.

## 0.6.6

- Added a bounded, read-only diagnostic path for user-reported slide IDs or page numbers.
- Added target-plus-neighbor evidence packets with selected structured records and filtered existing gate evidence; PDFs are never opened, rendered, copied, or shown to a model.
- Added the fixed-runtime `diagnostic-reviewer` role, planner-approved assignment, validated diagnostic result, and advisory patch-scope record.
- Added `mpres diagnostic open|submit|status`, a dedicated skill/agent/templates, migration guidance, logging support, token attribution, and focused regression tests.
- Kept source edits and scope expansion outside the diagnostic worker; later patches still require planner authorization and full-deck gates.

Not included yet: assignment idempotency or canonical YAML handoff hardening.

## 0.6.5

- Added stable-ID occurrence counting and a deterministic recurrence circuit breaker.
- Added exact TASK-confirmed operational workaround approval and operator-verified application.
- Added incident status/index views, policy/audit checks, CLI commands, skills, templates, migration guidance, and focused tests.

Not included yet in v0.6.5: slide-subset diagnostics, assignment idempotency, or canonical YAML handoff hardening.


## 0.6.4

- Added a task-local SQLite transaction store for canonical task state and the thread registry; JSON/YAML files remain human-readable projections.
- Serialized all public task-state and thread-lifecycle mutations with reentrant `BEGIN IMMEDIATE` task transactions, preventing read-modify-write lost updates.
- Added optimistic revision checks so stale direct snapshots fail explicitly instead of overwriting newer state.
- Added post-commit, revision-checked projection repair and automatic first-read import for existing v0.6.3 tasks.
- Added `mpres task transaction-status`, mutable-state audit checks, and concurrency/rollback/migration/full-review regression tests.

## 0.6.3

- Repaired the bounded current-plus-next pipeline: a current deck in review, deck revision, or release-ready state no longer closes the next authoring lane.
- Added automatic window refresh at review/revision/release transitions, including lazy materialization of exactly one next author-coordinator workspace in `all` mode.
- Kept `each`, the initial `pilot` pause, and zero next-WIP policies fail-closed.
- Unified automatic rebalancing and explicit activation on one status predicate and exposed overlap state in the work-plan and critical-path projection.
- Added focused scheduler and freeze-transition regression tests.

## 0.6.2

- Removed the model-based `review-coordinator` and `release-coordinator` roles, Codex agent configurations, assignment templates, checkpoint paths, and runtime mappings.
- Added runtime-free Python review-aggregation and release jobs under each task's `control-plane/` directory.
- Made the full-review aggregate deterministic from five validated reviewer receipts and recorded mechanical job receipts.
- Moved release rendering and packaging to the mechanical release workspace and removed planner approval from mechanical operations.
- Updated audit, supervision, policies, templates, skills, documentation, and end-to-end tests for the mechanical control plane.
- Ensured frozen review source becomes writable only in the deck revision author's copied workspace.

## 0.6.1

This is the first independently testable step toward v0.7.0.

- Added user-authored task-level `TASK-RUNTIME-PROFILE.yaml`.
- Set template defaults to planner `gpt-5.6-sol/high`, author `gpt-5.6-sol/medium`, reviewer `gpt-5.6-sol/low`.
- Added deterministic role, channel, and presentation overrides, all editable only before confirmation.
- Stored the complete confirmed runtime profile in canonical task state without adding another hash.
- Removed concrete runtime selection from project Codex and agent TOML configuration.
- Made token collector initialization a production start gate.
- Preserved unknown token counters as null and added known subtotals, unknown counts, and coverage.
- Added the `role-runtime-profiling` skill and regression tests.

Not included yet: mechanical review/release coordinators, scheduler overlap repair, transactional mutable state, incident circuit breakers, or slide-subset diagnostics.

## 0.6.18

Computed lines, projections and transformations; exact relationships, reproducible SVG/Python assets, source-contract enforcement, CLI and examples. No new semantic reviewer or runtime changes.

## 0.6.19

Sequential bounded audience reading on one session, exact coverage/evidence receipts, SQLite schema 7, recovery-safe stage delivery, first-review only.

## 0.6.20

Bounded typed local-checker recovery, safe host observations, precise completed-author-result correction, pilot/repair scope capacity, exact blocked-check resumption. No runtime mutation, gate relaxation or post-repair reviewer.
