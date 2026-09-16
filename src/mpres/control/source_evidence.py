"""Resolve exact frozen-source references without asking models to recopy TeX."""
from __future__ import annotations

from copy import deepcopy
import hashlib
from pathlib import Path
from mpres.marp_source import parse_deck
from mpres.util import MPresError, SubmissionRejected


def quote(directory: Path, slide_id: str, start_line: int, end_line: int,
          *, expected_sha256: str | None = None) -> dict:
    md=directory/'presentation.md'
    if md.is_symlink() or not md.is_file():raise MPresError('Missing/unsafe source evidence file')
    digest=hashlib.sha256(md.read_bytes()).hexdigest()
    if expected_sha256 is not None and digest!=expected_sha256:
        raise SubmissionRejected('Evidence source revision differs; reread the pinned source')
    slides=[s for s in parse_deck(md).slides if s.slide_id==slide_id]
    if len(slides)!=1:raise SubmissionRejected('Evidence must identify one existing canonical slide')
    lines=slides[0].source.splitlines()
    if type(start_line) is not int or type(end_line) is not int or not 1<=start_line<=end_line<=len(lines):
        raise SubmissionRejected('Evidence lines are 1-based, inclusive, relative to the selected slide source')
    text='\n'.join(lines[start_line-1:end_line]).strip()
    if not text or '<!--' in text or '-->' in text:
        raise SubmissionRejected('Evidence must quote visible source, not a hidden metadata/notes comment')
    if len(text)>1200:raise SubmissionRejected('Evidence excerpt exceeds 1200 characters; select a bounded exact range')
    return {'slide_id':slide_id,'quote':text,'source_ref':{'sha256':digest,
            'slide_id':slide_id,'start_line':start_line,'end_line':end_line}}


def resolve(value: dict, directory: Path) -> dict:
    """Normalize only declared evidence nodes; do not infer claims or severity."""
    value=deepcopy(value)
    nodes=[e for c in value.get('feedback_checks',[]) for e in c.get('evidence',[])]
    nodes+=value.get('observations',[])
    for node in nodes:
        ref=node.get('source_ref')
        if ref is None:continue
        if not isinstance(ref,dict) or set(ref)!={'sha256','slide_id','start_line','end_line'}:
            raise SubmissionRejected('source_ref needs sha256, slide_id, start_line and end_line only')
        if not isinstance(ref['sha256'],str) or len(ref['sha256'])!=64:
            raise SubmissionRejected('source_ref needs the full source SHA256')
        q=quote(directory,ref['slide_id'],ref['start_line'],ref['end_line'],expected_sha256=ref['sha256'])
        if node.get('slide_id')!=q['slide_id']:raise SubmissionRejected('Evidence slide_id and source_ref disagree')
        if 'quote' in node and node['quote']!=q['quote']:
            raise SubmissionRejected('Do not alter an exact program-resolved quote')
        node.pop('source_ref');node['quote']=q['quote']
    return value


def contract(directory: Path) -> dict:
    return {'version':1,'source_sha256':hashlib.sha256((directory/'presentation.md').read_bytes()).hexdigest(),
        'coordinates':'1-based inclusive line numbers within parse_deck slide.source, including metadata lines in the numbering',
        'command':['source','quote',str(directory),'--slide-id','<canonical-id>','--start-line','<n>','--end-line','<n>'],
        'use':'Use source lines to inspect coordinates; copy source_ref instead of recopying TeX into quote. The program resolves the exact visible excerpt. No semantic claim is inferred.'}


def lines(directory: Path, slide_id: str) -> dict:
    """Bounded on-demand view with coordinates; no duplicate full-deck index."""
    selected=[s for s in parse_deck(directory/'presentation.md').slides if s.slide_id==slide_id]
    if len(selected)!=1:raise MPresError('Unknown or duplicate slide ID')
    return {'slide_id':slide_id,'sha256':hashlib.sha256((directory/'presentation.md').read_bytes()).hexdigest(),
            'lines':[{'line':i,'text':line} for i,line in enumerate(selected[0].source.splitlines(),1)]}
