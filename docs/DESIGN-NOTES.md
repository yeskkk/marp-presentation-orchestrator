# Design notes

## Deliberate choices

- Marp PDF-only instead of Quarto/Reveal HTML inspection.
- Unpinned Marp CLI; capability is established by a real probe.
- One complete five-channel review, followed by author-owned revision with no independent recheck.
- Findings remain historical statements rather than lifecycle objects with resolved states.
- Planner authors every exact assignment; coordinators only request roles and supervise execution.
- Course units require 2–3 diagnostic MCQs; reports are exempt.
- Original PDFs are inaccessible to workers after system extraction.
- No screenshot/model-vision review.
- Python figures are exception-only; native text, formula, table and CSS are preferred.
- GeoGebra is optional hyperlink enrichment restricted to verified `geogebra.org/m/...` materials.

## Why staged authoring exists

The six-stage course profile prevents one worker from simultaneously optimizing scope, domain correctness, learner needs, diagnostic activity, student language and Marp layout. Each accepted artifact becomes the durable input to the next stage. Reports use a compact profile because a short academic narrative does not always justify six separate gates.

## Assignment ownership

A coordinator knows when work is needed but the planner owns task meaning. The request/brief/decision contract preserves that distinction while avoiding accidental coordinator-authored assignments. Fixed boilerplate lives in skills and templates; the planner writes the exact scope, constraints and acceptance criteria.

## Quality/cost trade-off

The user selected no reviewer verification after author revision. This reduces repeated review cost but means the sole frozen-deck review is the only independent content check. The release record explicitly states that findings were answered but not independently resolved. Mechanical release cannot compensate for a weak author revision.

## Future improvements

- Deterministic cross-check of stage artifacts against final deck claims.
- Better PDF text-box overlap diagnostics without rasterization.
- More robust import adapters for Codex token exports.
- An App Server scheduler that persists actual thread IDs and close outcomes.
- Optional task profiles for non-mathematical courses while preserving the same assignment/review boundaries.
