---
name: token-accounting
description: Import exact token counters at workflow milestones without model polling or repeated full-context collection.
---

# Token accounting

Collect only exact counters exposed by session metadata; never estimate missing values or read prompt/response contents. Attribute imported counters by assignment epoch, role, presentation, unit, review channel, stage profile, and thread handle.

Generate summaries at meaningful milestones—assignment start/handoff, freeze, review completion, revision completion, and release—not by periodic model polling. Record unavailable counters as unavailable. Cached input remains distinct from uncached input.
