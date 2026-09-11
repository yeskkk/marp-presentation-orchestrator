# Agent entry

Read README.md for the architecture and real implementation boundaries.
The user confirms TASK.md, task.yaml and TASK-RUNTIME-PROFILE.yaml; never choose or
change their model/effort. AI owns semantic planning, writing, editing, independent
review and diagnosis. The runner owns routine execution, gates, status and release.

Only six semantic skills are active. A job packet already contains its one guide,
its result schema and bounded inputs. Do not read all skills or legacy instructions.
Do not generate process records, assign job identities, schedule work or assert
mechanical success. Provider receipts and token counters must be genuine.

Use ./start.sh for interactive Codex or ./start.sh --cli / mpres for mechanical commands.
The launcher never turns off approval/sandbox policy. Manual Codex in this project
uses this same entry: select the task, read its three configuration inputs and
query its database before acting; do not infer the task from an old conversation.
With --task the launcher passes the task planner runtime. Without --task finish
planning only, then let the user reopen --task before production. Starting Codex
is not evidence that worker creation, capabilities or usage reporting work. Main responds to semantic decisions or explicit
user feedback, not healthy polling events. Unknown execution must be reconciled.
A deterministic fixture test is not native-browser or model-quality validation.

When reporting a finished delivery, attach/link the existing path from
`delivery_package` only when its state is `ready`; a PDF commit alone is not ZIP success.

User criticism is durable task data, not chat memory. Record explicit user feedback
in SQLite; never silently retire, weaken or mark it satisfied. Before every author/
reviewer job, the host must complete `brief` with the exact versions and a concrete
readback. The runner then emits `run`. Human attribution is not authentication: only
the user may authorize changing feedback or confirming a repair scope.

For user-directed rework, open a repair case at a delivery boundary. Obtain the
read-only problem expansion, present its exact version/targets/limits to the user,
and STOP for the user's reply. Do not auto-confirm an AI proposal or infer consent
from the initial complaint. Once confirmed, let the runner edit/review/release only
those targets. Attach the completed repair ZIP, not an unreviewed draft. Record
additional user requirements as new feedback versions; never edit runtime choices.

Project source contract applies to every entry, including manually launched Codex:
layout belongs to the installed project theme, never author/editor output. Do not
edit CSS, add HTML/inline SVG, per-slide styles/classes or image sizing tricks.
Use Markdown, mathematics and external assets; split/rewrite dense content. Run
`mpres source check <output>` before submitting. Theme copies are read-only; the
service verifies them and rejects violations before accepting a revision.
