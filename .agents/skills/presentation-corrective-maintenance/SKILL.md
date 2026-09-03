---
name: presentation-corrective-maintenance
description: Revise a published presentation in a numbered maintenance cycle while preserving the historical release and applying the selected targeted or full-review policy.
---

# Corrective maintenance

Open a numbered maintenance cycle from the published source; never overwrite the historical release. A main or delegated planner writes and approves the exact maintenance assignment. `targeted_patch` permits only the named changes and deterministic regression checks. `full_corrective_review` runs one new isolated five-channel full-deck review for the maintenance candidate, then returns all findings to the maintenance author and proceeds without reviewer recheck.

Publish a new numbered revision, update the current-revision pointer, retain prior PDFs and sources, and record the retrospective. The normal production profile and deck revision role do not retroactively reopen original lesson authors.

## v0.6.6 diagnostic intake

Before opening corrective maintenance for a user-reported local defect, prefer a bounded `mpres diagnostic open` case. Treat its `PATCH-SCOPE.yaml` as advisory evidence, not authorization. A planner may convert it into an exact targeted-maintenance assignment, or request an explicitly larger case/full review. Never let the diagnostic worker edit the published source or bypass maintenance revisioning and normal gates.
