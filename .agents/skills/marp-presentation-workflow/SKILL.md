---
name: marp-presentation-workflow
description: Select a production profile, execute planner-owned batch assignments on the critical path, run one five-channel full-deck review, and mechanically release Marp PDF artifacts.
---

# Marp presentation workflow

At task start, explain the non-negotiable defaults: one mandatory five-channel review in which every reviewer reads the entire frozen deck; no reviewer recheck after revision; no screenshots, PDF rasterization, model vision, or worker access to original reference PDFs; a user-edited task runtime profile whose defaults are planner `gpt-5.6-sol/high`, author `gpt-5.6-sol/medium`, and reviewer `gpt-5.6-sol/low`; 2–3 diagnostic MCQs per course lesson; PDF-only delivery; and pilot/each/all delivery modes.

Create `TASK-RUNTIME-PROFILE.yaml` with the task. The user may refine it before confirmation. Store the normalized profile in canonical task state at confirmation and reject every later change. An agent may resolve a configured entry but may not choose, escalate, downgrade, substitute, or retry with another model or reasoning effort.

## Planner ownership and delegation

Only the main agent may write or revise top-level `TASK.md`. Every other planner operation may be delegated to another planner, including production profiling, writing and approving `BATCH-ASSIGNMENT-PLAN.yaml`, reviewer and revision-author assignments, policy audit, supervision, exception decisions, and incident triage.

A lesson assignment expanded mechanically from an approved batch plan counts as planner-written. Planner semantic ownership is preserved; the program may expand paths and inherited fields but may not invent scope, constraints, sources, decision rights, or acceptance criteria.

Review aggregation and release are Python control-plane jobs. They have no model assignment, no Codex agent configuration, no runtime profile entry, and no thread handle.

## Production order

1. Present and confirm both `TASK.md` and the exact task runtime profile.
2. Initialize the exact token collector and pass the exact-pinned toolchain smoke test.
3. Initialize presentations without materializing future lesson workspaces.
4. Have a planner approve one semantic batch plan.
5. Queue units only on the current critical path; keep one fixed author per lesson.
6. Integrate completed lesson handoffs, run deterministic author gates, compile `AUTHOR-CONTEXT-PACKET.yaml`, and freeze the complete deck.
7. Only after freeze, create five isolated full-deck reviewers and register the mechanical review-aggregation job.
8. After all five receipts validate, mechanically generate the aggregate and hand every finding to one deck revision author; do not reopen lesson authors.
9. After the revision passes deterministic gates, register the mechanical release job, render, inspect, package, and publish.

Priority is always: finish current review/revision/release; finish the current deck; start a ready next deck; prepare future metadata without model workers. Never create speculative reviewers, revision authors, or release jobs, and never hold model threads speculatively.

A suspected workflow-engine bug is not an in-task hotfix opportunity. Record `ENGINE-INCIDENT.yaml`, propose a task policy amendment, revise and reconfirm `TASK.md`, and treat engine refactoring as separate work.

## v0.6.4 mutable-state gate

Task state and thread lifecycle are canonical SQLite documents. Use control-plane commands, not direct projection edits. Before production, `mpres task transaction-status <slug>` and the policy audit must show both documents, current projections, and `sqlite-begin-immediate` writer serialization. A stale snapshot is a conflict requiring a full command retry against current state, never a force-write.

## v0.6.5 deterministic incident circuit

Use `mpres engine status` to monitor automatic recurrence counts. A repeated deterministic engine
incident blocks production until an exact user-preapproved workaround is applied and verified.
Never change an incident ID to evade recurrence counting.
