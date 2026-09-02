Read and obey `AGENTS.md` as the binding project instructions.

## Task runtime

Every task creates `TASK-RUNTIME-PROFILE.yaml`. The user may edit all model and reasoning choices before initial confirmation; after confirmation the normalized profile is immutable. Agents may resolve the selected entry but may not choose, escalate, downgrade, substitute, or retry with another runtime.

## v0.6.2 mechanical control jobs

Do not launch or emulate `review-coordinator` or `release-coordinator` model roles. Use the Python review-aggregation and release jobs. They have no model runtime, assignment, checkpoint, or thread.

## v0.6.3 current-plus-next pipeline

In `all` mode, entering review automatically opens exactly one earliest-next authoring lane. Keep it open through current-deck review, revision, and release-ready states. Respect `each`, the initial `pilot` pause, and an explicit zero next-WIP limit.
