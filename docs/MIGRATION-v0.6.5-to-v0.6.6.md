# Migration from v0.6.5 to v0.6.6

v0.6.6 changes only the handling of user-reported, slide-local presentation defects. Existing runtime profiles, production state, deliveries, transactions, and incident records require no migration.

## New role and command surface

`diagnostic-reviewer` maps to the reviewer runtime family. Existing tasks therefore use their already confirmed reviewer default unless the user had explicitly configured a role override before confirmation. Do not edit a confirmed runtime profile merely to open a diagnostic case.

Use:

```bash
mpres diagnostic open <slug> --presentation <id> \
  --report "<verbatim user report>" --slide <slide-id> --neighbor-radius 1
mpres diagnostic status <slug> --presentation <id>
mpres diagnostic submit <slug> --presentation <id> --case-id <case-id>
```

## Safety and scope

The control plane resolves the current source state and copies only selected Marp slides plus bounded neighbors, related structured records, and existing machine-readable gate excerpts. It does not open or copy PDFs. The diagnostic assignment must be planner completed and approved before submission. The reviewer cannot edit source, widen context, or change runtime.

`PATCH-SCOPE.yaml` is not an assignment. A planner must separately authorize any patch or corrective-maintenance operation, and normal local plus full-deck gates remain mandatory. If evidence is insufficient, open a new explicitly wider case or use full corrective review.
