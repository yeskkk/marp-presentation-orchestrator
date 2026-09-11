"""Project-wide source contract: content adapts to one layout, never vice versa.

CommonMark permits raw HTML. This project deliberately accepts a narrower
subset. Parsed HTML tokens (including inline HTML) are rejected, with only two
closed metadata comment grammars allowed. TeX/code examples are not HTML.
"""
from __future__ import annotations

import re
import stat
from pathlib import Path
from urllib.parse import unquote, urlsplit

import yaml
from markdown_it import MarkdownIt

from mpres.util import MPresError

POLICY_VERSION = 3
THEME_PATH = Path(__file__).with_name('control')/'theme.css'
FRONTMATTER = {'marp':True,'theme':'mathist-academic','paginate':True,'size':'16:9','math':'mathjax'}
METADATA = re.compile(r'<!--\s*(?:slide-id:\s*[A-Za-z][A-Za-z0-9_.:-]{0,127}|_class:\s*(?:core|support))\s*-->')
IMAGE_OPTION = re.compile(r'(?:^|\s)(?:bg|fit)(?:\s|$)|(?:^|\s)(?:w|h|width|height|size|blur|brightness|contrast|grayscale|hue-rotate|invert|opacity|saturate|sepia|drop-shadow):',re.I)
# Math notation (mathbf/mathbb/quad/left etc.) remains allowed. These commands
# modify presentation, inject HTML/CSS or define macros that can conceal it.
TEX_STYLE = re.compile(r'(?<!\\)\\(?:tiny|small|scriptsize|footnotesize|normalsize|large|Large|LARGE|huge|Huge|fontsize|scalebox|resizebox|raisebox|hspace|vspace|kern|mkern|mspace|style|class|cssId|htmlClass|htmlStyle|htmlId|htmlData|color|textcolor|bbox|require|def|gdef|edef|xdef|let|newcommand|renewcommand|providecommand|newenvironment|renewenvironment)(?![A-Za-z])')


class _UniqueLoader(yaml.SafeLoader):
    pass


def _mapping(loader,node,deep=False):
    out={}
    for key_node,value_node in node.value:
        key=loader.construct_object(key_node,deep=deep)
        if key in out:raise ValueError(f'Duplicate YAML key: {key}')
        out[key]=loader.construct_object(value_node,deep=deep)
    return out


_UniqueLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,_mapping)


def split_frontmatter(text: str) -> tuple[dict,str,int]:
    lines=text.splitlines(keepends=True)
    if not lines or lines[0].strip()!='---':return {},text,0
    for end in range(1,len(lines)):
        if lines[end].strip()=='---':
            front=yaml.load(''.join(lines[1:end]),Loader=_UniqueLoader) or {}
            if not isinstance(front,dict):raise ValueError('Frontmatter must be a mapping')
            return front,''.join(lines[end+1:]),end+1
    raise ValueError('Unclosed frontmatter')


def _unescaped(text,index):
    n=0;index-=1
    while index>=0 and text[index]=='\\':n+=1;index-=1
    return n%2==0


def _math_inline(state,silent):
    pos=state.pos;src=state.src
    opener=next((x for x in ('$$','$',r'\(',r'\[') if src.startswith(x,pos)),None)
    if not opener or not _unescaped(src,pos):return False
    if opener=='$' and (pos+1==len(src) or src[pos+1].isspace()):return False
    closer={r'\(':r'\)',r'\[':r'\]'}.get(opener,opener)
    end=src.find(closer,pos+len(opener))
    while end>=0:
        if _unescaped(src,end) and (opener!='$' or not src[end-1].isspace()):break
        end=src.find(closer,end+len(closer))
    if end<0:return False
    if not silent:
        token=state.push('math_source','',0);token.content=src[pos+len(opener):end]
    state.pos=end+len(closer)
    return True


def _math_block(state,start,end,silent):
    begin=state.bMarks[start]+state.tShift[start]
    raw=state.src[begin:state.eMarks[start]]
    opener='$$' if raw.startswith('$$') else r'\[' if raw.startswith(r'\[') else None
    if not opener:return False
    closer='$$' if opener=='$$' else r'\]'
    stop=state.src.find(closer,begin+len(opener))
    while stop>=0 and not _unescaped(state.src,stop):stop=state.src.find(closer,stop+len(closer))
    if stop<0:return False
    finish=start
    while finish+1<end and state.eMarks[finish]<stop+len(closer):finish+=1
    if state.eMarks[finish]<stop+len(closer) or state.src[stop+len(closer):state.eMarks[finish]].strip():return False
    if silent:return True
    token=state.push('math_source','',0);token.block=True;token.map=[start,finish+1]
    token.content=state.src[begin+len(opener):stop]
    state.line=finish+1
    return True


def parser() -> MarkdownIt:
    md=MarkdownIt('commonmark',{'html':True}).enable('table')
    # Math is opaque to CommonMark's inline HTML recognizer, as it is in Marp.
    # These tokens are for source validation, never for rendering output.
    md.inline.ruler.before('escape','math_source',_math_inline)
    md.block.ruler.before('fence','math_source',_math_block,{'alt':['paragraph','reference','blockquote','list']})
    return md


def walk(tokens,line=1):
    for token in tokens:
        current=(token.map[0]+1) if token.map else line
        yield token,current
        if token.children:yield from walk(token.children,current)


def inspect_markdown(text: str) -> dict:
    errors=[];images=[];math=[];ids=[]
    try:front,body,offset=split_frontmatter(text)
    except (ValueError,TypeError,yaml.YAMLError) as exc:
        return {'success':False,'errors':[f'Frontmatter: {exc}'],'images':[],'policy_version':POLICY_VERSION}
    allowed=set(FRONTMATTER)|{'title','description','author','keywords','lang'}
    for key,value in front.items():
        if key not in allowed:errors.append(f'Forbidden frontmatter/directive: {key}; layout belongs to the project')
        elif key in FRONTMATTER and (type(value) is not type(FRONTMATTER[key]) or value!=FRONTMATTER[key]):
            errors.append(f'Fixed project frontmatter {key} must be {FRONTMATTER[key]!r}')
        elif key not in FRONTMATTER and not isinstance(value,(str,list)):
            errors.append(f'Invalid descriptive metadata: {key}')
    try:tokens=parser().parse(body)
    except Exception as exc:
        return {'success':False,'errors':[f'Markdown parser rejected source: {exc}'],'images':[],'policy_version':POLICY_VERSION}
    for token,line in walk(tokens):
        prefix=f'line {line+offset}: '
        if token.type in {'html_block','html_inline'}:
            # Only standalone exact metadata comments. Do not whitelist arbitrary
            # comments/HTML merely because they contain a slide-id substring.
            if not token.content.strip() or METADATA.sub('',token.content).strip():
                errors.append(prefix+'Raw HTML/unknown comment is forbidden; use Markdown and external assets')
            else:
                ids.extend(re.findall(r'slide-id:\s*([^\s>]+)',token.content))
        elif token.type=='image':
            src=token.attrGet('src') or '';alt=token.content
            if IMAGE_OPTION.search(alt):errors.append(prefix+'Marp image sizing/background/filter directives are forbidden')
            images.append({'src':src,'alt':alt,'line':line+offset})
            parsed=urlsplit(unquote(src))
            if parsed.scheme or parsed.netloc or unquote(src).startswith('/'):
                errors.append(prefix+'Images must be local file references, not remote/data/absolute resources')
        elif token.type=='math_source':
            math.append(token.content)
            if TEX_STYLE.search(token.content):errors.append(prefix+'TeX layout/CSS/macro-definition command is forbidden; split content instead')
    if len(ids)!=len(set(ids)):errors.append('Duplicate canonical slide ID')
    return {'success':not errors,'errors':errors,'images':images,'policy_version':POLICY_VERSION,
            'scope':'Restricted CommonMark + table + math; metadata comments only; no raw HTML or per-slide style'}


def theme_bytes() -> bytes:
    return THEME_PATH.read_bytes()


def install_theme(directory: Path) -> None:
    path=directory/'theme.css'
    if path.is_symlink():raise MPresError('theme.css must not be a symlink')
    if path.exists():
        if path.read_bytes()!=theme_bytes():raise MPresError('Custom/modified theme.css is forbidden; only project maintenance changes layout')
    else:path.write_bytes(theme_bytes())
    path.chmod(path.stat().st_mode & ~(stat.S_IWUSR|stat.S_IWGRP|stat.S_IWOTH))


def inspect_source(source: Path) -> dict:
    errors=[]
    if source.is_symlink() or not source.is_dir():
        return {'success':False,'errors':['Source must be a real directory'],'policy_version':POLICY_VERSION}
    if not (source/'presentation.md').is_file():
        return {'success':False,'errors':['presentation.md is missing'],'policy_version':POLICY_VERSION}
    report=inspect_markdown((source/'presentation.md').read_text(encoding='utf-8'))
    errors.extend(report['errors'])
    for path in source.rglob('*'):
        rel=path.relative_to(source)
        if path.is_symlink():errors.append(f'Symlink forbidden: {rel}');continue
        if not path.is_file():continue
        if path.suffix.lower() in {'.css','.scss','.sass','.less'}:
            if rel.as_posix()!='theme.css' or path.read_bytes()!=theme_bytes():
                errors.append(f'Custom stylesheet forbidden: {rel}; content must adapt to project layout')
        if path.suffix.lower() in {'.html','.htm','.xhtml','.js','.cjs','.mjs'} or path.name.startswith('.marprc'):
            errors.append(f'HTML/render-config/executable web asset forbidden: {rel}')
    for image in report.get('images',[]):
        raw=unquote(image['src']);parsed=urlsplit(raw)
        if parsed.scheme or parsed.netloc:continue
        p=Path(parsed.path)
        if p.is_absolute() or '..' in p.parts or not (source/p).resolve().is_relative_to(source.resolve()):
            errors.append(f'Image escapes source directory: {raw}')
        elif not (source/p).is_file():errors.append(f'Missing image: {raw}')
    from mpres.geometry import inspect_figures
    geometry=inspect_figures(source)
    errors.extend(geometry['errors'])
    return {**report,'success':not errors,'errors':errors,'computed_figures':geometry}


def require_source(source: Path) -> None:
    report=inspect_source(source)
    if not report['success']:
        from mpres.util import SubmissionRejected
        raise SubmissionRejected('Project source contract failed:\n'+'\n'.join(report['errors'][:20]))


def comparable_files(source: Path) -> dict[str,bytes]:
    """An omitted project theme and its exact read-only copy are equivalent."""
    result={p.relative_to(source).as_posix():p.read_bytes() for p in source.rglob('*') if p.is_file()}
    result.setdefault('theme.css',theme_bytes())
    return result


def render_options() -> list[str]:
    return ['--no-config-file','--no-html','--theme-set',str(THEME_PATH),
            '--theme',FRONTMATTER['theme'],'--size',FRONTMATTER['size'],'--math',FRONTMATTER['math']]
