# Migration from v0.6.6 to v0.6.7

No one-shot task migration is required. Existing assignment and workspace files remain valid and are preserved on the first v0.6.7 retry.

## Assignment contracts

A complete existing contract is reused. A pending interrupted scaffold may have only its missing files filled after identity and request semantics are checked. An `approved` or `revoked` decision with any missing taskbook/request/brief/decision file fails closed; restore the original file rather than regenerating planner content.

Exact approval retries are no-ops:

```bash
mpres assignment approve <slug> <assignment-path>   --planner-actor delegated-planner:example   --notes "same notes as the first approval"
```

To revise an approved contract:

```bash
mpres assignment revoke <slug> <assignment-path> --reason "..."
# planner edits the taskbook/brief
mpres assignment approve <slug> <assignment-path> --planner-actor delegated-planner:example
```

Batch plans use the parallel lifecycle:

```bash
mpres assignment batch-revoke <slug> --reason "..."
mpres assignment batch-approve <slug> --planner-actor delegated-planner:example
```

`BATCH-ASSIGNMENT-EXPANSIONS.yaml` is created on demand. It is operational materialization history; `BATCH-ASSIGNMENT-PLAN.yaml` remains the approved semantic source.

## Workspace retries

Re-running author, unit, review, revision, maintenance, diagnostic, or control-job preparation creates missing generated files only. Existing worker drafts, stage state, frozen source/evidence, assignment approvals, and original job timestamps are never reset.

v0.6.7 adds no hash and does not alter `TASK-RUNTIME-PROFILE.yaml` or any runtime-selection rule.
