#!/usr/bin/env python3
"""Check current documentation boundaries, local links and template loading paths.

Only the active surface is checked as current instruction. Archived migration
notes and verbatim compatibility templates are not silently declared current.
"""
from __future__ import annotations
import json
import re
from pathlib import Path
from urllib.parse import unquote, urlsplit

CONFIGS = {'TASK.template.md','task.template.yaml','TASK-RUNTIME-PROFILE.template.yaml'}
LEGACY_LOADERS = ['control_jobs','production','review','revision_routing','tasks','maintenance','stages','course_consistency','diagnostics']


def check(root: Path) -> dict:
    root=root.resolve();errors=[]
    current={p.name for p in (root/'templates/compact').glob('*') if p.is_file()}
    if current != CONFIGS:errors.append('Expected exactly three active configuration templates')
    for p in (root/'templates').iterdir():
        if p.name not in {'README.md','compact'}:errors.append(f'Unclassified active template path: {p.relative_to(root)}')
    if not (root/'compat/legacy/templates/TASK.template.md').is_file():
        errors.append('Missing explicit compatibility template archive')
    for name in LEGACY_LOADERS:
        text=(root/f'src/mpres/{name}.py').read_text()
        if re.search(r'root\s*/\s*[\"\']templates[\"\']',text):
            errors.append(f'Legacy loader reads the current template root: {name}')
    names={p.parent.name for p in (root/'.agents/skills').glob('*/SKILL.md')}
    files=[root/'README.md',root/'AGENTS.md',root/'templates/README.md']
    files+=list((root/'docs').glob('*.md'))
    # Historic migration notes carry historic paths, not current operational links.
    files=[p for p in files if not p.name.startswith('MIGRATION-')]
    files+=list((root/'.agents/skills').rglob('*.md'))
    for p in files:
        if not p.is_file():errors.append(f'Missing active document: {p.relative_to(root)}');continue
        text=p.read_text(encoding='utf-8')
        text=re.sub(r'(?ms)^(`{3,}|~{3,}).*?\n.*?^\1\s*$', '',text)
        for target in re.findall(r'(?<!!)\[[^\]\n]+\]\(([^\s)]+)\)',text):
            parsed=urlsplit(target)
            if parsed.scheme or parsed.netloc or not parsed.path:continue
            candidate=(p.parent/unquote(parsed.path)).resolve()
            if not candidate.is_relative_to(root) or not candidate.exists():
                errors.append(f'Broken/local-outside link in {p.relative_to(root)}: {target}')
    return {'success':not errors,'errors':errors,'active_documents_checked':len(files),
            'active_configuration_templates':len(current),
            'legacy_templates':sum(p.is_file() for p in (root/'compat/legacy/templates').rglob('*')),
            'semantic_skills':len(names)}

if __name__=='__main__':
    result=check(Path(__file__).resolve().parents[1]);print(json.dumps(result,ensure_ascii=False,indent=2))
    raise SystemExit(0 if result['success'] else 1)
