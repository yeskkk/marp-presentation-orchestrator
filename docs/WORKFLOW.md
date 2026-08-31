# Workflow and state machine — v0.5.0

## 1. Confirmed task

Planner completes and presents the single top-level `TASK.md`; explicit user confirmation binds that text. Only TASK.md uses a confirmation digest. Material policy changes require editing and reconfirming TASK.md.

## 2. Runtime policy

`MODEL-POLICY.yaml` is the sole source of truth:

```text
planner: gpt-5.6-sol / max
workers: gpt-5.6-sol / high
```

Thread registration records actual runtime values and refuses mismatches. Capacity preflight preserves the configured unallocated reserve.

## 3. Assignment ownership and deterministic launch planning

The planner personally writes every exact assignment and approval record. Coordinators may request an assignment but cannot fill its semantic brief. The CLI deterministically expands stable paths/rules and can generate current launch plans:

```text
mpres orchestration author-plan
mpres orchestration review-plan
```

A launch plan is current state only, not an attempt journal. It starts no agents and does not weaken planner ownership.

## 4. Parallel authoring with one thread per unit

Course content units are sequential numbered meetings; report units are logical parts. One planner-approved lesson assignment governs the whole content unit. The same lesson-author thread completes all internal stages:

```text
course: scope/sources → learner need → domain development → entry/diagnostics
        → learner language → Marp integration
report: task-selected compact profile
```

`mpres stage submit` validates the durable artifact/checkpoint and activates the next stage automatically. There are no stage-specific assignments, new spawns or coordinator acceptance gates between stages.

Lesson authors run in bounded parallel batches. Author coordinator integrates their handoffs and reconciles course terminology, semantic objects, continuity, examples, interactions and assets.

## 5. Course organization, time and interactions

Course decks are organized by `第 N 节课`, not textbook chapter boundaries. The nominal class duration defines a natural core stopping point. About 1.5× prepared material is advisory: a 40-minute lesson may include 40 minutes of core path followed by roughly 20 minutes of optional worked examples.

Each course unit has 2–3 diagnostic MCQ prompt/answer pairs; academic reports are exempt. MCQ audit checks information state, fresh inference, decision unit, prerequisites, cue leakage, composite options, labels, justifications and misconceptions.

## 6. Author mechanical gate

Before the sole review and again before release:

1. source and asset lint;
2. course terminology/object/continuity validation;
3. principal-teaching-move density audit;
4. math source inventory;
5. disposable Marp HTML renderer probe;
6. disposable HTML overflow/out-of-bounds inspection;
7. Marp PDF generation;
8. general PDF geometry/text/font/clipping inspection.

Temporary HTML is generated in a temporary directory, inspected with Playwright, and deleted. It is never durable output or reviewer evidence. Mechanical failure blocks review submission.

There is no `MATH-PDF-EVIDENCE`. Source/HTML math inspection is mechanical and cannot establish mathematical truth.

## 7. One full review

```text
authoring → review_requested → reviewing → author_revision → release_ready → finalized
```

Five isolated channels review the complete frozen deck: language, domain accuracy, layout/design, pedagogy and audience. Layout/design does not rerun mechanical overflow.

A reviewer may resubmit before aggregation only to correct location, evidence path or reviewer note. The coordinator validates all five current handoffs before any shared-state mutation; if one fails, no partial registry commit occurs. Successful aggregation atomically writes findings and generates finding-to-unit routing from the frozen manifest.

The author responds to every finding, performs routed revisions and reruns every deterministic gate. No reviewer checks the revision. Findings remain historical statements without resolved status.

## 8. Project log daemon

One persistent Python daemon serializes all log requests and is the sole writer of:

```text
tasks/<slug>/logs/project.jsonl
```

Callers do not open role-specific log files and do not handle locks. Log records include UTC, role, presentation/unit/round/channel coordinates, message and daemon sequence. Startup scripts start the daemon before Codex. `mpres log tail` filters the single file at read time.

The framework intentionally has no crash-recovery orchestration subsystem. After a crash, planner inspects state, the project log, thread registry, checkpoints and handoffs and decides how to continue.

## 9. Thread lifecycle

Thread registry records actual runtime, current assignment, authorship/reviewer independence, handoff and close/reuse outcome. Same lesson thread remains attached across authoring stages. Before a batch, capacity preflight accounts for all non-closed handles and preserves the configured reserve.

## 10. Course consistency

Course tasks maintain course terminology, semantic objects and cross-deck handoffs. Each deck declares local-to-course terminology mappings, object scope, incoming presentation and reactivated terms/objects. Mechanical validation blocks unknown references and missing bridges.

Language review remains contextual. For problematic learner-facing sentences it may record referent, intended proposition/action, discourse link, syntactic head, modifiers, ambiguity and recommended revision rather than relying on a forbidden-word list.

## 11. Corrective maintenance

A finalized deck may enter targeted patch or full corrective review. Historical releases remain unchanged. Full review maintenance uses the same one-review/no-recheck policy. Successful maintenance publishes a numbered revision and updates `CURRENT-REVISION.json`.

## 12. Deliberate exclusions

No crash recovery subsystem; no workflow-engine freeze; no MATH-PDF evidence; no token-attempt linkage; no persistent HTML; no original-PDF worker access; no screenshot/model vision; no non-TASK hashes; no reviewer recheck after author revision.
