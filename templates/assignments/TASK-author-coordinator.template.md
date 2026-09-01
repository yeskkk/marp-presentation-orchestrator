# Author coordinator assignment — [[PRESENTATION_ID]]: [[PRESENTATION_TITLE]]

## Planner-owned exact brief

This section must be completed and approved by a main or delegated planner before work starts.

[[PLANNER_ASSIGNMENT_BRIEF]]

## Confirmed task and content units

Confirmed plan: `[[TASK_MD_PATH]]`

[[CONTENT_UNIT_TABLE]]

## Responsibilities

Coordinate only the current critical-path deck. Maintain deck-level pedagogy, examples, terminology, semantic objects, assets, continuity, interaction, GeoGebra, and lesson-time records. Lesson workspaces are created lazily after a planner approves `BATCH-ASSIGNMENT-PLAN.yaml`; the program expands each exact lesson assignment from that plan. Do not write lesson assignments yourself.

Supervise one fixed author per materialized lesson through the production profile recorded in `PRODUCTION-PROFILE.yaml`. Validate the canonical unit records and durable handoff, integrate all units into one `presentation.md`, compile `AUTHOR-CONTEXT-PACKET.yaml` from the integrated snapshots, and run all deterministic author gates. Freeze the complete deck only after the source, assets, course consistency, density, mathematics, disposable-HTML layout, and PDF checks pass.

After the frozen-deck handoff, this coordinator and the lesson-author threads may close. Post-review revision belongs to a separate `deck-revision-author`; do not remain open speculatively and do not recall lesson authors.

## Paths

- Author source: `[[AUTHOR_SOURCE_PATH]]`
- Build: `[[AUTHOR_BUILD_PATH]]`
- Lesson-author root: `[[LESSON_AUTHOR_ROOT]]`
- Reviews: `[[REVIEW_ROOT]]`

## Boundaries

Do not alter `TASK.md`, create or complete worker assignments, launch reviewers before freeze, launch release work before `release_ready`, self-review, inspect screenshots, open original reference PDFs, or hot-patch the workflow engine.
