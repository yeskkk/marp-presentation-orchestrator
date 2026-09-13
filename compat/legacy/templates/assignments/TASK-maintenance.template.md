# Corrective maintenance assignment — [[PRESENTATION_ID]] revision [[REVISION_NUMBER]]

## Planner-owned exact brief

This section may be written and approved by a main or delegated planner. Only revising the top-level `TASK.md` is exclusive to the main agent.

[[PLANNER_ASSIGNMENT_BRIEF]]

## Mode and reason

- Mode: `[[MODE]]`
- Reason: [[REASON]]
- Previous published source: `[[SOURCE_RELEASE]]`

## Scope

Read `CORRECTIVE-SCOPE.md` and preserve all unaffected material.

- `targeted_patch`: address only the approved defect, run the compact targeted-revision profile and mechanical regression checks, then publish a numbered revision without specialist review.
- `full_corrective_review`: run one isolated five-channel full-deck review; all five reviewers read the whole candidate. One revision author then responds and revises, followed by direct mechanical publication without reviewer recheck.

## Required outputs

- revised `source/`
- `MAINTENANCE-CHECKLIST.yaml`
- `MAINTENANCE-RETROSPECTIVE.md`
- successful source, asset, mathematics, density, course-consistency, temporary-HTML layout, and PDF checks
- for `full_corrective_review`: complete responses to every maintenance finding

Do not overwrite the historical release. Publish under `deliverables/<id>/revisions/rNNNN/` and update the current pointer only after the release gate passes. A suspected workflow-engine defect must be recorded as an incident and handled through a TASK policy amendment, not patched inside maintenance.
