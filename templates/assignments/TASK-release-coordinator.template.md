# Release coordinator assignment — [[PRESENTATION_ID]]: [[PRESENTATION_TITLE]]

## Planner-owned exact brief

[[PLANNER_ASSIGNMENT_BRIEF]]

Act only after the author has submitted a complete post-review revision and the workflow has automatically placed the presentation in `release_ready` state.

- Release-ready source: `[[APPROVED_SOURCE_PATH]]`
- Release build: `[[RELEASE_BUILD_PATH]]`
- Deliverables: `[[DELIVERABLE_PATH]]`
- Author responses: `[[AUTHOR_RESPONSES_PATH]]`
- Modification checklist: `[[MODIFICATION_CHECKLIST_PATH]]`

Run only deterministic source lint, asset/GeoGebra validation, the disposable Marp HTML overflow gate, Marp PDF build, PDF inspection, packaging, and release records. Delete temporary HTML immediately and never retain it in the release. Do not judge whether a finding was substantively resolved, add findings, edit semantics, open original reference PDFs, retain HTML, use screenshots, or use model vision.
