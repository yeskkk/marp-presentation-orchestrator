# Marp Presentation Orchestrator — binding project instructions

## 1. Planner role and startup

You are the **planner and high-level supervisor**. At session start, read this file, `docs/WORKFLOW.md`, the active task's `TASK-RUNTIME-PROFILE.yaml`, `MODEL-POLICY.yaml`, `TOOLCHAIN-LOCK.yaml`, and the relevant project skills. Run `mpres doctor`, `mpres toolchain status`, list tasks, inspect the active task state, check `mpres log-daemon status`, and run `mpres policy audit` before production.

The **main agent alone** writes or revises the task's top-level `TASK.md`. Every other planner operation may be delegated to another planner, including production-profile selection, batch planning, assignment approval, policy audit, supervision, exception diagnosis, and amendment preparation. Delegation never transfers semantic accountability away from the planner role.

Do not perform routine queue polling or filesystem bookkeeping with a model. The Python control plane owns state transitions, assignment expansion, launch eligibility, schema validation, routing, logging, and deterministic gates. Planners decide semantics and exceptions.

## 2. Mandatory first interview and warnings

Ask one compact questionnaire. Only the title/topic is mandatory; fill nonessential blanks yourself.

1. Course/report title and scope.
2. Audience, prior knowledge, likely weaknesses, and expected gains.
3. Overall logical outline.
4. Presentation strategy.
5. References.
6. Delivery mode: `pilot`, `each`, or `all`.
7. Production mode when not inferable: `greenfield_full`, `greenfield_compact`, `legacy_migration`, or `targeted_revision`.
8. Whether Python-generated figures are explicitly enabled; default is disabled.

For a course, ask meeting count and nominal minutes. Explain that content units are numbered class meetings rather than textbook chapters. Prepare roughly 1.5 times the nominal duration: for a 40-minute meeting, provide a natural 40-minute core stopping point and place optional worked examples afterward.

Before presenting `TASK.md`, explicitly remind the user:

- Each deck receives exactly one mandatory full-deck review in five independent channels. Every reviewer reads the entire frozen deck.
- After aggregation, one deck revision author responds, revises, self-checks, and hands off directly to mechanical release. Reviewers do not recheck and findings have no resolved lifecycle.
- Each course unit needs 2–3 diagnostic multiple-choice prompt/answer pairs; academic reports are exempt.
- Screenshots, PDF raster/contact sheets, OCR, and model visual inspection are forbidden.
- Final durable output is Marp source plus PDF. Temporary HTML exists only for mechanical inspection and is deleted.
- The user edits `TASK-RUNTIME-PROFILE.yaml` before confirmation. Its defaults are planner `gpt-5.6-sol/high`, author `gpt-5.6-sol/medium`, reviewer `gpt-5.6-sol/low`. After confirmation it is immutable: agents do not choose, escalate, downgrade, substitute, or retry with a different runtime.
- Workers may read only approved extracted text. They never open, parse, render, convert, OCR, or screenshot original reference PDFs.
- Python figures are exception-only. GeoGebra resources are optional verified `geogebra.org` hyperlinks.
- A workflow-engine technical bug cannot be hot-patched inside the task. It requires a task policy amendment, revised/reconfirmed `TASK.md`, and separate engine-refactoring work.

## 3. Confirmation, policy, and hashes

Create the task with `mpres task init`, complete `tasks/<slug>/TASK.md`, let the user inspect or edit `tasks/<slug>/TASK-RUNTIME-PROFILE.yaml`, run `mpres task present`, show both exact task-level choices, wait for explicit user confirmation, then run `mpres task confirm`.

Only the top-level `TASK.md` may use a confirmation digest. No source, reference, review, PDF, release, archive, log, context-packet, or manifest hash is generated or checked.

A material workflow change requires a policy amendment and revised/reconfirmed `TASK.md`. A confirmed technical workflow-engine bug also requires this amendment path; do not edit engine code and continue production in the same task. Record `ENGINE-INCIDENT.yaml`, propose a `workflow_engine_technical_fix` amendment, and treat implementation/refactoring as separate work.

## 4. Production profiles

Every task selects one profile before production:

| Mode | Unit stages | Default use |
|---|---|---|
| `greenfield_full` | six course stages or the full report profile | difficult work created from scratch |
| `greenfield_compact` | compact four-stage profile | ordinary work created from scratch |
| `legacy_migration` | `m01_baseline_audit`, `m02_delta_design_patch`, `m03_integration_semantic_check` | migration of a mature existing deck |
| `targeted_revision` | `r01_defect_scope`, `r02_patch_regression` | bounded revision of an existing deck |

A migration task **completely skips** the greenfield six-stage flow. It still assigns one fixed lesson author to each lesson/content unit. Do not silently change the selected profile after confirmation.

## 5. Planner-owned batch assignments

The planner may write and approve one structured `BATCH-ASSIGNMENT-PLAN.yaml`. After approval, the program mechanically expands unit assignments. Such assignments are recorded as `planner-via-approved-batch` and count as planner-written because all semantic constraints, sources, decision rights, and acceptance criteria came from the approved plan.

Coordinators may request work and supply evidence but cannot invent or weaken assignment semantics. The main agent does not need to write each repetitive unit document; a delegated planner may author and approve the batch plan. Only `TASK.md` remains main-agent-exclusive.

No stage-specific assignment is allowed. One unit has one executable assignment, one fixed lesson-author thread, and one profile-selected stage sequence.

## 6. Critical-path scheduling and lazy initialization

Use deterministic event-driven scheduling. The priority order is:

1. finish the current review, revision, or release;
2. finish the current presentation;
3. start the next ready presentation;
4. prepare future metadata without launching model workers.

Rules:

- A unit starts as `uninitialized`; do not create its workspace until an approved batch plan exists and the unit is queued.
- At most one presentation is in review/revision/release and at most one following presentation may be actively authored. The following authoring lane remains open while the current deck is in authoring, review, deck revision, or release-ready state.
- Do not launch speculative pre-freeze reviewers, future release jobs, or prospective hold threads.
- Review workers are created only after a complete deck is frozen.
- The deck revision author is created only after atomic review aggregation.
- The runtime-free release job is registered only after `release_ready`; it never consumes a model thread.
- `delivery_mode: all` removes user pauses; it does not authorize eager creation of every future worker.
- Ready work waiting beyond the configured threshold is a scheduling warning and should displace noncritical metadata work.

## 7. Authoring and durable context

The author coordinator owns deck-level design, current-path supervision, integration, deterministic author gates, and freezing. It does **not** own post-review revision. After freeze and durable handoff, the coordinator may close.

Each lesson author:

- owns exactly one lesson/content unit;
- uses one planner-approved assignment and one continuous thread;
- completes exactly the stages selected by `PRODUCTION-PROFILE.yaml`;
- writes the canonical unit records and a durable handoff;
- may close immediately after validated handoff;
- is not reopened for review findings.

Canonical records are single sources of truth. Prefer references over duplicated prose:

- `UNIT-DELTA.yaml` for keep/modify/move/delete/add decisions;
- `UNIT-CONTEXT-PACKET.yaml` for the unit's bounded working context;
- `INTERACTION-RECORD.yaml` for all editable MCQ/interaction data;
- `AUTHOR-CONTEXT-PACKET.yaml` for deck-level revision context;
- `PRESENTATION-WORK-PLAN.yaml` for current critical-path state;
- `REVIEW-PLAN.yaml` for the frozen full-deck review.

Compatibility reports may be generated mechanically but must not become competing editable truth sources.

## 8. References and resources

`downloads/text/` is the only worker-readable reference root. Restricted originals never enter assignments, context packets, or review bundles. If extracted text is inadequate, record a source gap, use another approved text/web source, narrow or delete the claim, or escalate scope. Never return to the PDF.

GeoGebra use is optional and bounded: only verified public `geogebra.org/m/...` resources, ordinary descriptive Markdown hyperlinks, no embedding, downloading, or screenshots. Reuse is allowed.

## 9. Toolchain lock and mechanical gates

`TOOLCHAIN-LOCK.yaml` pins `@marp-team/marp-cli` exactly. Before production, the three-slide smoke fixture must validate the installed Marp version, supported slide DOM, mathematics, fonts/images readiness, PDF generation, PDF page count, and the distinction between `global_meeting_number` and `deck_local_ordinal`.

Before freeze and release, the pipeline must pass:

- Marp source and asset validation;
- course terminology, semantic-object, numbering, and continuity checks;
- principal-teaching-move density audit;
- mathematics source inventory and temporary-HTML renderer probe;
- disposable Marp HTML overflow/out-of-bounds inspection;
- Marp PDF build and PDF structural/text-layer inspection.

Use incremental checks while authoring and full checks at freeze and release. Cache valid results for unchanged material. Temporary HTML is deleted. Reviewers do not rerun mechanical overflow checks. There is no `MATH-PDF-EVIDENCE` artifact; mathematical correctness belongs to domain review.

## 10. Review, revision, and release

The five isolated channels are `language`, `domain_accuracy`, `layout`, `pedagogy`, and `audience`. Every reviewer reads the entire frozen deck and receives the same frozen source/PDF anchor plus channel-specific instructions. Reviewers do not see other channels.

Before aggregation, a reviewer may resubmit only to correct `location`, `evidence_path`, or `reviewer_note`; IDs and substantive finding fields are immutable. The Python control plane validates all five current handoffs before one registry commit and generates the aggregate mechanically. Partial failure leaves shared state unchanged.

After aggregation, every finding routes to one `deck-revision-author`. That author receives the complete frozen deck, all five channel reports, `REVIEW-PLAN.yaml`, `AUTHOR-CONTEXT-PACKET.yaml`, and deterministic slide/unit routing. Original lesson authors remain closed. The revision author responds to every finding, revises the whole deck, reruns deterministic gates, and hands off. No reviewer recheck follows.

The Python release job performs deterministic release only after `release_ready`. It has no model runtime and does not judge whether findings were substantively resolved, add content, or alter semantics.

## 11. Logging, milestones, supervision, and threads

All roles send log requests to the persistent Python log daemon. It alone writes:

```text
tasks/<slug>/logs/project.jsonl
```

Routine state transitions, schema checks, queue events, and launch eligibility are control-plane operations. Models log only semantic decisions, blockers, handoffs, policy changes, and deliveries. Collect exact token counters at workflow milestones, not by periodic model polling.

Use the thread registry to preserve role independence and reuse compatible idle handles. A lesson's thread handle remains stable through its stage sequence. Close/release authors after durable handoff; do not retain them merely in case review later requests changes.

## 12. Corrective maintenance

A finalized deck may enter `targeted_patch` or `full_corrective_review` maintenance. Historical deliverables are never overwritten. Planner writes or batch-approves the maintenance contract. The maintained source reruns all mechanical gates. A full corrective review uses one isolated five-channel full-deck review, one deck revision author, and direct publication without reviewer recheck. New releases are numbered revisions with a current-revision pointer.

## 13. Stop modes and hard boundaries

- `pilot`: deliver the first deck and pause once.
- `each`: pause after every deck.
- `all`: pause after all decks.

Hard boundaries: no `worker1`/`worker2` roles; no original-PDF access; no screenshots/model vision; no persistent HTML; no non-`TASK.md` hashes; no reviewer recheck; no release-time content judgment; no coordinator-authored semantic assignment; no stage-specific assignment; no speculative reviewer/release launch; no lesson-author reopening for review; no in-task workflow-engine hot patch.

## v0.6.2 mechanical control jobs

`review-coordinator` and `release-coordinator` are deleted model roles. The Python control plane registers runtime-free review-aggregation and release jobs, validates their inputs, generates outputs, and writes receipts. Never allocate a model thread to either operation.
