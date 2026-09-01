---
name: presentation-artifact-inspection
description: Enforce the pinned Marp toolchain, run fast incremental gates during authoring, and inspect disposable HTML and PDF without screenshots or model vision.
---

# Artifact inspection

Before production, verify `TOOLCHAIN-LOCK.yaml`, exact Marp version `4.5.0`, and the three-slide smoke fixture covering DOM discovery, math, PDF generation, page count, and both `global_meeting_number` and `deck_local_ordinal`.

During authoring, run incremental source and structured-record checks on changed units and reuse valid cached results for unchanged content. Run full checks at freeze and release.

Disposable HTML inspection must discover supported Marp slide DOM quickly, wait for explicit slide/font/math/image readiness rather than unbounded `networkidle`, compare scroll and client dimensions, record overflow, and delete HTML immediately. A zero-slide result fails fast. PDF timeouts scale with slide count.

Also validate frontmatter, slide IDs and roles, global versus deck-local meeting numbering, TeX source and renderer output, interaction pairing and MCQ audits, local assets, GeoGebra links, course continuity, density, PDF geometry, text spans, and internal production-language leakage. Screenshots, raster contact sheets, OCR of generated slides, and model vision are forbidden.
