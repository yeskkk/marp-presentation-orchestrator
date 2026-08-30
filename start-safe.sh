#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"
"${PYTHON_BIN:-python3}" scripts/bootstrap.py
export MPRES_ROOT="$ROOT"
export PATH="$ROOT/.venv/bin:$ROOT/node_modules/.bin:$PATH"
PROMPT='Read AGENTS.md, docs/WORKFLOW.md, and the marp-presentation-workflow skill. Run startup checks and continue a valid active task. If none exists, conduct the compact presentation questionnaire and explicitly warn about three mandatory rounds, no screenshots/model vision, medium default reasoning, PDF-only Marp output, disabled-by-default Python figures, optional GeoGebra-only hyperlink enrichment, and pilot/each/all delivery choices. Do not initialize production before the exact TASK.md is confirmed.'
exec codex --strict-config --cd "$ROOT" --sandbox workspace-write --ask-for-approval on-request --search "$PROMPT"
