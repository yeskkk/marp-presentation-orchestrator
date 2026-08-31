---
name: presentation-artifact-inspection
description: Deterministically inspect Marp source, disposable Marp HTML layout, and PDF without screenshots, page rasterization, or model vision.
---

# Artifact inspection

The author and release coordinator generate temporary Marp HTML, inspect every `section[data-marpit-scope]` or `.marpit > section`, compare `scrollWidth/scrollHeight` with `clientWidth/clientHeight`, record overflow, and delete the HTML. A successful report is required before review or release. This is not delegated to reviewers.

Also check frontmatter, slide boundaries, IDs, core/support roles, prompt/answer adjacency, TeX source, course MCQ quotas, MCQ option audits, local assets, GeoGebra hyperlink policy, PDF page count/geometry/text spans, internal production vocabulary, and text clipping.

For course tasks, each content unit must contain 2 or 3 valid multiple-choice prompt slides. Reports have no quota. Mechanical checks do not judge whether an author's post-review revision satisfies a finding.
