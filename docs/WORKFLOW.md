# Workflow and state machine — v0.4.1

## 1. Confirmed task

```text
task_draft → awaiting_user_confirmation → confirmed → working
```

Only `TASK.md` uses a confirmation digest. Material changes require editing and reconfirming it.

## 2. Global runtime policy

`MODEL-POLICY.yaml` is the single repository source of truth:

```yaml
planner: {model: gpt-5.6-sol, reasoning_effort: max}
workers: {model: gpt-5.6-sol, reasoning_effort: high}
```

Task policy and Codex configuration must agree with it.

## 3. Planner-owned assignments and parallel authoring

Every runnable role or stage has request, brief, decision and taskbook files. The planner writes and approves the exact assignment. Course content units are sequential numbered meetings; report units are logical sections. Lesson authors may run in bounded parallel batches.

## 4. Course meeting and time contract

A course unit is `第 N 节课`, not a textbook chapter. Each unit has `LESSON-TIME-PLAN.yaml`:

- nominal class duration;
- prepared material target, normally about 1.5× nominal;
- natural end of the core path;
- optional explanatory worked-example bank;
- explicit permission to stop when class ends.

The ratio is advisory. It is not a hard completion or publication gate.

## 5. Author mechanical gate

Before a review request, and again before release:

```text
canonical presentation.md
→ source/asset/GeoGebra lint
→ frozen source snapshot
→ disposable Marp HTML
→ Playwright scroll/client dimension inspection
→ delete HTML
→ Marp PDF
→ PDF structural inspection
```

Any HTML overflow blocks PDF generation and review submission. Temporary HTML and its report are author/release evidence only; reviewers do not receive or rerun them. No screenshot or model vision is used.

## 6. One full review

```text
authoring → review_requested → reviewing → author_revision → release_ready → finalized
```

The full review has language, domain accuracy, layout/design, pedagogy and audience channels. Layout/design reviewers evaluate hierarchy, density, grouping and presentation design, not mechanical overflow. Findings remain historical statements; after author responses and a successful fresh mechanical build, the deck proceeds directly to release without reviewer verification.

## 7. GeoGebra

Only verified `geogebra.org/m/...` materials may be linked, through ordinary Markdown text links. Reusing the same resource in multiple meetings is allowed and is not a deduplication error.

## 8. Final delivery

The release coordinator repeats the mechanical gate and copies PDF, canonical source, review aggregate, findings, author responses, checklist and reports into `deliverables/<id>/`. Persistent HTML is forbidden.
