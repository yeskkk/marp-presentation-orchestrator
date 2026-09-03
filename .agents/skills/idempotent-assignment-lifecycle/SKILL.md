---
name: idempotent-assignment-lifecycle
description: Recover assignment and worker workspaces without overwriting planner contracts, approvals, worker drafts, or canonical evidence.
---

# Idempotent assignment lifecycle

Use this skill whenever a control command creates, retries, resumes, or repairs an assignment or role workspace.

## Create-only scaffold

Assignment taskbooks, `ASSIGNMENT-REQUEST.yaml`, `ASSIGNMENT-BRIEF.yaml`, and `ASSIGNMENT-DECISION.yaml` use create-if-absent publication. A repeated scaffold preserves every existing byte. It may fill only files missing from an interrupted **unapproved** scaffold, after validating assignment identity and request semantics.

If a decision is already `approved` or `revoked`, any missing contract file is corruption. Fail closed; never reconstruct unknown planner-authored content. The decision file is created or updated last because it is the lifecycle commit marker.

## Approval and revision

Exact repeated approval by the same planner actor with the same notes is a no-op. Preserve the original approval time, first approver, taskbook, brief, request, and decision. A different actor or different approval metadata requires explicit revocation.

Approved contracts are API-immutable and best-effort filesystem read-only. To revise one, a planner must run the explicit revoke command with a reason. Reapproval increments `approval_sequence` while preserving `first_approved_utc`. There is no force-overwrite path.

## Batch assignments

The approved `BATCH-ASSIGNMENT-PLAN.yaml` is semantic input and must not be mutated by lesson workspace materialization. Record operational expansion in `BATCH-ASSIGNMENT-EXPANSIONS.yaml`. A batch plan may be revised only after explicit batch revocation and later reapproval.

## Workspace recovery

A repeated workspace preparation command may create missing generated files or directories only. It must preserve:

- approved or revoked assignment contracts;
- author and reviewer drafts;
- stage state and accepted artifacts;
- frozen review source and evidence;
- maintenance and diagnostic records;
- control-plane job creation timestamps.

Validate that an existing workspace belongs to the requested task, role, presentation, unit, round, or channel. Conflicting identity or semantics is an error, not a reason to replace files.

This lifecycle adds no hashes and never changes task runtime selection.
