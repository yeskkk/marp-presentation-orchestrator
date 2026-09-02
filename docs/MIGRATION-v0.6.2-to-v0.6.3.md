# Migration from v0.6.2 to v0.6.3

This release changes only the bounded critical-path presentation window.

- No task data migration is required.
- Existing `PRESENTATION-WORK-PLAN.yaml` files are projections and are refreshed by the scheduler.
- A v0.6.2 task already in review, revision, or release can run `mpres production activate --presentation <next-id>` immediately; the next lifecycle transition also repairs the active window automatically.
- `delivery_mode: each`, the initial pilot pause, and `next_presentation_authoring_wip_limit: 0` retain their previous behavior.
- Review/release control-plane jobs, task runtime profiles, and token accounting are unchanged from v0.6.2.
