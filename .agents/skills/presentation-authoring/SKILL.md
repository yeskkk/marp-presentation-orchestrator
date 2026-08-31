---
name: presentation-authoring
description: Coordinate staged parallel lesson authors and integrate a coherent Marp course or report without turning planner suggestions into a rigid classroom script.
---

# Presentation authoring

The author coordinator completes deck-level maps, requests planner-written unit assignments, supervises one lesson author per content unit, validates durable same-thread stage artifacts, integrates fragments, reconciles terminology and semantic objects, builds the PDF, and responds to the sole review.

Planner examples, titles, activities, and page sequences are replaceable hypotheses unless explicitly listed as hard constraints. Local authors may improve them while preserving confirmed scope and recording important decisions.

For courses, every unit includes exactly 2–3 diagnostically useful multiple-choice prompt/answer pairs at different conceptual points. Reports are exempt. A question must require fresh inference, not merely repeat the previous slide.

After review, the author responds to every finding, completes the modification checklist, revises, reruns lint/assets/PDF inspection, and submits the revision. No reviewer or verifier evaluates the revision again.

Only extracted reference text and explicitly permitted web text may be read. Never open or process the original reference PDF.

## Course meeting and time strategy

A course deck is organized by numbered class meetings, not by textbook chapter boundaries. Each meeting has a core path intended to fit the nominal class duration and an optional worked-example extension bank afterward. Preparing about 1.5 times the nominal duration is a default planning heuristic, not a completion requirement or hard gate. At class end the instructor may stop without presenting the extension examples.

Before any review request, the author coordinator must pass the temporary Marp HTML overflow check and record it in SELF-CHECK.md. Reviewers do not repeat this mechanical check.

## Course-level continuity

For a course, use `COURSE-TERMINOLOGY.yaml`, `COURSE-SEMANTIC-OBJECTS.yaml`, `CROSS-DECK-HANDOFFS.yaml`, and each deck's `PRESENTATION-CONTINUITY-MAP.yaml`. A deck term must map to a course term, course-scoped semantic objects must exist in the course registry, and later decks must state what terms/objects are reactivated from the previous meeting.

## Teaching-move density

Every slide receives one `principal_teaching_move` entry in `SLIDE-DENSITY-AUDIT.yaml`, plus its substantial blocks and any reason not to split. Character/bullet counts are warnings; the contract is that unrelated teaching actions should not be crowded onto one slide.
