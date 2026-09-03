---
name: presentation-defect-triage
description: Diagnose a user-reported presentation defect from a bounded read-only slide subset before authorizing any patch.
---

# Presentation defect triage

Use this skill when the user points out a specific problem in one or more slides or page numbers during production or after publication.

1. Run `mpres diagnostic open` with the verbatim user report and the smallest known slide/page set. The default neighbor radius is one and may not exceed two. The control plane copies only the target slides, neighbors, selected structured records, and filtered existing gate evidence. It never copies or opens a PDF.
2. A planner completes and approves `TASK-DIAGNOSTIC-REVIEWER.md`. The diagnostic reviewer reads only the case evidence and writes only `response/DIAGNOSTIC-RESULT.yaml`.
3. Runtime comes from the immutable task-level profile. `diagnostic-reviewer` uses the reviewer family unless the user configured a specific role override before confirmation. The agent never changes runtime because a problem appears easy or difficult.
4. Diagnosis is read-only. Require root-cause hypotheses, exact slide-ID evidence, confidence, affected slides, remaining uncertainty, and a recommended action.
5. If evidence is insufficient, open a new case with an explicitly larger slide set or select full corrective review. The reviewer may not widen context by itself.
6. `mpres diagnostic submit` validates the result and generates `PATCH-SCOPE.yaml`. This file is only a proposal. A planner must authorize a later author or maintenance contract. No diagnostic command edits presentation source.
7. After any later patch, run changed-slide and neighbor checks first, then the normal complete source, layout, PDF, and release gates. Historical releases remain unchanged.
