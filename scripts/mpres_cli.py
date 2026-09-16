#!/usr/bin/env python3
"""Stable absolute-path entrypoint for workers; no guessed python command."""
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from mpres.cli import main
if __name__=='__main__':raise SystemExit(main())
