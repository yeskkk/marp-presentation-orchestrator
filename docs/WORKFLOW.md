# Workflow and state machine — v0.6.1

## v0.6.1 pre-production runtime and telemetry gate

Task initialization creates `TASK-RUNTIME-PROFILE.yaml`. The user may edit its planner, author, reviewer, role, channel, and presentation entries before confirmation. `task present` records the normalized profile shown to the user; `task confirm` stores it in canonical task state. Any later difference fails the confirmation gate. Agents never alter runtime selection.

After confirmation, initialize the token collector before `production init`. Unknown counters remain null and never become synthetic zeros.

## 1. Control plane versus semantic work

v0.6.0 separates two kinds of work.

**The Python control plane** owns deterministic operations: state transitions, batch expansion, workspace creation, queue ordering, launch eligibility, schema validation, review routing, logging, rendering commands, and mechanical gates.

**Planners, authors, and reviewers** own semantic operations: task definition, production-profile selection, assignment meaning, teaching design, writing, mathematical judgment, specialist review, and exception decisions.

Routine control-plane work must not be implemented as repeated model calls.

## 2. Task confirmation and planner delegation

The main agent is the only actor allowed to write or revise top-level `tasks/<slug>/TASK.md`. The exact file is presented to the user and confirmed before production. A material policy change, including a confirmed workflow-engine technical bug that blocks the task, requires a policy amendment, revised `TASK.md`, presentation, and explicit reconfirmation.

Every other planner operation may be delegated to a planner worker. This includes production-profile selection, batch planning, assignment approval, policy audits, scheduling supervision, incident diagnosis, and amendment preparation. The planner role retains semantic accountability.

Only `TASK.md` receives a confirmation digest. No other artifact is hashed.

## 3. Production profiles

Task initialization records one immutable confirmed mode:

| Mode | Stage profile | Stages | Typical use |
|---|---|---|---|
| `greenfield_full` | `course_six` or full report profile | six course stages / full report stages | difficult new material |
| `greenfield_compact` | compact profile | four compact stages | ordinary new material |
| `legacy_migration` | `migration_three` | `m01_baseline_audit` → `m02_delta_design_patch` → `m03_integration_semantic_check` | mature existing deck |
| `targeted_revision` | `targeted_revision_two` | `r01_defect_scope` → `r02_patch_regression` | bounded changes |

Migration completely bypasses greenfield stages. It still uses one fixed lesson author per lesson.

## 4. Batch-plan assignment flow

```text
planner writes BATCH-ASSIGNMENT-PLAN.yaml
        ↓
planner approves the semantic batch
        ↓
program expands one unit assignment per queued unit
        ↓
assignment records written_by: planner-via-approved-batch
        ↓
lesson author starts one continuous thread
```

The approved batch supplies common and unit-specific scope, sources, hard constraints, replaceable hypotheses, local decision rights, and acceptance criteria. Programmatic expansion may substitute paths and stable policy text but may not invent semantics. No stage-specific assignment exists.

## 5. Lazy production and critical path

A task starts with presentation/unit metadata only. Unit workspaces do not exist until the unit is queued under an approved batch plan.

The scheduler maintains this priority:

1. finish current review/revision/release;
2. finish current presentation;
3. start the next ready presentation;
4. prepare future metadata without model workers.

The active window is one current presentation plus at most one next presentation in authoring. The independent next-authoring lane remains open while the current deck is in authoring, review, deck revision, or release-ready state, and it is refreshed automatically at those transitions. Only one presentation may be in review/revision/release. Reviewers are absent before freeze. The deck revision author is absent before aggregation. The runtime-free release job is absent before `release_ready`.

Representative state progression:

```text
uninitialized
  → assignment_ready
  → queued
  → running
  → handoff_ready
  → integrated
  → frozen
  → reviewing
  → revision_required
  → revising
  → release_ready
  → released
```

Not every field applies at both unit and presentation level, but directory creation must never be mistaken for active work.

## 6. Unit authoring

One fixed lesson-author thread executes the profile-selected sequence under one assignment. `mpres stage submit` validates the current durable artifact and activates the next stage. A stage may be reopened with a recorded reason without creating a new assignment or thread.

For migration:

1. **M01 baseline audit:** compare the mature source to task requirements and write the canonical `UNIT-DELTA.yaml`.
2. **M02 delta design and patch:** preserve qualified material and implement only required changes.
3. **M03 integration and semantic check:** verify continuity, learner entry, mathematics, timing, interactions, numbering, and Marp integration.

The lesson author writes `UNIT-CONTEXT-PACKET.yaml`, hands off, and may close. It does not wait for review.

## 7. Canonical records

The system avoids multiple editable descriptions of the same fact:

- `PRODUCTION-PROFILE.yaml`: selected mode and stage graph.
- `BATCH-ASSIGNMENT-PLAN.yaml`: planner-owned batch semantics.
- `PRESENTATION-WORK-PLAN.yaml`: critical-path status and launch window.
- `UNIT-DELTA.yaml`: legacy keep/modify/move/delete/add decisions.
- `UNIT-CONTEXT-PACKET.yaml`: bounded author context.
- `INTERACTION-RECORD.yaml`: sole editable interaction/MCQ record.
- `AUTHOR-CONTEXT-PACKET.yaml`: compiled deck-level revision context.
- `REVIEW-PLAN.yaml`: frozen full-deck review anchor.
- `REVISION-ROUTING.yaml`: deterministic finding locations, all routed to the deck revision author.
- `TOOLCHAIN-LOCK.yaml`: exact production tool versions.
- `ENGINE-INCIDENT.yaml`: technical defect and amendment requirement.
- `MILESTONE-CHECKPOINT.json`: sparse durable milestone state.

Legacy compatibility views and audit reports are generated from canonical records where required; they are not independently edited.

## 8. Integration and freeze

The author coordinator supervises only the current critical path, integrates lesson fragments, runs full author gates, compiles `AUTHOR-CONTEXT-PACKET.yaml`, and freezes one complete deck. Original lesson authors and the author coordinator may then close.

Freeze requires the exact Marp 4.5.0 toolchain and a passing startup smoke report. Authoring may use incremental checks, but freeze runs the complete source, asset, course consistency, density, mathematics, HTML layout, PDF structure, and PDF text-layer gates.

## 9. One full-deck review

After freeze, the control plane creates one `REVIEW-PLAN.yaml` and exactly five isolated reviewers:

- language;
- domain accuracy;
- layout/design;
- pedagogy;
- audience fit.

Every reviewer reads the entire frozen source/deck. There is no delta-only or sampling mode. Review assignments and workspaces are not prepared before freeze.

The Python control plane validates all five handoffs, generates the aggregate report, and commits the shared finding registry without a coordinator model. A failed channel or invalid schema leaves the old registry unchanged. Limited pre-aggregation resubmission may repair only location/evidence/note metadata.

## 10. Deck-level revision and release

Atomic aggregation creates one deck revision author, not five lesson-revision queues. It receives the frozen deck, all findings, review plan, author context packet, and deterministic unit/slide routing. Every finding targets this same author. Original lesson authors remain closed.

The deck revision author responds to every finding, edits the entire deck, runs deterministic gates, and records its handoff. Reviewers never inspect the revised deck. Once revision is complete, the system enters `release_ready` and registers the mechanical release job just in time.

The mechanical release job performs deterministic checks and packaging only, with `model_runtime: null`. It may not judge content or finding resolution.

## 11. Toolchain and inspection

`@marp-team/marp-cli` is pinned to `4.5.0`. `TOOLCHAIN-LOCK.yaml` and `mpres toolchain smoke` must agree before production. The smoke fixture checks:

- installed Marp version;
- supported Marp slide DOM;
- mathematics/fonts/images readiness;
- HTML slide count;
- PDF generation and page count;
- course numbering fields.

HTML inspection waits for explicit slide readiness rather than unbounded network idle. Unsupported or zero-slide DOM fails quickly. Rendering timeout scales with deck size. Temporary HTML is always disposable.

## 12. Engine incidents

A suspected engine failure is diagnosed without editing the engine. When confirmed:

```text
ENGINE-INCIDENT.yaml
        ↓
workflow_engine_technical_fix policy amendment
        ↓
main agent revises TASK.md
        ↓
user reconfirms
        ↓
current task follows the reconfirmed policy
```

Actual engine refactoring and regression-test implementation are separate work. There is no in-task hotfix lane.

## 13. Logging and supervision

One daemon serializes all records into `logs/project.jsonl`. The control plane records routine transitions automatically. Models log semantic decisions, blockers, handoffs, amendments, and deliveries. Token counters are collected exactly at milestones; periodic model polling is forbidden.

Planner fallback supervision is every twenty minutes or a delivery event, but event-driven state changes should normally make polling unnecessary.

## 14. Delivery modes

- `pilot`: complete and deliver the first deck, then pause once.
- `each`: pause after every deck.
- `all`: complete all decks before pausing.

Delivery mode affects user pauses, not scheduling discipline or speculative worker creation.

## v0.6.2 mechanical control jobs

Review aggregation and release are explicit Python control-plane jobs with `model_runtime: null`. The repository contains neither coordinator agent configuration nor coordinator assignment template. Specialist reviewers and the deck revision author remain model roles governed by the confirmed task runtime profile.
