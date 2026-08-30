---
name: python-asset-generation
description: Exception-only workflow for approved Python-generated Marp assets with readable labels and structural layout reports.
---

# Python asset generation

This skill is inactive unless TASK.md and EXECUTION-POLICY enable Python assets and ASSET-DECISIONS.yaml approves the exact asset.

Before writing code, record why a Markdown table, formula, CSS layout, or existing image is insufficient. Prefer SVG. Generated raster images containing text are forbidden. Use the project plotting helper so text sizes and arrow/text overlaps are reported. A failed asset report blocks use of the asset. The figure must explain a relationship that is genuinely hard to express directly; decoration is not a reason.
