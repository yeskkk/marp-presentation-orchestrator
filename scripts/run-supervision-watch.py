#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

from mpres.supervision import watch_supervision
from mpres.util import find_repo_root


def main() -> int:
    parser = argparse.ArgumentParser(description="Event-aware Marp presentation supervision.")
    parser.add_argument("slug")
    parser.add_argument("--scope", choices=["planner", "author", "review"], default="planner")
    parser.add_argument("--presentation")
    parser.add_argument("--poll-seconds", type=int)
    parser.add_argument("--iterations", type=int)
    parser.add_argument("--root", type=Path)
    args = parser.parse_args()
    root = args.root.resolve() if args.root else find_repo_root()
    watch_supervision(root, args.slug, scope=args.scope, presentation_id=args.presentation, interval=args.poll_seconds, iterations=args.iterations)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
