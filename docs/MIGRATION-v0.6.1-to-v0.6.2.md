# Migration from v0.6.1 to v0.6.2

1. Remove `.codex/agents/review-coordinator.toml` and `.codex/agents/release-coordinator.toml`.
2. Remove the two coordinator assignment templates and do not register their runtime-profile entries or checkpoints.
3. At freeze, register `control-plane/review-aggregation/<presentation>/job.yaml`. After all five specialist-review receipts validate, run the Python aggregation job and route its complete findings registry to one deck-revision-author.
4. At `release_ready`, register `control-plane/release/<presentation>/job.yaml`. Run deterministic release rendering, inspections, packaging, and receipt generation without a model thread.
5. Keep `TASK-RUNTIME-PROFILE.yaml` unchanged: only planner, author, reviewer, and their user-authored refinements select model runtimes.
