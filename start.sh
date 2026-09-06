#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON="${PYTHON_BIN:-$ROOT/.venv/bin/python}"
if [[ ! -x "$PYTHON" ]]; then
  echo "Install first: python scripts/bootstrap.py (or set PYTHON_BIN to the project environment)." >&2
  exit 2
fi
export MPRES_ROOT="$ROOT"
if [[ $# -eq 0 ]]; then set -- --help; fi
exec "$PYTHON" -m mpres --root "$ROOT" "$@"
