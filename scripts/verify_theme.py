#!/usr/bin/env python3
"""Native pinned-Marp regression. Never substitutes fake HTML for Marp.

Run after bootstrap --with-figures and npm install:
    python scripts/verify_theme.py --output /path/to/theme-check
Creates an isolated specimen, renders real Marp HTML/PDF, and checks the actual
DOM and PDF. No task, model, screenshot, OCR or user configuration is changed.
A missing tool is a failed check (exit 2), not a pass or a silent fallback.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))

from mpres.control.files import copy_tree
from mpres.geometry import build
from mpres.html_layout import inspect_marp_html_layout
from mpres.math_inspection import inspect_math_renderer, inspect_math_source
from mpres.pdf_inspection import inspect_pdf_file
from mpres.rendering import _marp_command
from mpres.source_policy import POLICY_VERSION, install_theme, require_source
from mpres.toolchain import require_pinned_marp
from mpres.util import run_command


def verify(output: Path, timeout: int = 180) -> dict:
    output = output.resolve()
    if output.exists():
        raise ValueError('Choose a new output directory; previous evidence is never overwritten')
    output.mkdir(parents=True)
    report = {'success': False, 'source_policy_version': POLICY_VERSION,
              'implementation': 'native pinned Marp + Chromium + MathJax + PDF inspection',
              'model_calls': 0, 'checks': {}}
    try:
        report['marp'] = require_pinned_marp(ROOT)
        source = output / 'source'
        copy_tree(ROOT / 'tests/fixtures/project-theme', source, read_only=False)
        build(source / 'assets/intersection.plot.json')
        install_theme(source)
        require_source(source)
        policy = {'marp': {'browser': 'auto'}}
        layout = inspect_marp_html_layout(ROOT, source, policy=policy, timeout=timeout)
        report['checks']['layout'] = layout
        report['checks']['math'] = inspect_math_renderer(inspect_math_source(source), layout)
        pdf = output / 'theme-regression.pdf'
        proc = run_command(_marp_command(ROOT, source, pdf, policy), cwd=source, timeout=timeout)
        report['checks']['render'] = {'success': proc.returncode == 0 and pdf.is_file(),
                                      'returncode': proc.returncode, 'stderr': proc.stderr[-4000:]}
        if report['checks']['render']['success']:
            report['checks']['pdf'] = inspect_pdf_file(pdf, expected_pages=5)
        report['success'] = all(v.get('success') is True for v in report['checks'].values())
    except Exception as exc:
        report['error'] = f'{type(exc).__name__}: {exc}'
    (output / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    return report


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--timeout', type=int, default=180)
    args = p.parse_args()
    try:
        result = verify(args.output, args.timeout)
    except (ValueError, OSError) as exc:
        p.exit(2, f'{exc}\n')
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result['success'] else 2


if __name__ == '__main__':
    raise SystemExit(main())
