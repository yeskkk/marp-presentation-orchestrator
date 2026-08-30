# Marp Presentation Orchestrator — binding project instructions

## 1. Role of the main agent

You are the **planner and high-level supervisor**, not the deck author or specialist reviewer. Read this file, `docs/WORKFLOW.md`, and `.agents/skills/marp-presentation-workflow/SKILL.md` at session start. Run `mpres doctor`, list tasks, and inspect the active task state before acting.

The planner interviews the user, writes and confirms the one top-level `TASK.md`, initializes presentations and content units, completes role assignments, starts coordinators, observes presentation-level milestones, applies the user pause policy, and resolves only genuinely cross-role conflicts. Do not write slide-by-slide content or directly manage every lesson author and reviewer.

## 2. Mandatory first interview and warnings

When no task exists, ask one compact questionnaire. Only the topic/title is mandatory; blank answers are filled by the planner.

1. Course/report title and concise scope.
2. Audience, prior knowledge, likely weaknesses, and expected gains.
3. Overall logical outline.
4. Presentation strategy.
5. References.
6. Delivery mode: `pilot`, `each`, or `all`.
7. Whether the material is difficult enough to raise reasoning from the default `medium` to `high` or `max`.
8. Whether Python-generated figures are explicitly enabled. The default is disabled.

For a course, determine meeting count and nominal minutes. Time calibrates volume but does not mechanically divide concepts.

Before writing TASK.md, explicitly remind the user:

- Every deck undergoes three mandatory review rounds: initial full review, incremental review, and final full review.
- Five independent channels participate in every round.
- Screenshots, PDF page rasterization/contact sheets, and model visual inspection are forbidden.
- The project creates Marp Markdown and PDF only; no persistent HTML artifact is generated or reviewed.
- Default reasoning effort is `medium`; difficult academic material should normally use `high` or `max` for authoring and domain-accuracy review.
- Python figures are disabled unless the task and exact asset decision both approve them.
- When a mathematical unit may benefit from dynamic exploration, authors make a small bounded search restricted to `geogebra.org`; selected materials are optional Markdown hyperlinks only and are never embedded or downloaded.

## 3. TASK.md confirmation gate

Create the task with `mpres task init`, complete `tasks/<slug>/TASK.md`, then run:

```text
mpres task present <slug>
```

Tell the user the exact path and wait for explicit confirmation of that version. After confirmation run:

```text
mpres task confirm <slug>
```

Only top-level TASK.md may be hashed. Never generate or validate hashes for sources, references, review requests, findings, PDF files, releases, archives, or context bundles. Editing TASK.md invalidates confirmation. After production initialization, TASK.md is frozen; use `mpres task restore-confirmed` for accidental drift or create a new task for a material plan change.

## 4. Production graph

After the gate passes, initialize exact presentation and content-unit IDs:

```text
mpres production init <slug> \
  --presentation "p01::Title" \
  --unit "p01::lesson01::Unit title"
```

For courses, one lesson/content unit maps to one `lesson-author` instance. For reports, use one logically coherent section per content unit. Author coordinators run lesson authors in bounded parallel batches, then integrate their modular fragments into one `presentation.md`.

Logical roles:

- `author-coordinator`: structured design, parallel lesson-author supervision, integration, render, self-check, and responses.
- `lesson-author`: exactly one lesson/content unit.
- `specialist-reviewer`: exactly one channel and round.
- `review-coordinator`: all five channels over all three rounds.
- `release-coordinator`: terminal closure and mechanical PDF release.

Do not revive numbered names such as worker1 or worker2.

## 5. Authoring requirements

The author coordinator must complete the deck manifest, pedagogy map, example map, terminology table, semantic-object registry, asset decisions, and the aggregated GeoGebra resource record before integration. Each lesson author supplies `section.md`, `UNIT-MANIFEST.yaml`, `GEOGEBRA-RESOURCES.yaml`, `SELF-CHECK.md`, local approved assets, and a checkpoint.

For a mathematically relevant unit, the lesson author should make a small, bounded attempt to find a useful public resource on `geogebra.org`. This is optional enrichment, not a requirement to add a link to every lesson: if GeoGebra is not relevant, record that judgment and stop. When searching, use at most the configured number of targeted queries and select at most a few resources. Any selected resource must be cited only as an ordinary Markdown hyperlink to `https://www.geogebra.org/m/<resource-id>`. Never embed a GeoGebra applet, iframe, script, object, screenshot, preview image, downloaded copy, or generated thumbnail.

One canonical Marp `presentation.md` is the source of truth. It must use the project theme, explicit slide IDs, and core/support classes. Prefer native text, formulas, Markdown tables, and theme CSS. Do not convert ordinary tables or short explanations into diagrams merely to add visual content.

Python figure generation is exceptional. It requires:

- TASK.md opt-in;
- `EXECUTION-POLICY.yaml` enabled;
- an approved entry in `ASSET-DECISIONS.yaml`;
- documented alternatives and instructional necessity;
- a generator and structural report;
- readable SVG text and no arrow/text overlap;
- no labelled raster image.

## 6. Rendering and artifact inspection

The standard release command is Marp CLI PDF output. `--html` may be passed only as a Marp parser option to permit approved local HTML in Markdown; no HTML file may be written or retained.

Before review, require:

- source lint;
- asset validation;
- successful Marp PDF build;
- PDF page count equal to slide count;
- landscape page geometry;
- readable text spans;
- no clipped text, replacement glyphs, internal production vocabulary, remote assets, or persistent HTML.

Inspection uses source and PDF structure/text only. Never take screenshots, rasterize deck pages, build contact sheets, or invoke model vision.

## 7. Mandatory review sequence

Every presentation follows:

```text
authoring
→ initial full review
→ author changes
→ incremental review
→ author changes
→ final full review
→ terminal author revision
→ release closure
→ release build
→ finalized
```

All five channels are required in every review round:

- language;
- domain accuracy;
- layout/PDF behavior;
- pedagogy;
- audience fit.

Initial and final rounds review the whole deck. Incremental review is limited to prior findings, named changed areas, and regressions. Terminal closure is not a fourth review and cannot invent a new substantive finding.

Reviewers never edit author source. Findings have stable IDs, learner impact, acceptance criteria, and verification method. Review coordinators may merge duplicate background but must not weaken a finding.

## 8. Supervision

The planner performs high-level supervision only when one of these happens first:

- twenty minutes have elapsed since the previous planner check;
- a presentation delivery sequence advances.

Use:

```text
mpres supervise <slug> --scope planner --record
```

Author and review coordinators supervise their own parallel subroles at the shorter task-policy interval. The planner intervenes only for confirmed-plan conflict, coordinator escalation, environment failure, or prolonged silence without durable progress. File changes and checkpoints count as durable progress; do not restart merely because logs are quiet.

## 9. Delivery modes

- `pilot`: fully deliver the first deck, pause once for user feedback, then resume parallel production after `mpres task continue`.
- `each`: pause after every deck.
- `all`: continue until all decks are finalized.

After a delivery, report the PDF, source, review records, and release retrospective. Feed stable lessons from the retrospective into later assignments.

## 10. Boundaries and safety

The supplied dangerous launcher follows the user's selected Codex mode. It is appropriate only in an externally isolated VM/container or dedicated low-privilege account. Repository role directories and read-only snapshots are workflow boundaries, not OS security boundaries.
