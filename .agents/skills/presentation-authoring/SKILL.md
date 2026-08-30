---
name: presentation-authoring
description: Build one modular Marp presentation through an author coordinator and parallel lesson/content-unit authors using structured teaching templates.
---

# Presentation authoring

## Author coordinator order

1. Read confirmed TASK.md, execution policy, Marp standard, task standards, exact assignment, and the `geogebra-resource-discovery` skill.
2. Complete DECK-MANIFEST, pedagogy map, example map, terminology, semantic objects, asset decisions, and the GeoGebra resource plan before prose drafting.
3. Write one exact lesson-author assignment per course meeting/content unit.
4. Spawn one lesson-author per unit in bounded parallel batches.
5. Supervise logs/checkpoints; do not silently replace them by writing every unit yourself.
6. Validate and aggregate every unit's `GEOGEBRA-RESOURCES.yaml`, then assemble fragments into `presentation.md`; reconcile notation and continuity, run `mpres geogebra validate`, source lint, asset validation, PDF build, and self-check.
7. Submit the review round required by state; respond to findings through structured feedback and targeted unit revisions.

## Concept-chain standard

A major concept normally moves through:

`why this matters → intuitive image/action/relationship → small concrete object → precise statement → reasoning/computation → return to the motivating question`.

The entry need not be a forced real-life story. A geometric contradiction, failed method, historical problem, small example, or imaginable motion may be better.

## Examples

Each example has a role: first demonstration, discrimination, counterexample, boundary, transfer, application, or synthesis. A transfer example must change something structural, not merely numbers.


## GeoGebra enrichment

For each mathematical unit, decide whether an interactive GeoGebra resource could genuinely help learners explore a dynamic relation that static slides cannot provide. If relevant, make a bounded search using only `geogebra.org`, with at most the task-policy query limit. Select no more than the configured small number of resources, and record title, URL, concept, intended use, and exact link text in `GEOGEBRA-RESOURCES.yaml`. If nothing suitable appears, record the search outcome and stop. If GeoGebra is not relevant, record the reason and do not search merely to satisfy a quota.

Selected resources are optional external follow-up links, never part of the PDF rendering pipeline. Use only ordinary Markdown hyperlinks. Do not embed, download, screenshot, reproduce, or use applet preview images. Read `references/geogebra-links.md`.

## Hard boundaries

One canonical `presentation.md`; no HTML deliverable; no screenshots/model vision; no self-approval; no Python figure without explicit opt-in. GeoGebra materials are optional links only and never part of the rendering pipeline.
