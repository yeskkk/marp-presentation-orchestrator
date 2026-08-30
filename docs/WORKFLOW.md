# Marp presentation workflow

## Architecture

```text
confirmed TASK.md
  → presentation plan
    → author coordinator
      → parallel lesson/content-unit authors
      → integrated presentation.md + theme.css + local assets
      → Marp CLI PDF
    → five parallel specialist reviewers × three rounds
    → terminal author revision
    → release coordinator closure
    → final Marp PDF + source + records
```

The project deliberately has no Quarto, notebook execution, Reveal.js output, or persistent HTML artifact. Marp CLI may invoke a browser internally to print PDF.

## State sequence

```text
task_draft
→ awaiting_user_confirmation
→ confirmed
→ working

presentation:
authoring
→ initial_review_requested / initial_reviewing
→ initial_changes
→ incremental_review_requested / incremental_reviewing
→ incremental_changes
→ final_review_requested / final_reviewing
→ terminal_revision
→ release_closure_requested
→ release_approved
→ finalized
```

Three rounds and five channels are mandatory. A final candidate with no findings still passes through all three rounds. Release closure verifies final findings and mechanical readiness only.

## Directory layout

```text
tasks/<slug>/
├── TASK.md
├── EXECUTION-POLICY.yaml
├── REVIEW-PROFILE.yaml
├── MARP-AUTHORING-STANDARD.md
├── downloads/
├── logs/
├── reviews/<presentation>/
├── workers/
│   ├── author-coordinator/
│   ├── lesson-authors/<presentation>/<unit>/
│   ├── review-coordinator/
│   ├── specialist-reviewers/<presentation>/<round>/<channel>/
│   └── release-coordinator/
└── deliverables/<presentation>/
    ├── <presentation>.pdf
    ├── source/
    ├── findings.yaml
    ├── CLOSURE.md
    ├── render-report.json
    ├── pdf-inspection.json
    └── release.json
```

## Parallel authoring

Each course meeting or report section receives an isolated unit directory and assignment. Unit authors do not edit integrated source. The author coordinator establishes shared terminology, semantic objects, example roles, asset policy, and slide-ID namespace before spawning unit authors. Integration validates each unit's `GEOGEBRA-RESOURCES.yaml`, aggregates the records, copies unit handoffs into `source/sections/`, and assembles canonical `presentation.md`. A relevant unit may make a bounded `geogebra.org` search, but selected resources are ordinary Markdown links only; embeds, screenshots, preview images, and downloads are forbidden.

## Rendering

The render transaction:

1. validates required structured files and placeholders;
2. lints Marp frontmatter, slide IDs, classes, density, local assets, manifest, and GeoGebra link-only records;
3. validates `ASSET-DECISIONS.yaml`;
4. freezes a source snapshot;
5. runs local Marp CLI with `--pdf --allow-local-files --html --theme-set theme.css` and an explicit PDF output;
6. removes and reports any unexpected HTML artifact;
7. checks PDF page count, geometry, text spans, font sizes, clipping, missing glyph markers, and internal production vocabulary.

The `--html` flag enables controlled HTML tags in Marp Markdown; it does not request an HTML output file.

## Review requests

Each request freezes the rendered source snapshot, PDF, source lint, asset validation, PDF inspection, render report, and author self-check. It contains no digest. Reviewers consume the frozen request directory and do not edit it.

Initial and final rounds use complete context. Incremental context includes prior findings, author responses, changed areas, and regressions. Five channel reports are required before aggregation.

## No-screenshot inspection

No code path creates slide screenshots. Layout evidence comes from Marp source structure and PDF geometry/text. OCR rasterization remains available only for scanned reference documents after ordinary text extraction fails; it is not deck review.

## Supervision

Planner supervision is event-aware: a ten-second lightweight poll can observe state, but the planner records/intervenes only when twenty minutes are due or a deck delivery occurs. Author/review coordinators supervise lesson authors/review channels on shorter intervals and use checkpoints before restart.
