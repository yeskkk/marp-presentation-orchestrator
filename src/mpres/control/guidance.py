"""Select narrowly scoped semantic instructions from the installed source tree.

One shared contract, one role, and only applicable mode/channel sections. No
recursive documentation scan, legacy fallback, truncation, or new task state.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from mpres.util import MPresError

GUIDANCE_VERSION = '0.8.3'
ROLE_GUIDES = {
    'write': 'marp-writing', 'edit': 'deck-editing', 'revise': 'deck-editing',
    'diagnose': 'problem-diagnosis',
}
REVIEW_GUIDES = {
    'domain_accuracy': 'domain-accuracy-review',
    'pedagogy': 'pedagogy-review',
    'audience': 'audience-review',
    'language': 'language-review',
    'layout': 'layout-review',
}
CHANNELS = set(REVIEW_GUIDES)
SHARED = '_shared/learning-contract.md'


def skill_root(root: Path) -> Path:
    """Choose one complete source tree, never mix old/new files across trees."""
    candidate = root / '.agents' / 'skills'
    if candidate.is_dir():
        return candidate.resolve()
    installed = Path(__file__).resolve().parents[3] / '.agents' / 'skills'
    if not installed.is_dir():
        raise MPresError('Install the source checkout with its semantic skills')
    return installed.resolve()


def read_fragment(base: Path, relative: str, section: str | None = None) -> str:
    path = (base / relative).resolve()
    if not path.is_relative_to(base.resolve()) or not path.is_file():
        raise MPresError(f'Missing or unsafe semantic guide: {relative}')
    text = path.read_text(encoding='utf-8')
    if text.startswith('---\n'):
        parts = text.split('---', 2)
        if len(parts) != 3:
            raise MPresError(f'Unclosed skill metadata: {relative}')
        text = parts[2]
    if section is not None:
        headings = list(re.finditer(r'^## ([a-z_]+)\s*$', text, re.M))
        found = [(i, match) for i, match in enumerate(headings) if match.group(1) == section]
        if len(found) != 1:
            raise MPresError(f'Missing/duplicate semantic section: {relative}#{section}')
        index, match = found[0]
        text = text[match.end():headings[index+1].start() if index+1 < len(headings) else len(text)]
    if not text.strip():
        raise MPresError(f'Empty semantic guide: {relative}')
    return text.strip()


def assemble(root: Path, fragments: list[tuple[str, str | None]], mode: str) -> dict[str, Any]:
    base = skill_root(root)
    unique = list(dict.fromkeys(fragments))
    sources = ['.agents/skills/' + path + (f'#{section}' if section else '')
               for path, section in unique]
    # Full selected fragments count toward the existing context budget. Never truncate.
    text = '\n\n'.join(read_fragment(base, path, section) for path, section in unique)
    return {'text': text, 'sources': sources, 'mode': mode, 'version': GUIDANCE_VERSION,
            'bytes': len(text.encode('utf-8'))}


def compile_guidance(root: Path, kind: str, *, channel: str | None = None,
                     repair: bool = False, correction: bool = False) -> dict[str, Any]:
    if kind == 'review':
        if channel not in REVIEW_GUIDES:
            raise MPresError('A review needs one assigned channel; never guess or load all five')
        role = REVIEW_GUIDES[channel]
    else:
        if kind not in ROLE_GUIDES:
            raise MPresError('No semantic guide for a mechanical job')
        role = ROLE_GUIDES[kind]
    fragments = [(SHARED, None), (f'{role}/SKILL.md', None)]
    mode = kind
    if kind == 'edit':
        selected = 'correction' if correction else 'integration'
        fragments.append(('deck-editing/references/modes.md', selected)); mode = selected
    elif kind == 'revise':
        fragments.append(('deck-editing/references/modes.md', 'revision')); mode = 'revision'
        if correction:
            fragments.append(('deck-editing/references/modes.md', 'correction'))
    elif kind == 'write' and correction:
        fragments.append(('deck-editing/references/modes.md', 'correction')); mode = 'write-correction'
    elif kind == 'review':
        mode = 'review:' + channel
    elif kind == 'diagnose':
        selected = 'expansion' if repair else 'bounded'
        fragments.append(('problem-diagnosis/references/modes.md', selected)); mode = 'diagnose:' + selected
    if repair and kind in {'edit', 'revise'}:
        fragments.append(('deck-editing/references/modes.md', 'repair'))
    elif repair and kind == 'review':
        fragments.append(('_shared/review-scope.md', None))
    return assemble(root, fragments, mode)


def audience_guidance(root: Path, phase: str, *, introduce: bool = False) -> dict[str, Any]:
    if phase not in {'student', 'production_language'}:
        raise MPresError('Unknown audience guidance phase')
    fragments = [(SHARED, None), ('audience-review/SKILL.md', None)] if introduce else []
    fragments.append(('audience-review/references/steps.md', phase))
    return assemble(root, fragments, 'audience:' + phase)


def audience_synthesis_guidance(root: Path, *, repair: bool = False, introduce: bool = False) -> dict[str, Any]:
    fragments = [(SHARED, None), ('audience-review/SKILL.md', None)] if introduce else []
    fragments.append(('audience-review/references/steps.md', 'synthesis'))
    if repair:
        fragments.append(('_shared/review-scope.md', None))
    return assemble(root, fragments, 'review:audience:synthesis')


def attach_guidance(packet: dict, bundle: dict[str, Any]) -> None:
    packet['semantic_guidance'] = bundle['text']
    packet['semantic_guidance_sources'] = bundle['sources']
    packet['semantic_guidance_mode'] = bundle['mode']
    packet['semantic_guidance_version'] = bundle['version']
