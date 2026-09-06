# v0.6.7 → v0.6.8

Use a new compact task directory; never retrofit the legacy live database in place.
`mpres task import-legacy OLD --slug NEW` reads the old SQLite in read-only mode
(or an explicitly unverified JSON projection fallback). It imports source revisions,
including the real v5 `section.md` entrypoint, but not active sessions, lifecycle
success flags or old gate approvals. Source files are preserved byte-for-byte.

Fill blank semantic briefs and check resource paths/runtime/capacity before presenting
and confirming. Imported source revisions remain unverified and are not silently
assigned to succeeded jobs. There is no automatic resume of old external model sessions.

The default CLI is compact. Unconverted old tasks use `mpres legacy ...` (put legacy
before --root). Calling an old API on a compact task fails before it creates a second
state store. Technical render/check modules remain reusable; new automatic production
integration comes in the following stage.

Regression includes the real v5 archive: 8 presentations, 32 units, 8 existing source
revisions imported, no legacy task bytes changed. The import does not create any
assignment triplets or stage folders.
