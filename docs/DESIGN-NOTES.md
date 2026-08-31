# Design notes — v0.4.1

## Deliberate choices

- Marp source and PDF are the only durable presentation artifacts.
- Disposable Marp HTML is allowed only for author/release mechanical overflow inspection.
- Mechanical overflow is an author self-check and submission gate, not a reviewer responsibility.
- Planner defaults to Sol/max; workers default to Sol/high, from one global policy file.
- Course decks are organized by numbered meetings, not textbook chapters.
- A course normally prepares about 1.5× nominal time; optional explanatory examples come after the natural stopping point and need not be presented.
- One complete five-channel review, followed by author-owned revision with no independent recheck.
- Findings remain historical statements rather than resolved lifecycle objects.
- Planner personally writes every exact assignment.
- Original PDFs are inaccessible to workers after system extraction.
- Screenshots and model-vision review are forbidden.
- Python figures are exception-only.
- Verified GeoGebra materials may be reused across meetings; there is no deduplication policy.

## Why temporary HTML is not a second output

Marp's HTML output exposes each slide as a real DOM section. That permits deterministic scroll/client dimension checks which PDF text extraction cannot reliably provide. The HTML is generated in a temporary directory, is never given to reviewers, is deleted immediately, and never enters deliverables. It is analogous to a compiler's temporary intermediate representation, not a parallel teaching artifact.

## Time planning philosophy

The nominal class duration marks the point where essential teaching should be complete. Preparing additional examples gives the instructor flexibility to respond to audience speed. The framework checks that the stopping point and extension bank are explicit; it does not reject a deck merely because the prepared-time estimate differs from 1.5×.
