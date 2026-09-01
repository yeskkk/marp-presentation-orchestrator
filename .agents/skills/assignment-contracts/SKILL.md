---
name: assignment-contracts
description: Preserve planner semantic ownership through delegated planner approval, one batch authoring plan, and deterministic unit-assignment expansion.
---

# Assignment contracts

Only writing or revising top-level `TASK.md` is reserved to the main agent. A main or delegated planner may perform every other planner operation.

## Lesson author assignments

A planner writes and approves one `BATCH-ASSIGNMENT-PLAN.yaml` containing common constraints and exact per-unit scope, audience context, prior knowledge, decision rights, approved text sources, acceptance criteria, baseline/delta requirements, and risks. After approval, `mpres` may expand each unit into:

- `TASK-LESSON-AUTHOR.md`;
- `ASSIGNMENT-REQUEST.yaml`;
- `ASSIGNMENT-BRIEF.yaml` with `written_by: planner-via-approved-batch`;
- `ASSIGNMENT-DECISION.yaml` with planner semantic ownership and the batch-plan provenance.

This deterministic expansion counts as planner-written. It may not fill missing semantics or weaken the approved batch plan.

## Other roles

Coordinator, specialist-reviewer, deck-revision-author, release, and maintenance assignments are individually written and approved by a main or delegated planner. An assignment is runnable only when its Markdown taskbook is complete, its structured brief has no placeholders, and its decision records `status: approved` with planner semantic ownership.

Approval establishes assignment authorship, not acceptance of future worker output.
