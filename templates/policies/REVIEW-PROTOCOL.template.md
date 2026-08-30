# One-round five-channel review protocol

Every presentation receives exactly one independent full-deck review. Five channels run in parallel:

- language;
- domain accuracy;
- layout and PDF behaviour;
- pedagogy;
- audience fit.

Each channel reviews the same frozen Marp source, PDF, source-lint report, asset report, and PDF-inspection report, but does not receive another channel's findings. Reviewers do not see author responses because those do not exist until the review is complete.

A finding records a stable ID, location, issue, learner impact, acceptance criteria, and verification method. Findings do not carry or require a `resolved` state. After aggregation, the author revises the deck, writes a structured response to every finding, completes the modification checklist, rebuilds and self-checks. The revised deck is not returned to reviewers. Once the deterministic author-revision gate passes, it is automatically approved for mechanical release.

The release coordinator checks only required files, response coverage, successful lint/build/PDF inspection, and release packaging. It does not decide whether the author's substantive change is good enough, and it cannot create a new finding.

Screenshots, PDF page rasterization/contact sheets, and model visual inspection are forbidden.
