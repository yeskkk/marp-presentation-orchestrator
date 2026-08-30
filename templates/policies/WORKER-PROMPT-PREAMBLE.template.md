# CACHE-STABLE WORKER PROMPT PREFIX — DO NOT EDIT OR PREPEND TEXT

Repository: [[REPOSITORY_PATH]]
Task: [[TASK_SLUG]]
Confirmed plan: tasks/[[TASK_SLUG]]/TASK.md
Execution policy: tasks/[[TASK_SLUG]]/EXECUTION-POLICY.yaml
Review profile: tasks/[[TASK_SLUG]]/REVIEW-PROFILE.yaml
Marp standard: tasks/[[TASK_SLUG]]/MARP-AUTHORING-STANDARD.md

Global rules:
- three mandatory review rounds and five specialist channels;
- no screenshots and no model visual inspection;
- Marp Markdown to PDF only; no persistent HTML artifact;
- no hashes except the top-level TASK.md confirmation gate;
- Python-generated figures are disabled unless TASK and ASSET-DECISIONS explicitly allow them;
- durable UTC logs and checkpoints;
- role boundaries are binding.

Read the exact role assignment named after this prefix. Do not infer another role's responsibilities.
