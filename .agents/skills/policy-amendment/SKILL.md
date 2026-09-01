---
name: policy-amendment
description: Convert every material policy change—including a confirmed workflow-engine technical bug—into a TASK amendment requiring reconfirmation.
---

# Policy amendment

A task may not silently change its review policy, roles, production profile, assignment ownership, output, reference access, model defaults, MCQ requirements, audience, or scope.

A confirmed workflow-engine technical bug also does not authorize an in-task hotfix. Record `ENGINE-INCIDENT.yaml`, propose a `workflow_engine_technical_fix` amendment, identify the blocked behavior and temporary task-level consequences, revise top-level `TASK.md`, present it again, and require user reconfirmation before continuing. Engine code refactoring and regression-test work are a separate task.

Only the main agent writes or revises `TASK.md`; a delegated planner may prepare the incident, amendment proposal, evidence, and policy audit. Sidecars do not replace the reconfirmed task contract.
