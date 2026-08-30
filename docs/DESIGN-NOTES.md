# Design decisions

## Why Marp

This branch treats slide content as the scarce resource. It removes Quarto/Jupyter/Reveal processing and the associated HTML inspection loop. The source is ordinary Marp Markdown with one academic CSS theme; the sole rendered artifact is PDF.

## Preserved lessons

- structured pedagogy, example, terminology, semantic-object, asset, and manifest records;
- one author per lesson/content unit and bounded parallelism;
- three mandatory rounds and five independent channels;
- stable findings and terminal closure rather than an informal fourth review;
- random-entry classroom self-containment;
- exact audience profile and expected gains;
- planner supervision every twenty minutes or delivery event;
- pilot first-deck feedback option;
- only top-level TASK.md uses a confirmation digest;
- optional, bounded GeoGebra enrichment uses registered `geogebra.org` Markdown links only and never reintroduces remote embeds or image-production work.

## Restrained visual policy

The system does not assume more pictures are better. Tables remain tables; equations remain native math; simple contrasts use CSS columns or callouts. Python diagrams are disabled by default because text size, arrow placement, semantic drift, and unnecessary conversion of tabular information have repeatedly produced waste. The optional figure helper measures Matplotlib text and arrow/text bounds but cannot prove a diagram is pedagogically worthwhile.

## Future improvements

- richer PDF line/shape collision analysis without rasterization;
- formal schema validation for every YAML record;
- domain-specific terminology linters;
- deterministic CSS regression checks based on Marp/PDF object geometry;
- Codex App Server orchestration with persistent thread IDs.
