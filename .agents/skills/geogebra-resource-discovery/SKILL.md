---
name: geogebra-resource-discovery
description: Find and evaluate optional GeoGebra materials for a mathematics presentation, using geogebra.org only and citing selected materials as ordinary hyperlinks without embedding.
---

# GeoGebra resource discovery

Use this skill only when a lesson contains a mathematical relationship that could benefit from optional interactive exploration. Do not force a GeoGebra link into every lesson.

## Search boundary

Search only GeoGebra's own site, preferably with queries such as:

```text
site:geogebra.org/m <mathematical topic> <exploration or visualization>
```

A candidate must resolve to a public material URL of the form:

```text
https://www.geogebra.org/m/<resource-id>
```

Do not use mirrors, search-result aggregators, shortened URLs, calculator deep links, iframe URLs, API URLs, or resources hosted outside `geogebra.org`.

## Evaluation

Record the title, URL, author when visible, verified-resource status when visible, concept/unit, intended student action, mathematical fit, language burden, and date checked. Prefer a resource only when it materially improves exploration or intuition and does not contradict the course's conventions.

## Use in the deck

- Cite a selected resource only as an ordinary Markdown hyperlink, for example `[课后拖动参数观察轨迹](https://www.geogebra.org/m/...)`.
- Do not embed an applet, iframe, object, script, remote image, preview card, screenshot, QR code, or downloaded copy.
- The slide must remain complete without opening the link. Treat it as optional exploration or follow-up, not as evidence required for the in-class argument.
- Keep link text instructional: state what the learner should manipulate or observe.

Lesson authors record relevance, bounded searches, outcomes, and selected links in their unit-level `GEOGEBRA-RESOURCES.yaml`; the author coordinator validates and consolidates those records into the presentation-level file.
