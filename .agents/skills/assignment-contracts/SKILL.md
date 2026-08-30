---
name: assignment-contracts
description: Preserve planner ownership of every exact worker assignment through request records, manual planner writing, and explicit planner approval.
---

# Assignment contracts

Coordinators may state that a new job is needed and provide structured evidence in `ASSIGNMENT-REQUEST.yaml`. They must not write, complete, infer, or weaken the worker assignment. The main planner personally edits the exact Markdown taskbook, removes all placeholders, and runs `mpres assignment approve`.

An assignment is runnable only when:

- its request identifies the role and coordinates;
- the Markdown taskbook contains the exact planner-written scope, hard constraints, replaceable hypotheses, local decision rights, references, outputs and acceptance tests;
- `ASSIGNMENT-DECISION.yaml` records `status: approved` and `written_by: planner`.

Approval records planner authorship; it is not approval of future worker output.
