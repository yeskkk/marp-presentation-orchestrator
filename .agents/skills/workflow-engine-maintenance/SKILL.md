---
name: workflow-engine-maintenance
description: Diagnose workflow-engine defects and prepare a separate refactoring task without hot-patching an active courseware task.
---

# Workflow-engine maintenance

When behavior suggests an engine defect, reproduce it deterministically, distinguish it from content or policy error, and record versions, commands, expected/actual behavior, affected task state, and a safe stop point in `ENGINE-INCIDENT.yaml`.

Do not edit engine source, add regression tests, or continue through a local workaround inside the active task. Propose the required task policy amendment and reconfirm `TASK.md`. Perform the engine repair, tests, release, and migration guidance as separate work, then resume the courseware task under the amended contract.
