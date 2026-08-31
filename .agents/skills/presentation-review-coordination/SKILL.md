---
name: presentation-review-coordination
description: Coordinate five isolated specialist channels for one full-deck review, support narrow pre-aggregation corrections, commit atomically, and route findings to authors without a second review.
---

# Review coordination

There is one full-deck review round named `full`. Run five planner-assigned reviewers in parallel. Each receives the frozen request and its own channel guidance, but no other channel findings and no author response.

Before aggregation, a channel may resubmit only to correct `location`, `evidence_path`, or `reviewer_note`. Finding IDs and the substantive fields—issue, learner impact, acceptance criteria, verification method, channel and round—cannot change. Preserve every attempt and mark which attempt it supersedes.

Validate all five **current** handoffs before modifying the shared registry or task state. If any handoff, receipt, ID namespace, channel or routing location fails, abort without partial commit. After all validate, write the registry once, generate mechanical finding-to-unit queues from the frozen deck manifest, and hand work to lesson authors/author coordinator.

The workflow does not ask reviewers to recheck modifications and does not require findings to become `resolved`. Release depends only on complete author responses, a completed modification checklist, and deterministic build checks.
