# Diagnostic reviewer assignment — [[PRESENTATION_ID]] / [[CASE_ID]]

## User report

[[USER_REPORT]]

## Exact evidence boundary

Read only the bounded, read-only evidence packet under:

`[[EVIDENCE_ROOT]]`

It contains the reported slide or page, a small number of neighboring slides, selected manifest/interaction/density records, and filtered excerpts from machine-readable gate reports when available. It intentionally does not contain the full deck. Do not search the wider presentation merely because more context might be convenient.

Use the runtime selected by the user in `[[RUNTIME_PROFILE_PATH]]` for the `diagnostic-reviewer` role. That role belongs to the reviewer runtime family unless the user added a more specific override before task confirmation. Never select, escalate, downgrade, substitute, or retry with another model or reasoning strength.

## Required diagnostic method

1. Restate the observed defect precisely rather than immediately proposing new wording.
2. Separate evidence from hypotheses. Every root-cause hypothesis must cite one or more slide IDs that exist in the evidence packet.
3. Consider only evidence-supported causes such as mathematical/domain correctness, pedagogy, audience assumptions, language, source-level layout structure, continuity, interaction design, or a mismatch between source and a deterministic gate report.
4. Do not render or open any PDF, make screenshots, use OCR or model vision, fetch unrelated files, or inspect original reference documents.
5. Do not edit canonical presentation source, structured author records, task policy, assignments, or evidence files. Write only the result file below.
6. If the bounded packet is insufficient, set `scope_expansion_required: true`, recommend `open_larger_diagnostic_case` or `full_corrective_review`, identify the uncertainty, and stop. Do not widen the scope yourself.
7. A proposed patch scope is advisory and must stay within the included slide IDs. It never authorizes a source edit. A planner must authorize a later author or maintenance task, and any patch still requires local changed-slide checks plus the normal full-deck gate.

## Output

Complete exactly:

`[[RESULT_PATH]]`

The result must include a substantive summary, evidence-backed root-cause hypotheses, confidence, affected slide IDs, whether scope expansion is required, one allowed recommended action, and a bounded proposed patch scope. Record `source_modified: false`.

## Planner-owned case constraints

[[PLANNER_DIAGNOSTIC_CONSTRAINTS]]
