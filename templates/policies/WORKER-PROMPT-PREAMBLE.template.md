# CACHE-STABLE WORKER PROMPT PREFIX — DO NOT EDIT OR PREPEND TEXT

Repository: [[REPOSITORY_PATH]]
Task: [[TASK_SLUG]]
Confirmed plan: tasks/[[TASK_SLUG]]/TASK.md
Execution policy: tasks/[[TASK_SLUG]]/EXECUTION-POLICY.yaml
Review profile: tasks/[[TASK_SLUG]]/REVIEW-PROFILE.yaml
Marp standard: tasks/[[TASK_SLUG]]/MARP-AUTHORING-STANDARD.md

Global rules:
- one mandatory full-deck review round with five independent specialist channels;
- no screenshots and no model visual inspection;
- Marp Markdown to PDF only; no persistent HTML artifact;
- no hashes except the top-level TASK.md confirmation gate;
- Python-generated figures are disabled unless TASK and ASSET-DECISIONS explicitly allow them;
- durable UTC logs and checkpoints;
- role boundaries are binding;
- every exact worker assignment is written by the main planner; a coordinator may validate and
  supervise it but may not create, complete, rewrite, or weaken it.

Read the exact planner-written role assignment named after this prefix. If its planner-only brief is
missing, incomplete, or still a placeholder, stop and report the assignment defect. Do not infer
another role's responsibilities.
