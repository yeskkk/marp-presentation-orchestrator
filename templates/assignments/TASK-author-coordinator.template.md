# Author coordinator assignment — [[PRESENTATION_ID]]: [[PRESENTATION_TITLE]]

## Task and audience

Confirmed plan: `[[TASK_MD_PATH]]`

[[PRESENTATION_SCOPE]]

[[AUDIENCE_CONTEXT]]

## Content units

[[CONTENT_UNIT_TABLE]]

Create one exact lesson-author assignment per unit and run them in bounded parallel batches. Do not treat prior exposure as mastery.

## Structured design before drafting

Complete:

- `[[AUTHOR_SOURCE_PATH]]/DECK-MANIFEST.yaml`
- `PEDAGOGY-MAP.md`
- `EXAMPLE-MAP.md`
- `TERMINOLOGY.md`
- `SEMANTIC-OBJECTS.yaml`
- `ASSET-DECISIONS.yaml`
- `GEOGEBRA-RESOURCES.yaml`
- legacy audit/reuse maps when relevant

[[PRESENTATION_STRATEGY]]

## References

[[REFERENCES]]

## Workflow

1. Complete maps and lesson assignments.
2. Spawn one lesson-author per unit. Each unit must record whether a bounded GeoGebra-only search is relevant, then either perform it or explain why it is not applicable.
3. Validate and aggregate unit GeoGebra records. Select only genuinely useful public materials at `https://www.geogebra.org/m/...` and cite them as ordinary Markdown hyperlinks.
4. Assemble fragments into `presentation.md`; reconcile terminology, slide IDs, semantic objects, examples, links, and transitions.
5. Run `mpres source lint`, `mpres assets validate`, `mpres render`, and `mpres inspect`.
6. Submit initial, incremental, final, and terminal requests as state requires.

## Paths

- Author source: `[[AUTHOR_SOURCE_PATH]]`
- Build: `[[AUTHOR_BUILD_PATH]]`
- Lesson-author root: `[[LESSON_AUTHOR_ROOT]]`
- Reviews: `[[REVIEW_ROOT]]`

## Forbidden actions

Do not change TASK.md, self-approve, use screenshots/model vision, edit reviewer reports, generate HTML, or maintain a second lecture source. Python figures require explicit task and asset approval. GeoGebra applets, iframes, remote images, previews, QR codes, downloaded copies, and non-GeoGebra mirrors are forbidden.

## Task-specific acceptance criteria

[[ACCEPTANCE_CRITERIA]]
