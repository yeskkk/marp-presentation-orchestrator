#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"
"${PYTHON_BIN:-python3}" scripts/bootstrap.py
export MPRES_ROOT="$ROOT"
export PATH="$ROOT/.venv/bin:$ROOT/node_modules/.bin:$PATH"
PROMPT='Read AGENTS.md, docs/WORKFLOW.md, and the marp-presentation-workflow skill. Run startup checks and continue a valid active task. If none exists, conduct the compact presentation questionnaire and explicitly explain: one mandatory full-deck five-channel review; no reviewer recheck after the author completes the revision workflow; screenshots/model vision and original reference-PDF access are forbidden; workers default to gpt-5.6-sol with high reasoning; every course lesson needs 2–3 diagnostic multiple-choice prompt/answer pairs while academic reports are exempt; output is Marp PDF only; Python figures are disabled by default; GeoGebra enrichment is hyperlink-only; and delivery choices are pilot/each/all. The main planner personally writes and approves every exact assignment. Do not initialize production before the exact TASK.md is confirmed.'
exec codex --strict-config --cd "$ROOT" --sandbox workspace-write --ask-for-approval on-request --search "$PROMPT"
