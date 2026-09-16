"""Compact command line; historical authoring lives in Git history."""
from __future__ import annotations

import sys
from mpres.control.cli import build_parser, main as compact_main


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == 'legacy':
        print('Legacy authoring/templates were removed. Recover them from Git history, or use task import-legacy for read-only import into a new compact task.', file=sys.stderr)
        return 2
    return compact_main(argv)
