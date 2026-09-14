"""Single-page exercise identity, coverage, and isolated student-visible inputs.

The parser does NOT prove mathematical sufficiency. It checks references/coverage;
existing semantic reviewers judge the actual question without borrowing other pages.
Historical source lacking a manifest stays explicitly unindexed, never retro-approved.
"""
from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from urllib.parse import unquote

from jsonschema import Draft202012Validator

from mpres.marp_source import parse_deck
from mpres.util import MPresError, SubmissionRejected
from .files import inside
from .store import encode

FILE = 'exercises.json'
VERSION = 1
# Discovery, not a semantic verdict. Reviewers still read the whole assigned source.
CANDIDATE = re.compile(r'练习|诊断|判断题|随堂|你来(?:算|做|判断|试)|试一试|小测|思考题|'
                       r'\b(?:exercise|quiz|your turn|check yourself)\b', re.I)
COMMENT = re.compile(r'<!--.*?-->', re.S)
CHECK_SCHEMA = {
    'type':'array', 'items':{'type':'object','additionalProperties':False,
    'required':['question_slide_id','status','finding_index'],
    'properties':{
        'question_slide_id':{'type':'string','minLength':1},
        'status':{'enum':['sufficient','missing_information','not_exercise']},
        'finding_index':{'type':['integer','null'],'minimum':0},
        'reason':{'type':'string','minLength':1}},
    'allOf':[{'if':{'properties':{'status':{'const':'not_exercise'}}},'then':{'required':['reason']}}]}}


@lru_cache(maxsize=1)
def manifest_schema():
    value=json.loads(Path(__file__).with_name('schemas').joinpath('exercise-manifest.json').read_text())
    Draft202012Validator.check_schema(value)
    return value


def visible(source: str) -> str:
    """Speaker notes and metadata cannot satisfy a student's question."""
    return COMMENT.sub('',source).strip()


def candidates(source: Path) -> list[str]:
    return [s.slide_id for s in parse_deck(source/'presentation.md').slides
            if s.slide_id and CANDIDATE.search(s.title or '')]


def read_manifest(source: Path, *, required=False) -> dict | None:
    path=inside(source,FILE)
    if not path.is_file():
        if required:raise SubmissionRejected('Exercise manifest exercises.json is required, including an explicit empty list')
        return None
    if path.stat().st_size>262144:raise SubmissionRejected('Exercise manifest is too large; do not copy question text')
    try:value=json.loads(path.read_text(encoding='utf-8'))
    except (ValueError,UnicodeError) as exc:raise SubmissionRejected('Invalid exercises.json') from exc
    errors=list(Draft202012Validator(manifest_schema()).iter_errors(value))
    if errors:raise SubmissionRejected('Exercise manifest: '+errors[0].message)
    try:slides=parse_deck(source/'presentation.md').slides
    except (MPresError,ValueError) as exc:raise SubmissionRejected(str(exc)) from exc
    ids=[s.slide_id for s in slides]
    if any(not sid for sid in ids) or len(ids)!=len(set(ids)):
        raise SubmissionRejected('Exercise index requires unique stable slide IDs')
    known=set(ids);questions=set();exids=set();non=set()
    for row in value['exercises']:
        sid=row['question_slide_id'];eid=row['exercise_id']
        if sid not in known or sid in questions or eid in exids:
            raise SubmissionRejected('Unknown/duplicate exercise question page or identity')
        questions.add(sid);exids.add(eid)
        answers=row['answer_slide_ids']
        if any(a not in known or a==sid for a in answers):
            raise SubmissionRejected('Exercise answer must reference an existing separate answer page')
    for row in value.get('non_exercises',[]):
        sid=row['slide_id']
        if sid not in known or sid in questions or sid in non:
            raise SubmissionRejected('Conflicting/duplicate non-exercise classification')
        non.add(sid)
    missing=set(candidates(source))-questions-non
    if missing:raise SubmissionRejected('Unclassified exercise candidates: '+', '.join(sorted(missing)))
    # Images are checked only from the question page, not from an answer or note.
    for sid in questions:isolated_question(source,sid)
    return value


def isolated_question(source: Path, slide_id: str) -> dict:
    slides=[s for s in parse_deck(source/'presentation.md').slides if s.slide_id==slide_id]
    if len(slides)!=1:raise MPresError('Question page is missing or not unique')
    from mpres.source_policy import inspect_markdown
    text=visible(slides[0].source);assets=[]
    for image in inspect_markdown(text)['images']:
        path=inside(source,unquote(image['src']))
        if not path.is_file():raise SubmissionRejected('Exercise question image is missing')
        assets.append(str(path))
    return {'question_slide_id':slide_id,'markdown':text,'assets':list(dict.fromkeys(assets)),
            'scope':'Only this student-visible question page. No answers, notes, adjacent examples or producer claims.'}


def review_scope(source: Path, *, slide_ids=None) -> dict:
    manifest=read_manifest(source)
    entries=manifest['exercises'] if manifest else []
    declared={r['question_slide_id']:r['exercise_id'] for r in entries}
    # Even excluded candidates must be independently classified by the reviewer.
    expected=set(declared)|set(candidates(source))
    ordered=[s.slide_id for s in parse_deck(source/'presentation.md').slides
             if s.slide_id in expected and (slide_ids is None or s.slide_id in slide_ids)]
    return {'version':VERSION,'manifest_status':'indexed' if manifest is not None else 'historical_unindexed',
            'question_slide_ids':ordered,
            'declared_exercises':{sid:declared[sid] for sid in ordered if sid in declared},
            'instruction':'Independently check every question and ALL subquestions on one page. Use already learned knowledge, not remembered instance data. Also discover unindexed exercises in the full assigned reading. A keyword is not proof. missing_information requires a concrete same-page finding; not_exercise cannot reclassify an indexed question.'}


def validate_checks(result: dict, scope: dict, allowed: set[str]) -> None:
    checks=result.get('exercise_checks',[])
    errors=list(Draft202012Validator(CHECK_SCHEMA).iter_errors(checks))
    if errors:raise MPresError('Invalid exercise coverage: '+errors[0].message)
    expected=set(scope['question_slide_ids']);seen=set()
    for row in checks:
        sid=row['question_slide_id'];status=row['status'];index=row['finding_index']
        if sid not in allowed or sid in seen:raise MPresError('Exercise check cites an unread/duplicate page')
        seen.add(sid)
        if status=='not_exercise' and sid in scope['declared_exercises']:
            raise MPresError('Do not rename an indexed exercise to evade independent question review')
        if status=='missing_information':
            findings=result.get('findings',[])
            if type(index) is not int or index<0 or index>=len(findings) or sid not in findings[index]['slide_ids']:
                raise MPresError('Missing question information needs a same-page finding')
            if findings[index].get('severity') not in {'major','critical'}:
                raise MPresError('Unanswerable exercise is a blocking learning issue, not a minor warning')
        elif index is not None:raise MPresError('A sufficient/non-exercise classification must not point to a missing-information finding')
    if not expected<=seen:raise MPresError('Exercise coverage omitted pages: '+', '.join(sorted(expected-seen)))


def validate_author(source: Path, result: dict, *, required: bool):
    manifest=read_manifest(source,required=required)
    if manifest is None:return
    expected={r['question_slide_id'] for r in manifest['exercises']}
    actual=result.get('exercise_checked_slide_ids',[])
    if not isinstance(actual,list) or any(not isinstance(s,str) for s in actual) or len(actual)!=len(set(actual)) or set(actual)!=expected:
        raise SubmissionRejected('Author must independently check every indexed exercise and its answer; list exact exercise_checked_slide_ids')


def attach(packet: dict, source: Path | None, *, slide_ids=None):
    if packet.get('kind') in {'write','edit','revise'}:
        packet['exercise_contract']={'version':VERSION,'required_manifest':True,'file':FILE,
            'manifest_schema':manifest_schema(),
            'instruction':'Write exercises.json as a lightweight identity/coverage index, including [] when no questions. Classify all title candidates, and also index questions with other titles. Keep full question text only in presentation.md. Check all question pages in isolation and independently recompute answers; return exercise_checked_slide_ids. New edits must apply this rule even when the imported draft had no manifest.'}
        packet['source_contract']['files'].append(FILE)
    elif packet.get('kind')=='review' and packet.get('channel') in {'pedagogy','audience'} and source:
        scope=review_scope(source,slide_ids=slide_ids)
        packet['exercise_review']=scope
        if scope['question_slide_ids'] and 'exercise_checks' not in packet['result_schema'].get('required',[]):
            # The caller owns a deep copy; never mutate the cached shared schema.
            packet['result_schema']['required'].append('exercise_checks')


def source_check(source: Path) -> dict:
    try:
        manifest=read_manifest(source)
        return {'success':True,'errors':[],'indexed':manifest is not None,
                'exercise_count':len(manifest['exercises']) if manifest is not None else None,
                'semantic_sufficiency':'not_proven_by_program'}
    except (MPresError,ValueError) as exc:
        return {'success':False,'errors':[str(exc)],'semantic_sufficiency':'not_proven_by_program'}


def merge_manifests(sources: list[Path], output: Path):
    manifests=[read_manifest(s) for s in sources]
    if any(m is None for m in manifests):
        # An editor under the new contract will classify the entire assembly.
        return
    merged={'version':VERSION,'exercises':[], 'non_exercises':[]}
    for m in manifests:
        merged['exercises'].extend(m['exercises']);merged['non_exercises'].extend(m.get('non_exercises',[]))
    (output/FILE).write_text(encode(merged)+'\n',encoding='utf-8')
    read_manifest(output,required=True)
