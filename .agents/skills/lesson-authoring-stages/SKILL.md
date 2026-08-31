---
name: lesson-authoring-stages
description: Guide one lesson-author thread through the complete course/report stage sequence under one planner-approved assignment.
---

# One-thread staged authoring

The planner writes and approves one exact `TASK-LESSON-AUTHOR.md` for the whole lesson/content unit. The same lesson-author thread completes every stage in order.

For a course: scope/sources → learner need → domain development → entry/diagnostics → learner-facing language → Marp integration. A report uses the compact profile declared by task state.

At each stage:

1. Read the prior durable artifacts and the unchanged lesson assignment.
2. Complete the current `STAGE-ARTIFACT.md`.
3. Save a checkpoint.
4. Run `mpres stage submit`; successful validation automatically activates the next stage.
5. Continue in the same thread.

There is no stage-specific assignment, no new worker spawn, and no coordinator acceptance gate between stages. Reopening a stage keeps the lesson assignment and resumes the same lesson-author thread.

Original PDFs, screenshots and model vision remain forbidden.
