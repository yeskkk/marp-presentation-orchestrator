---
name: mathematical-typesetting-inspection
description: Mechanically inspect mathematical source and the disposable Marp HTML renderer output without introducing a PDF-math evidence layer.
---

# Mathematical typesetting inspection

Run two layers only:

1. **Source inventory.** Ignore comments, fenced code and inline code; inventory each slide's math fragments, environments and commands. Block mismatched environments, unmatched delimiters, bare TeX control words outside math, and unsupported source forms caught by the project lint.
2. **Renderer probe.** During the disposable Marp HTML author/release gate, record rendered MathJax/KaTeX/MathML nodes, renderer error nodes and raw TeX markers leaked into learner-visible text. Source math with no rendered node is blocking.

Do not create `MATH-PDF-EVIDENCE`, rasterize PDF pages, take screenshots or use model vision. General PDF structural/text checks remain separate. Passing these two layers does not prove mathematical correctness, notation consistency, or that a formula states the intended theorem; the domain-accuracy reviewer remains responsible for those judgments.
