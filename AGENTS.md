# Agent entry

Read README.md for architecture and current implementation boundaries.

For a new task use the compact `mpres task` interface. The user edits and confirms
TASK.md, task.yaml and TASK-RUNTIME-PROFILE.yaml. Never choose or change runtime
on the user's behalf. Semantic work means planning, writing, editing, independent
review or diagnosis. Do not generate assignment triplets, stage essays, registry
projections, or self-declared gate receipts. Submit content and semantic results.

The database generates job/attempt identities. Use only IDs returned by the
service. Execution/creation receipts must come from the actual provider. Do not
invent close support, released capacity, gate success, token counts or completion.

Legacy commands are explicitly opt-in and cannot address a compact task. Legacy
operating instructions in docs/legacy are for unconverted old tasks only; the old
management skills are not required inputs for compact jobs.

This is a staged refactor. In v0.6.9 the compact data and semantic-job runner
are operational. Use runner commands rather than making scheduling decisions in
model turns. Command mode requires a real user-configured JSON adapter; bridge mode
forwards exact requests and actual receipts. A test adapter is not a real provider.
Full deck gate/review/revision/release integration is still a following stage.
Never claim accepted writing jobs are validated or finalized presentations.
