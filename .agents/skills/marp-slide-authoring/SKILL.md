---
name: marp-slide-authoring
description: Author concise, mathematically capable Marp Markdown slides using a stable academic theme and PDF-only build path.
---

# Marp slide authoring

Read the local references before editing a deck.

- Use one line `---` to separate slides.
- Global directives live only in the canonical frontmatter.
- Use `<!-- slide-id: ... -->` and `<!-- _class: core -->` or `support` on every slide.
- Prefer a concise title and one primary message per slide.
- Use Markdown tables for comparisons and structured data; use CSS columns and callouts before reaching for an image.
- Use Marp image syntax only for local images with a clear teaching purpose. GeoGebra resources, when selected, are ordinary Markdown hyperlinks only and are never images or embeds.
- Use `$...$` and `$$...$$` with `math: mathjax`.
- The build target is PDF only. `--html` may be passed to permit local HTML tags in Markdown, but no HTML artifact is written or reviewed.
- Python diagrams are an exceptional, explicitly approved asset type.
- A GeoGebra material may appear only as a normal Markdown hyperlink to `https://www.geogebra.org/m/...`; never use an iframe, remote image, preview card, QR code, or downloaded applet.
