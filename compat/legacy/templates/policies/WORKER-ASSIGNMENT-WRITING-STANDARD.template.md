# Planner-owned assignment standard

The planner owns assignment semantics. Only writing or revising the top-level `TASK.md` is exclusive to the main agent; batch plans, individual assignments, approvals, policy audits, supervision, and incident decisions may be performed by a delegated planner.

Lesson assignments normally inherit from one approved `BATCH-ASSIGNMENT-PLAN.yaml`. The program may mechanically expand a unit taskbook and structured contract only after the plan is complete and approved. Such expansion counts as planner-written because every semantic field comes from the approved plan; the program may not infer missing scope from coordinator prose or placeholders.

Non-lesson roles use an individual exact assignment written and approved by a main or delegated planner. Every assignment specifies:

- role and presentation/unit/channel coordinates;
- objective, audience state, and prerequisites to reactivate;
- hard constraints, replaceable hypotheses, and local decision rights;
- approved extracted-text or web references;
- required paths, outputs, acceptance tests, stop condition, and prohibited actions.

An individual scaffold remains invalid until all placeholders are removed and `mpres assignment approve` records `written_by: planner`. A lesson assignment expanded from an approved batch records `written_by: planner-via-approved-batch`. Approval records planner authorship; it does not pre-approve worker output.
