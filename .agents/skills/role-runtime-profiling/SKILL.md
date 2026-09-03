---
name: role-runtime-profiling
description: Create and validate the user-authored, task-level model and reasoning profile without dynamic agent selection.
---

# Role runtime profiling

Create `tasks/<slug>/TASK-RUNTIME-PROFILE.yaml` when the task is initialized. The user is the only authority for its model and reasoning choices. Defaults are:

- planner: `gpt-5.6-sol/high`
- author: `gpt-5.6-sol/medium`
- reviewer: `gpt-5.6-sol/low`

The user may refine exact roles, reviewer channels, or presentations before task confirmation. `mpres task present` records the normalized profile shown for approval. `mpres task confirm` stores the complete normalized profile in canonical task state; no additional hash is created. Every later gate compares the current file with that snapshot and fails closed on any difference.

Agents never infer runtime from difficulty, confidence, retry count, or budget. They do not escalate, downgrade, substitute, or rewrite model/reasoning settings during a task. Assignment and thread code only resolves the exact preconfirmed entry and verifies the actual runtime against it.

## v0.6.6 diagnostic reviewer

`diagnostic-reviewer` belongs to the reviewer family. The user may configure a more specific role override before task confirmation; otherwise it receives the reviewer default. A low-confidence diagnosis requests a new evidence scope rather than changing model or reasoning effort.
