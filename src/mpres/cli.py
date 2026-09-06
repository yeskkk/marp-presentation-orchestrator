"""Default compact command line; explicit legacy escape hatch for OLD tasks only."""
from __future__ import annotations

import sys
from mpres.control.cli import build_parser, main as compact_main


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == 'legacy':
        from mpres.legacy_cli import main as legacy_main
        return legacy_main(argv[1:])
    return compact_main(argv)
