# v0.6.8 → v0.6.9

The first Store connection upgrades schema 1 to 2 atomically: persistent pool slots,
actual host observation and an admitted author-concurrency field. Existing config
snapshots, job IDs, attempts and revisions remain unchanged. No model/effort migration.

A v0.6.8 task with existing registered sessions may require attaching those actual
handles to compatible pool slots. They continue to count as occupied until attached;
the runner never silently discards them. A missing/unknown capacity or absent host
usage capability blocks new dispatch. Restore confirmed files rather than changing
runtime in an active task.

New tasks may configure a command adapter before confirmation. Existing tasks whose
confirmed mode is bridge keep using bridge; switching command/runtime during execution
is not allowed. Input context and provider timeout defaults apply if optional budget
fields were absent in the earlier task configuration.

This release runs semantic jobs only. It does not silently adopt a legacy handoff as
passed gates and does not enable automatic final PDF delivery. The full deck workflow
will be a later independently tested refactor stage.
