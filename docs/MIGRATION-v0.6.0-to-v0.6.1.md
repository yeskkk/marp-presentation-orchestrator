# Migration from v0.6.0 to v0.6.1

v0.6.1 is deliberately limited to task-local runtime selection and trustworthy token accounting.

## Existing tasks

1. Copy `templates/policies/TASK-RUNTIME-PROFILE.template.yaml` to the task root as `TASK-RUNTIME-PROFILE.yaml`.
2. Edit the profile with the user before resuming production. Defaults are planner `gpt-5.6-sol/high`, author `gpt-5.6-sol/medium`, reviewer `gpt-5.6-sol/low`.
3. Re-present and reconfirm the task so canonical task state stores the normalized runtime profile. No new hash is created.
4. Initialize the collector with `mpres token collector-init ...` before `mpres production init`.
5. Treat old token summaries that reported zero from missing counters as invalid. Regenerate them with v0.6.1; unknown totals will be `null` and coverage will be explicit.

## Runtime configuration

Remove concrete `model` and `model_reasoning_effort` entries from project `.codex/config.toml` and `.codex/agents/*.toml`. Runtime launch code must read the confirmed task profile and pass those exact values. Do not implement automatic escalation, downgrade, fallback, or retry-time substitution.

## Deferred work

Review/release coordinator removal, scheduler overlap repair, transactional mutable state, incident circuit breaking, and slide-subset diagnostics remain outside v0.6.1.
