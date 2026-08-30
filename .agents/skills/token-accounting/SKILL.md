---
name: token-accounting
description: Collect exact Codex token counters without reading message content and attribute them by presentation, role, unit, channel, stage, and thread.
---

# Token accounting

Before the first coordinator starts, initialize the collector configuration and run the collector at the task policy interval. It reads only session metadata and token-count event fields, never prompts, responses, or tool contents. Missing counters remain unavailable and are never estimated.

Planner supervision checks collector freshness and records gaps without stopping recoverable work.
