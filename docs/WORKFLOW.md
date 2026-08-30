# Workflow and state machine

## 1. Confirmed task

```text
task_draft
→ awaiting_user_confirmation
→ confirmed
→ working
```

Only `TASK.md` uses a confirmation hash. Production initialization freezes the plan. Material policy changes require editing and reconfirming TASK.md; sidecar amendment records are audit history only.

## 2. Planner-owned assignments

Every runnable role or authoring stage has four files:

```text
ASSIGNMENT-REQUEST.yaml
ASSIGNMENT-BRIEF.yaml
ASSIGNMENT-DECISION.yaml
TASK-....md / STAGE-ASSIGNMENT.md
```

A coordinator may create the request. The main planner personally writes the structured brief and exact taskbook, then approves it. The CLI rejects placeholders, short generic taskbooks, restricted reference paths and unapproved decisions.

## 3. Parallel staged authoring

Course units use six stages; report units use four compact stages. Each stage moves through:

```text
awaiting_assignment
→ active
→ submitted
→ accepted
```

The next stage cannot activate until the planner has written and approved its assignment. An accepted stage may be reopened with a recorded reason. One lesson-author owns one unit; author coordinator supervises multiple units in bounded parallel batches and later assembles them into `presentation.md`.

## 4. Course interaction contract

Each course unit requires two or three diagnostic MCQ prompt/answer pairs. Prompt and response slides are adjacent, reciprocal in manifests, and marked core/support. `INTERACTION-MANIFEST.yaml`, `MCQ-AUDIT.yaml`, `UNIT-MANIFEST.yaml`, `DECK-MANIFEST.yaml` and final source must agree. Academic reports are exempt from the quota.

## 5. Source and reference boundary

System ingestion stores originals and restricted metadata outside worker-readable context and removes read permissions. Workers use only `downloads/text/`. Stage 01, assignments, review bundles and manifests are scanned for `.pdf` and restricted paths. Source gaps are recorded rather than solved by reopening the original.

## 6. Marp build

```text
canonical presentation.md
→ source lint
→ asset + GeoGebra validation
→ frozen source snapshot
→ Marp CLI PDF build
→ PDF structural inspection
```

No persistent HTML artifact is allowed. The Marp version is deliberately unpinned; doctor accepts any installed version that passes the probe.

## 7. One full review

```text
authoring
→ review_requested
→ reviewing
→ author_revision
→ release_ready
→ finalized
```

The `full` review has five isolated channels. Each channel submits a report and structured findings. Aggregation hands the historical registry to the author. No incremental/final/acceptance-verification round exists.

The author response must cover every finding exactly. The author then completes the modification checklist and reruns all deterministic checks. This workflow transition does **not** mark findings resolved and does not send revisions back to reviewers.

## 8. Mechanical release

`release_ready` is created from the author's successful post-modification source snapshot and evidence. The release coordinator may fix environment/build failures only. Any required semantic change returns the deck to `author_revision`. A successful release copies PDF, canonical source, review aggregate, findings, author responses, revision note, checklist and deterministic reports into `deliverables/<id>/`.

## 9. Thread lifecycle

Thread states are active, idle reusable, terminal-not-releasable or closed. A thread that authored a deck cannot review it. Handoff validation is required before reuse or close. Runtime close requests that do not release capacity are recorded honestly as reusable, not closed.

## 10. Supervision

Planner supervision is event-aware: it acts after 1200 seconds or a delivery sequence change, whichever occurs first. Coordinators use shorter local intervals and distinguish recent logs, durable file progress, silence and checkpoint age. Inactive future presentations are ignored.
