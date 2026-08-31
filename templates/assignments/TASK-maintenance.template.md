# Corrective maintenance assignment — [[PRESENTATION_ID]] revision [[REVISION_NUMBER]]

## Planner-owned exact brief

Only the main planner may replace this placeholder. Stop if it remains incomplete.

[[PLANNER_ASSIGNMENT_BRIEF]]

## Mode and reason

- Mode: `[[MODE]]`
- Reason: [[REASON]]
- Previous published source: `[[SOURCE_RELEASE]]`

## Scope

Read `CORRECTIVE-SCOPE.md`. Preserve all unaffected material. A `targeted_patch` addresses only the planner-approved defect and receives no new specialist review. A `full_corrective_review` receives one isolated five-channel full review, followed by author-owned revision and direct mechanical publication without reviewer recheck.

## Required outputs

- revised `source/`
- `MAINTENANCE-CHECKLIST.yaml`
- `MAINTENANCE-RETROSPECTIVE.md`
- successful Marp source, asset, mathematics, density, course-consistency, temporary-HTML layout and PDF checks
- for `full_corrective_review`: complete author responses to every maintenance finding

Do not overwrite the historical release. The new revision is published under the deliverable revision tree and becomes current only after `mpres maintenance publish`.
