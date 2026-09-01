# Review coordinator assignment — [[PRESENTATION_ID]]: [[PRESENTATION_TITLE]]

## Planner-owned exact brief

[[PLANNER_ASSIGNMENT_BRIEF]]

Confirmed plan: `[[TASK_MD_PATH]]`
Review root: `[[REVIEW_ROOT]]`
Findings registry: `[[FINDINGS_REGISTRY_PATH]]`

Start only after the complete deck is frozen. Coordinate exactly one review round named `full`. Five distinct reviewers receive five exact planner-approved channel assignments; each reviewer must read the entire frozen deck, remain isolated from the other channels, and stop after submitting its handoff.

Validate all five current handoffs before changing shared state. Permit only narrow pre-aggregation corrections to location, evidence path, or reviewer note while preserving finding identity and substance. Commit the registry atomically, generate `REVISION-ROUTING.yaml`, and hand the full frozen source, review plan, finding registry, and author context packet to one `deck-revision-author`.

Do not create reviewer work before freeze, write assignments, edit source or findings, reopen lesson authors, organize a second review, ask reviewers to inspect the later revision, inspect mechanical overflow, open original PDFs, use screenshots/model vision, or hot-patch the workflow engine.
