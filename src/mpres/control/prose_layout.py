"""Bounded Markdown-structure checks, not a machine verdict on writing quality.

Math, code, links and metadata are opaque. A sentence may wrap naturally. Only
clear CJK sentence endings followed by another visible sentence in the same
paragraph/display run are blocking. Ambiguous Western punctuation is not used
as an automatic sentence splitter. No source is rewritten by this checker.
"""
from __future__ import annotations

import re
from pathlib import Path
from mpres.marp_source import parse_deck
from mpres.source_policy import parser

VERSION=1
END=re.compile(r'[。！？](?:[”’」』】）)》〉]+)?(?=\s*[^\s。！？”’」』】）)》〉])')


def inspect(source: Path) -> dict:
    violations=[]
    from mpres.util import MPresError
    try:deck=parse_deck(source/'presentation.md')
    except (MPresError,OSError,ValueError) as exc:
        return {'version':VERSION,'success':False,'violations':[],'errors':[str(exc)],'title_required':False,'source_rewritten':False}
    for slide in deck.slides:
        tokens=parser().parse(slide.source)
        for index,token in enumerate(tokens):
            if token.type!='inline' or not token.map:continue
            previous=tokens[index-1].type if index else ''
            # Headings are optional. A multi-sentence heading is a semantic issue,
            # not a pretext to require a title or add style directives.
            if previous=='heading_open':continue
            parts=[''];link_depth=0
            for child in token.children or []:
                if child.type=='link_open':link_depth+=1;parts[-1]+='OBJECT';continue
                if child.type=='link_close':link_depth-=1;continue
                if link_depth:continue
                if child.type=='hardbreak':parts.append('');continue
                if child.type=='softbreak':parts[-1]+='\n';continue
                if child.type=='text':parts[-1]+=child.content
                elif child.type in {'math_source','code_inline','image'}:parts[-1]+='OBJECT'
            joined=[part for part in parts if END.search(part)]
            if joined:
                violations.append({'slide_id':slide.slide_id,'line':token.map[0]+1,
                    'code':'independent_sentences_share_display_run',
                    'message':'独立句子应分别起行；使用 Markdown 硬换行（行末两个空格或反斜杠）或分段，不改成满页项目符号。',
                    'excerpt':joined[0][:240]})
    return {'version':VERSION,'success':not violations,'violations':violations,
        'errors':[f"{r['slide_id']} line {r['line']}: {r['message']}" for r in violations],
        'title_required':False,'source_rewritten':False,
        'semantic_scope':'Only clear structural collisions are checked. Clarity, disciplinary language, sentence boundaries in ambiguous notation, titles and naturalness still require existing semantic reviewers.'}
