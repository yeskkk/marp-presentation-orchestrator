---
name: courseware-production-profiling
description: Choose the smallest valid stage graph and work granularity for greenfield, migration, targeted revision, or maintenance work.
---

# Production profiling

Before production, classify the task as `greenfield_full`, `greenfield_compact`, `legacy_migration`, or `targeted_revision`. Record the choice in `PRODUCTION-PROFILE.yaml` and keep it consistent with confirmed `TASK.md`, task kind, stage graph, unit granularity, and full-deck review policy.

Use `legacy_migration` whenever a mature prior deck is the baseline and the work is chiefly keep/modify/move/delete/add. It always uses the three migration stages and still assigns one fixed author per lesson. Do not make maturity an excuse to reduce the five reviewers' full-deck reading requirement.

Changing the production mode after confirmation is a material policy amendment.
