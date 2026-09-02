---
name: marp-presentation-workflow
description: Select a production profile, execute planner-owned batch assignments on the critical path, run one five-channel full-deck review, and release Marp PDF artifacts.
---

# Marp presentation workflow

At task start, explain the non-negotiable defaults: one mandatory five-channel review in which every reviewer reads the entire frozen deck; no reviewer recheck after revision; no screenshots, PDF rasterization, model vision, or worker access to original reference PDFs; a user-edited task runtime profile whose defaults are planner `gpt-5.6-sol/high`, author `gpt-5.6-sol/medium`, and reviewer `gpt-5.6-sol/low`; 2–3 diagnostic MCQs per course lesson; PDF-only delivery; and pilot/each/all delivery modes.

Create `TASK-RUNTIME-PROFILE.yaml` with the task. The user may refine it before confirmation. Store the normalized profile in canonical task state at confirmation and reject every later change. An agent may resolve a configured entry but may not choose, escalate, downgrade, substitute, or retry with another model or reasoning effort.

## Planner ownership and delegation

Only the main agent may write or revise top-level `TASK.md`. Every other planner operation may be delegated to another planner, including production profiling, writing and approving `BATCH-ASSIGNMENT-PLAN.yaml`, individual coordinator/reviewer/revision/release assignments, policy audit, supervision, exception decisions, and incident triage.

A lesson assignment expanded mechanically from an approved batch plan counts as planner-written. Planner semantic ownership is preserved; the program may expand paths and inherited fields but may not invent scope, constraints, sources, decision rights, or acceptance criteria.

## Production order

1. Present and confirm both `TASK.md` and the exact task runtime profile.
2. Initialize the exact token collector and pass the exact-pinned toolchain smoke test.
3. Initialize presentations without materializing future lesson workspaces.
4. Have a planner approve one semantic batch plan.
5. Queue units only on the current critical path; keep one fixed author per lesson.
6. Integrate completed lesson handoffs, run deterministic author gates, compile `AUTHOR-CONTEXT-PACKET.yaml`, and freeze the complete deck.
7. Only after freeze, create five isolated full-deck reviewers.
8. Aggregate atomically and hand every finding to one deck revision author; do not reopen lesson authors.
9. Only after the revision passes deterministic gates, create the release coordinator and publish.

Priority is always: finish current review/revision/release; finish the current deck; start a ready next deck; prepare future metadata without model workers. Never create speculative reviewer, revision, release, or hold threads.

A suspected workflow-engine bug is not an in-task hotfix opportunity. Record `ENGINE-INCIDENT.yaml`, propose a task policy amendment, revise and reconfirm `TASK.md`, and treat engine refactoring as separate work.
