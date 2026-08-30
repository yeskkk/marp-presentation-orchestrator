---
name: lesson-authoring-stages
description: Stage lesson/content-unit authoring so each worker solves scope, learner need, domain development, diagnostics, language, and Marp integration in a controlled sequence.
---

# Staged lesson authoring

Course units use six stages:

1. scope and extracted sources;
2. learner need;
3. domain development;
4. cognitive entry, examples, and 2–3 diagnostic MCQs;
5. learner-facing language;
6. Marp integration and self-check.

Academic reports use the compact profile defined in `EXECUTION-POLICY.yaml` and are exempt from the MCQ quota.

Only the current stage is active. The lesson author completes its artifact and runs `mpres stage submit`; the author coordinator inspects the durable artifact and runs `mpres stage accept` or `reopen`. Acceptance activates the next stage. Unit handoff and integration are blocked until all configured stages are accepted.
