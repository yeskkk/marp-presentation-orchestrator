---
name: presentation-review-coordination
description: Coordinate five isolated specialist channels for one full-deck review and hand findings to the author without a second review or resolution gate.
---

# Review coordination

There is one full-deck review round named `full`. Run five planner-assigned reviewers in parallel. Each receives the frozen request and its own channel guidance, but no other channel findings and no author response.

Aggregate all channel submissions without weakening findings. Then hand the immutable finding registry to the author. The workflow does not ask reviewers to recheck modifications and does not require findings to become `resolved`. Release depends only on complete author responses, a completed modification checklist, and deterministic build checks.
