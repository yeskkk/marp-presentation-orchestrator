"""Four semantic result schemas; six guides, with no workflow instructions to AI."""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from jsonschema import Draft202012Validator

from mpres.util import MPresError, SubmissionRejected

SCHEMAS = {'plan','author-result','review-result','diagnosis-result'}
GUIDES = {'write':'marp-writing','edit':'deck-editing','revise':'deck-editing',
          'review':'specialist-review','diagnose':'problem-diagnosis'}


@lru_cache(maxsize=4)
def schema(name: str) -> dict:
    if name not in SCHEMAS:
        raise MPresError('Unknown semantic schema')
    value=json.loads(Path(__file__).with_name('schemas').joinpath(name+'.json').read_text())
    Draft202012Validator.check_schema(value)
    return value


def validate(name: str, value) -> None:
    errors=sorted(Draft202012Validator(schema(name)).iter_errors(value),key=lambda e:str(list(e.path)))
    if errors:
        first=errors[0]
        where='/'.join(str(x) for x in first.path) or '<result>'
        raise SubmissionRejected(f'Semantic schema {name} at {where}: {first.message}')


def result_schema_name(kind: str) -> str:
    if kind in {'write','edit','revise'}:return 'author-result'
    if kind=='review':return 'review-result'
    if kind=='diagnose':return 'diagnosis-result'
    raise MPresError('Mechanical jobs do not request AI result schemas')


def guidance(root: Path, kind: str) -> str:
    if kind not in GUIDES:
        raise MPresError('No semantic guide for a mechanical job')
    relative=Path('.agents/skills')/GUIDES[kind]/'SKILL.md'
    path=root/relative
    if not path.is_file():
        path=Path(__file__).resolve().parents[3]/relative
    if not path.is_file():
        raise MPresError('Install the source checkout with its semantic skills; no implicit old-skill fallback')
    # Skill metadata helps discovery, not model execution. The role body is small.
    text=path.read_text(encoding='utf-8')
    return text.split('---',2)[-1].strip() if text.startswith('---') else text


def gate_excerpt(report: dict) -> dict:
    """Pass errors/warnings, not a second copy of every slide and PDF span."""
    return {
        'gate_id': report.get('gate_id'), 'artifact_id': report.get('artifact_id'),
        'success': report.get('success'), 'failure_kind': report.get('failure_kind'),
        'errors': report.get('errors', []),
        'checks': {name: {key: detail[key] for key in ('success','errors','warnings','slide_count','page_count') if key in detail}
                   for name, detail in report.get('checks', {}).items()},
    }
