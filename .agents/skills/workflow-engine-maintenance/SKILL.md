---
name: workflow-engine-maintenance
description: Diagnose workflow-engine defects and prepare a separate refactoring task without hot-patching an active courseware task.
---

# Workflow-engine maintenance

When behavior suggests an engine defect, reproduce it deterministically, distinguish it from content or policy error, and record versions, commands, expected/actual behavior, affected task state, and a safe stop point in `ENGINE-INCIDENT.yaml`.

Do not edit engine source, add regression tests, or continue through an improvised local workaround inside the active task. Propose the required task policy amendment and reconfirm `TASK.md`. Engine repair remains separate work. The active task may resume only through an exact reversible operational workaround that was presented with TASK.md, explicitly reconfirmed by the user, and later operator-verified.

## v0.6.5 recurrence control

Record every occurrence under the same stable incident ID. A repeated deterministic occurrence
opens the task-production circuit. Prepare an exact reversible workaround before reconfirmation;
do not retry every deck through the same known failure or let an agent choose a runtime workaround.
