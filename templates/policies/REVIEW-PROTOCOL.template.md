# One-round five-channel full-deck review protocol

Every presentation receives exactly one review round named `full`. The five channels are language, domain accuracy, layout/presentation design, pedagogy, and audience fit. Each channel has a distinct reviewer, and **every reviewer reads the entire frozen deck**. Review work is created only after author freeze.

Reviewers receive the same frozen source and PDF plus their own exact assignment and channel guidance. They do not receive another channel's findings and never see the later revision. Mechanical HTML overflow and PDF-bound checks remain deterministic author/release gates rather than reviewer work.

A finding records stable ID, exact location, issue, learner impact, acceptance criteria, and verification method. It does not carry a resolved status. Before aggregation, a reviewer may correct only location, evidence path, or reviewer note while preserving substantive fields.

The Python control plane validates all five current handoffs, mechanically generates the aggregate, and commits the canonical outputs without a coordinator model. One deck-revision-author then receives the frozen deck, complete registry, review plan, routing, and author context packet. It responds to every finding, revises the whole deck, completes its checklist, and reruns deterministic gates. No reviewer recheck follows. Mechanical release begins only after this handoff creates `release_ready`.

Screenshots, page rasterization/contact sheets, model vision, and original-reference-PDF access are forbidden.
