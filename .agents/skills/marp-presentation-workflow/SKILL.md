---
name: marp-presentation-workflow
description: Plan and supervise a confirmed Marp-to-PDF task with parallel lesson authors, three mandatory review rounds, and no screenshot-based inspection.
---

# Planner workflow

Read `AGENTS.md`, `docs/WORKFLOW.md`, active task state, and this skill.

## Tell the user before TASK.md

- Every presentation has three rounds: initial full review, incremental review, final full review.
- Five specialist channels are required in every round.
- Screenshots, PDF raster contact sheets, and model visual inspection are forbidden.
- Default reasoning effort is `medium`; recommend `high` or `max` for difficult academic material.
- Ask whether to pause after the first delivered presentation (`pilot`), after every presentation (`each`), or only after all (`all`).
- Marp source and PDF are the deliverables. No persistent HTML artifact is generated.
- Python figures are disabled by default and require explicit opt-in and justification.
- Mathematical units may make a bounded GeoGebra-only resource search; selected materials are optional ordinary Markdown hyperlinks and are never embedded.

## Planner boundary

The planner creates and confirms TASK.md, initializes the production graph, completes role assignments, and starts coordinators. It does not author slides or manage every unit/reviewer directly. The author coordinator supervises lesson authors; the review coordinator supervises specialist reviewers; the release coordinator owns closure.

While work is active, wake after 1200 seconds or immediately when one presentation is delivered, whichever occurs first. Intervene only for coordinator escalation, plan conflict, prolonged silence without durable progress, or environment failure.
