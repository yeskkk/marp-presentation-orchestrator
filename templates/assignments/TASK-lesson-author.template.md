# Lesson/content-unit author assignment — [[PRESENTATION_ID]] / [[UNIT_ID]]: [[UNIT_TITLE]]

## Planner-owned exact brief

This assignment is runnable only after its semantics have been written by a main or delegated planner, either directly or through an approved batch plan.

[[PLANNER_ASSIGNMENT_BRIEF]]

## Instructional job

[[UNIT_SCOPE]]

## Audience, prerequisites, and local decision rights

[[AUDIENCE_CONTEXT]]

[[PRIOR_KNOWLEDGE_TO_REACTIVATE]]

[[LOCAL_DECISION_RIGHTS]]

## Profile-selected staged workflow

Stage state: `[[STAGE_STATE_PATH]]`

Use `lesson-authoring-stages` and `PRODUCTION-PROFILE.yaml`. One fixed lesson-author thread completes exactly the stage sequence recorded in `UNIT-STAGE-STATE.yaml` under this single assignment. After `mpres stage submit` validates a durable artifact, continue immediately to the next stage. Do not spawn a new worker, request a stage-specific assignment, or wait for coordinator acceptance.

For `legacy_migration`, the three stages are baseline audit, delta design/patch, and integration/semantic check; the six-stage greenfield process is skipped completely. Course units must finish with 2–3 valid diagnostic multiple-choice prompt/answer pairs. Academic reports are exempt from the quota.

## Canonical context and shared conventions

- Unit delta: `[[UNIT_SOURCE_PATH]]/UNIT-DELTA.yaml`
- Unit context packet: `[[UNIT_SOURCE_PATH]]/UNIT-CONTEXT-PACKET.yaml`
- Terminology: `[[TERMINOLOGY_PATH]]`
- Semantic objects: `[[SEMANTIC_OBJECTS_PATH]]`
- Deck manifest: `[[DECK_MANIFEST_PATH]]`
- Example map: `[[EXAMPLE_MAP_PATH]]`
- Canonical interaction record: `[[INTERACTION_MANIFEST_PATH]]`
- Generated MCQ compatibility view: `[[MCQ_AUDIT_PATH]]`
- Asset decisions: `[[ASSET_DECISIONS_PATH]]`
- GeoGebra record: `[[GEOGEBRA_UNIT_RESOURCES_PATH]]`
- Lesson/time plan: `[[LESSON_TIME_PLAN_PATH]]`

## References

[[REFERENCES]]

Read only approved extracted text and explicitly permitted web text. Never open, render, convert, OCR, or otherwise inspect an original reference PDF. Record a source gap rather than guessing.

GeoGebra search is optional and bounded. A selected item must be a verified `geogebra.org/m/...` resource and appear only as a descriptive Markdown hyperlink.

For a course, organize the fragment as the assigned numbered class meeting. Give the core path a natural stopping point near the nominal duration; optional worked examples may follow and need not be taught if class ends.

## Required handoff

- `[[UNIT_SOURCE_PATH]]/section.md`
- `UNIT-MANIFEST.yaml`
- `UNIT-DELTA.yaml`
- `UNIT-CONTEXT-PACKET.yaml`
- `INTERACTION-RECORD.yaml` as the sole editable interaction/MCQ record
- `GEOGEBRA-RESOURCES.yaml`
- `LESSON-TIME-PLAN.yaml`
- `SELF-CHECK.md`
- all profile-selected stage artifacts and the stage-sequence state
- local approved assets, if any
- checkpoint under `[[UNIT_CHECKPOINT_PATH]]`

After the durable handoff is validated, close or release the thread. Do not remain available for post-review revision. Do not edit another unit, the integrated deck, `TASK.md`, reviewer files, deliverables, or workflow-engine code. Do not use screenshots or model vision.
