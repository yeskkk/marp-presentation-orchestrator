#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON="${PYTHON_BIN:-$ROOT/.venv/bin/python}"
if ! command -v "$PYTHON" >/dev/null 2>&1; then
  echo "Install first: python scripts/bootstrap.py --with-figures (or set PYTHON_BIN)." >&2
  exit 2
fi
export MPRES_ROOT="$ROOT"
# A source checkout must never import a different editable installation.
export PYTHONPATH="$ROOT/src${PYTHONPATH:+:$PYTHONPATH}"
exec "$PYTHON" -m mpres.startup --root "$ROOT" "$@"
