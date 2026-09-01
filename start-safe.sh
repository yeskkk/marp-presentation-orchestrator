#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"
"${PYTHON_BIN:-python3}" scripts/bootstrap.py
export MPRES_ROOT="$ROOT"
export PATH="$ROOT/.venv/bin:$ROOT/node_modules/.bin:$PATH"
"$ROOT/.venv/bin/python" -m mpres.log_daemon start --root "$ROOT" >/dev/null
PROMPT='Read AGENTS.md, docs/WORKFLOW.md, MODEL-POLICY.yaml, TOOLCHAIN-LOCK.yaml, and the relevant skills. Run the strict startup checks and continue a valid active task. If none exists, conduct the compact questionnaire and explain the binding policy: choose an explicit production profile; legacy migrations use exactly three migration stages while keeping one fixed author per lesson; every deck receives five isolated full-deck reviews and every reviewer reads the entire frozen deck; one deck revision author handles all findings after lesson authors close; reviewers do not recheck; screenshots/model vision and original-PDF worker access are forbidden; the main agent alone writes or revises TASK.md, but all other planner work may be delegated to max-reasoning planners; an approved batch plan may be mechanically expanded into exact unit assignments; review, revision, and release workers are created only when their gates are reached; the exact pinned toolchain must pass its smoke test; confirmed engine bugs require a policy amendment and separate repair work, never an in-task hot-patch; course lessons need 2–3 diagnostic MCQ prompt/answer pairs; output is Marp PDF; Python figures are disabled by default; GeoGebra is hyperlink-only; delivery modes are pilot/each/all. Use the persistent project log daemon. Do not initialize production before exact TASK.md confirmation.'
exec codex --strict-config --cd "$ROOT" --sandbox workspace-write --ask-for-approval on-request --search "$PROMPT"
