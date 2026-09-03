# Design notes — v0.6.5


## Why v0.6.1 is incremental

v0.6.1 changed only runtime selection and token observability. v0.6.2 removed model-based review/release coordinators, v0.6.3 repaired the bounded current-plus-next scheduler, and v0.6.4 makes task state and the thread registry transactional. v0.6.5 adds incident recurrence and circuit breaking; slide-subset diagnostics remain reserved for a later independently testable milestone.

## Why v0.6.0 exists

A mature linear-algebra course migration exposed a control-plane bottleneck: after more than seven hours, useful lesson writing had progressed far less than expected while thousands of model calls repeatedly produced assignments, checkpoints, speculative reviewer material, status supervision, and duplicate evidence. Some ready lesson work waited for hours because future-task preparation occupied capacity. Tool-version drift and a numbering-validator defect then blocked an almost-finished deck.

v0.6.0 treats those observations as workflow-design failures rather than a reason to reduce author/reviewer reasoning quality.

## Production profiles instead of one universal pipeline

The six-stage course method remains valuable for difficult greenfield creation, but it is wasteful when a mature deck already supplies structure, examples, language, and continuity. Production profiles select the smallest semantically adequate stage graph. Legacy migration therefore has exactly three stages and preserves qualified material through a canonical delta record.

The user explicitly retained one fixed author per lesson in migration. Deck-level continuity is recovered at integration and in the later deck revision author, not by replacing lesson ownership with one migration author.

## Planner authorship without repetitive prose

The key invariant is that a planner chooses assignment semantics, not that the main agent manually repeats the same global policy dozens of times. A planner-approved batch plan is therefore the authoritative semantic act; deterministic unit expansion counts as planner-written. Only top-level `TASK.md` is exclusive to the main agent. All other planner work may be delegated.

This preserves responsibility while removing model-generated control-plane repetition.

## Critical path rather than speculative concurrency

Higher concurrency does not improve throughput when reviewer assignments, release roles, and distant presentations are created before they can run. v0.6.0 uses one current presentation and at most one next authoring presentation. Reviewer, revision, and release roles are just-in-time. Lazy unit initialization keeps directory existence and actual execution state distinct.

The scheduler favors completing deliverables over preparing distant work.

## Why lesson authors close before review

Keeping every lesson author alive for possible findings consumes handles and encourages fragmented revision. Each author now produces a durable unit context packet and closes after handoff. After five full-deck reviews, one deck revision author sees every finding and the complete frozen source, so it can repair cross-lesson consistency rather than distribute changes back into isolated fragments.

## Why all five reviewers still read the whole deck

The user rejected risk-stratified or delta-only review. Each specialist therefore reads the complete frozen deck. The optimization is temporal and structural: reviewers launch only after freeze, share one frozen anchor, submit schema-validated reports, and never recheck the revision. Review quality is not traded for speed.

## Canonical records instead of evidence duplication

Prior versions repeated time plans, MCQ logic, legacy-reuse decisions, and constraints across stage artifacts, manifests, audits, and self-checks. v0.6.0 names a small set of editable canonical records and treats other reports as generated views. Context packets compile references to those records instead of copying entire task histories into each worker prompt.

## Why the engine cannot hot-fix itself

A workflow bug and a courseware task are different projects. Even a purely technical defect may change execution assumptions or distract the task from its confirmed purpose. The user therefore requires `ENGINE-INCIDENT.yaml`, a task policy amendment, revised/reconfirmed `TASK.md`, and separate engine-refactoring work. v0.6.0 deliberately has no in-task hotfix lane.

## Why the toolchain is pinned

The prior unpinned Marp installation changed its generated HTML DOM and invalidated the layout inspector. Exact Marp 4.5.0 pinning plus a three-slide startup smoke fixture turns tool compatibility into a precondition rather than a late production surprise. Explicit DOM readiness and size-aware timeouts prevent zero-slide errors from consuming long fixed waits.

## What remains intentionally unchanged

- Runtime selection is task-local and user-authored. Defaults are planner `gpt-5.6-sol/high`, author `gpt-5.6-sol/medium`, and reviewer `gpt-5.6-sol/low`; confirmed choices never change during production.
- Five review channels remain independent.
- Review aggregation is atomic.
- There is no reviewer recheck after author revision.
- Screenshots, model vision, original-PDF worker access, persistent HTML, and non-`TASK.md` hashes remain forbidden.
- One daemon remains the only project-log writer.
- Corrective releases never overwrite historical deliverables.


## v0.6.3 — why the active window follows the current deck

The current presentation remains the critical-path identity until it is finalized, but its authoring lane and the later deck's authoring lane are independent resources. Closing the latter merely because the former entered review serialized all decks. v0.6.3 therefore keeps the same bounded WIP—one current plus one next—but preserves the next authoring lane across review, revision, and release.

## v0.6.4 — why atomic file replacement was insufficient

Atomic replacement prevents readers from seeing a half-written JSON or YAML file, but it does not protect a read-modify-write sequence. Two processes can read revision N, make independent changes, and each atomically replace the whole file; the second replacement silently erases the first.

v0.6.4 therefore stores the two shared mutable documents—task state and the thread registry—in a task-local SQLite database. `BEGIN IMMEDIATE` provides one internal writer boundary across processes, while nested control-plane calls reuse the same transaction. Normal commands serialize their complete read/validate/update sequence. Direct callers also carry a revision and receive an explicit conflict when it is stale.

The familiar JSON/YAML files remain available as generated projections. They are written after commit, and a projection flush checks that its revision is still canonical before writing. If a projection is missing or stale, the next read repairs it from SQLite. A v0.6.3 task with no database is imported from its existing projections on first access.

This milestone deliberately does not make every artifact file transactional. It addresses the two registries that previously suffered concurrent lost updates. Review/release artifacts retain the v0.6.2 mechanical job behavior; incident recurrence, circuit breakers, assignment idempotency, and slide-subset diagnostics remain later milestones.

## v0.6.5 — incident recurrence

A write-once incident could not show the same deterministic failure across decks. The stable ID now
owns a transactional occurrence list; the second deterministic occurrence opens a production
circuit. Recovery is declarative: exact plan snapshot, user reconfirmation, operator execution, and
verification attestation.
