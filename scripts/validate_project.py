#!/usr/bin/env python3
"""Static release checks, not a substitute for actual integration tests."""
from __future__ import annotations
import ast
import json
import sys
import tomllib
from pathlib import Path
import yaml

root=Path(__file__).resolve().parents[1]
def main():
    errors=[]
    version=(root/'VERSION').read_text().strip()
    if tomllib.loads((root/'pyproject.toml').read_text())['project']['version'] != version:errors.append('Python version mismatch')
    if json.loads((root/'package.json').read_text())['version'] != version:errors.append('Node version mismatch')
    for path in (root/'src').rglob('*.py'):
        try:ast.parse(path.read_text(),filename=str(path))
        except SyntaxError as exc:errors.append(str(exc))
    if len(list((root/'templates'/'compact').glob('*'))) != 3:errors.append('Expected exactly three compact configuration templates')
    profile=yaml.safe_load((root/'templates/compact/TASK-RUNTIME-PROFILE.template.yaml').read_text())
    if profile['runtime_changes_during_task'] != 'forbidden':errors.append('Dynamic runtime enabled')
    if [profile['defaults'][f]['reasoning_effort'] for f in ('planner','author','reviewer')] != ['high','medium','low']:errors.append('Runtime defaults changed')
    if (root/'AGENT.md').exists():errors.append('Duplicate agent entry')
    if not (root/'src/mpres/control/schema.sql').is_file():errors.append('Missing relational schema')
    if len(list((root/'.agents/skills').glob('*/SKILL.md'))) != 6:errors.append('Expected six semantic-only skills')
    if (root/'.codex/agents/author-coordinator.toml').exists():errors.append('Resident author coordinator must be absent')
    if len(list((root/'src/mpres/control/schemas').glob('*.json'))) != 4:errors.append('Expected four semantic schemas')
    print(json.dumps({'version':version,'success':not errors,'errors':errors},indent=2))
    return 1 if errors else 0
if __name__=='__main__':raise SystemExit(main())
