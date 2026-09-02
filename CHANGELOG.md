# Changelog

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
