# Execution and trust boundaries

The interactive launcher starts Codex with the user's approval and sandbox settings.
It never supplies a bypass flag, authenticates an account, installs dependencies,
or uses CLI text as proof of user authorization. `--cli` never starts a model.

Use a dedicated unprivileged account or container for untrusted author/tool code.
The database, path containment and read-only revisions are accident guards, not a
sandbox against another process running as their owner. Preserve host receipts;
a configured capability is not evidence of an executed action. Missing/uncertain
provider results must be reconciled before retry, not converted to success.

A selected task pins its main-planner runtime from confirmed settings; workers
must report matching model/effort in their own receipts. No automatic fallback.
Starting without a task is only a planning session using the user's host defaults.
No secrets, environment snapshots, sessions or credentials belong in source ZIPs.
