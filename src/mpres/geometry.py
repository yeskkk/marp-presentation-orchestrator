"""Small, deterministic mathematical figure generator; never executes author code.

The .plot.json file is mathematical input, not a gate receipt. The generator
computes geometry using exact rational arithmetic, renders with Matplotlib in
one data coordinate system, and exports a reproducible sibling Python entry.
Source checks recompute the output rather than trusting an author's success flag.
"""
from __future__ import annotations

import io
import json
import math
import re
from fractions import Fraction
from pathlib import Path
from threading import RLock
from xml.etree import ElementTree as ET

from mpres.util import MPresError

GENERATOR = 'mpres-geometry-1'
GENERATOR_V2 = 'mpres-geometry-2'
GENERATOR_V3 = 'mpres-geometry-3'
_LOCK = RLock()  # Matplotlib rcParams are process global, not thread-local.


def number(value) -> Fraction:
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise MPresError('Geometry numbers must be finite integers, decimals or rational strings')
    if len(str(value)) > 80:
        raise MPresError('Geometry number is too long')
    try:
        n = Fraction(str(value))
    except (ValueError, ZeroDivisionError, OverflowError) as exc:
        raise MPresError('Invalid finite rational geometry number') from exc
    if abs(n) > 10**9 or n.denominator > 10**12:
        raise MPresError('Geometry number is outside supported exact arithmetic bounds')
    return n


def vector(value, size=2) -> tuple[Fraction, ...]:
    if not isinstance(value, list) or len(value) != size:
        raise MPresError(f'Expected {size} mathematical coordinates')
    return tuple(number(x) for x in value)


def dot(a, b):
    return sum(x*y for x, y in zip(a, b))


def solve_lines(lines) -> dict:
    if not isinstance(lines, list) or len(lines) != 2:
        raise MPresError('Two lines [a,b,c], meaning a*x+b*y=c, are required')
    first, second = (vector(row, 3) for row in lines)
    a,b,c = first; d,e,f = second
    if (a,b) == (0,0) or (d,e) == (0,0):
        raise MPresError('A line must have a nonzero normal vector')
    determinant = a*e-b*d
    if not determinant:
        status = 'coincident' if a*f == c*d and b*f == c*e else 'parallel'
        return {'status':status, 'lines':[first,second], 'intersection':None}
    p = ((c*e-b*f)/determinant, (a*f-c*d)/determinant)
    if any(dot(row[:2],p) != row[2] for row in (first,second)):
        raise MPresError('Exact line intersection residual failed')
    return {'status':'intersecting', 'lines':[first,second], 'intersection':p}


def projection(point, direction) -> dict:
    p, u = vector(point), vector(direction)
    if not dot(u,u):
        raise MPresError('Projection direction must be nonzero')
    scale = dot(p,u)/dot(u,u)
    q = tuple(scale*x for x in u)
    r = tuple(x-y for x,y in zip(p,q))
    if dot(r,u) != 0 or any(q[i]+r[i] != p[i] for i in range(2)):
        raise MPresError('Exact projection residual failed')
    return {'point':p,'direction':u,'foot':q,'residual':r}


def transformation(matrix, vectors) -> dict:
    if not isinstance(matrix,list) or len(matrix) != 2:
        raise MPresError('Expected a 2 by 2 transformation matrix')
    m = tuple(vector(row) for row in matrix)
    if not isinstance(vectors,list) or not 1 <= len(vectors) <= 4:
        raise MPresError('Use one to four input vectors per figure')
    vv = [vector(row) for row in vectors]
    return {'matrix':m,'vectors':vv,'images':[tuple(dot(row,v) for row in m) for v in vv]}


def mathematical_model(spec: dict) -> dict:
    if not isinstance(spec,dict) or type(spec.get('version')) is not int or spec['version'] not in (1,2,3):
        raise MPresError('Geometry spec requires version: 1, 2 or 3')
    kinds = {'lines':{'lines'}, 'projection':{'point','direction'}, 'transform':{'matrix','vectors'}}
    kind = spec.get('kind')
    if spec['version']==3 and kind!='lines':
        raise MPresError('Geometry version 3 supports line diagrams only')
    if kind not in kinds or set(spec) != {'version','kind'} | kinds[kind]:
        raise MPresError('Geometry spec contains missing/unknown fields; pixel coordinates, styles and claimed results are forbidden')
    if kind == 'lines':
        result = solve_lines(spec['lines'])
        if spec['version']>=2:
            # Only uniquely defined intercepts: an axis-coincident line does not
            # have a single intercept on that axis. Preserve exact rationals.
            result['intercepts']=[{'x':(c/a,Fraction(0)) if a else None,
                                   'y':(Fraction(0),c/b) if b else None}
                                  for a,b,c in result['lines']]
    elif kind == 'projection':
        result = projection(spec['point'],spec['direction'])
    else:
        result = transformation(spec['matrix'],spec['vectors'])
    return {'kind':kind, **result}


def _plain(value):
    if isinstance(value,Fraction): return str(value)
    if isinstance(value,dict): return {k:_plain(v) for k,v in value.items()}
    if isinstance(value,(tuple,list)): return [_plain(v) for v in value]
    return value


def _xy(p):
    return tuple(float(x) for x in p)


def _point_label(prefix,p):
    return prefix + '=(' + ', '.join(str(x) for x in p) + ')'


def _line_label(row):
    a,b,c=row
    return f'{a}x + ({b})y = {c}'


def _line_points(row):
    a,b,c=row
    # Normal projection of origin and an exact direction; works for vertical lines.
    base=(a*c/(a*a+b*b), b*c/(a*a+b*b))
    return base, (base[0]-b,base[1]+a)


def _figure_bytes_v1(spec: dict) -> tuple[bytes, dict]:
    model=mathematical_model(spec)
    try:
        import matplotlib as mpl
        from matplotlib.figure import Figure
        from matplotlib.backends.backend_agg import FigureCanvasAgg
    except ImportError as exc:
        raise MPresError('Install the project figures extra before generating/checking computed diagrams') from exc
    with _LOCK, mpl.rc_context({'font.size':18,'svg.fonttype':'none','svg.hashsalt':GENERATOR,
                               'text.usetex':False,'font.family':'DejaVu Sans'}):
        fig=Figure(figsize=(9,6),layout='constrained');FigureCanvasAgg(fig)
        ax=fig.add_subplot(111)
        points=[(Fraction(0),Fraction(0))]
        if model['kind']=='lines':
            for i,row in enumerate(model['lines']):
                a,b=_line_points(row);points.append(a)
                artist=ax.axline(_xy(a),_xy(b),label=_line_label(row))
                artist.set_gid(f'computed-line-{i}')
            p=model['intersection']
            if p is not None:
                points.append(p)
                marker,=ax.plot(*_xy(p),marker='o',linestyle='none',label=_point_label('p',p))
                marker.set_gid('computed-intersection')
            else:
                ax.set_title(model['status'].capitalize())
        elif model['kind']=='projection':
            p,u,q=model['point'],model['direction'],model['foot'];points += [p,q]
            ax.axline((0,0),_xy(u),label='span(u)')
            ax.plot([0,float(p[0])],[0,float(p[1])],marker='o',label=_point_label('p',p))
            foot,=ax.plot(*_xy(q),marker='s',linestyle='none',label=_point_label('proj',q))
            foot.set_gid('computed-projection')
            ax.plot([float(q[0]),float(p[0])],[float(q[1]),float(p[1])],linestyle='--',label='orthogonal residual')
        else:
            for i,(v,w) in enumerate(zip(model['vectors'],model['images'])):
                points += [v,w]
                ax.plot([0,float(v[0])],[0,float(v[1])],marker='o',linestyle='--',label=_point_label(f'v{i+1}',v))
                image,=ax.plot([0,float(w[0])],[0,float(w[1])],marker='s',label=_point_label(f'A v{i+1}',w))
                image.set_gid(f'computed-image-{i}')
        xs=[float(p[0]) for p in points];ys=[float(p[1]) for p in points]
        span=max(max(xs)-min(xs),max(ys)-min(ys),2.0);margin=span*0.35
        cx=(max(xs)+min(xs))/2;cy=(max(ys)+min(ys))/2
        half=span/2+margin
        if not math.isfinite(half) or half>10**10:
            raise MPresError('Figure range is numerically unsuitable; choose a better teaching example')
        ax.set_xlim(cx-half,cx+half);ax.set_ylim(cy-half,cy+half)
        ax.set_aspect('equal',adjustable='box');ax.set_xlabel('x');ax.set_ylabel('y')
        ax.grid(True);ax.legend(loc='upper left',bbox_to_anchor=(1.02,1),fontsize=18)
        data=io.BytesIO()
        fig.savefig(data,format='svg',metadata={'Date':None,'Creator':GENERATOR})
        return data.getvalue(),_plain(model)


def figure_bytes(spec: dict) -> tuple[bytes, dict]:
    # Validate before choosing a renderer; bool and unknown versions are not integers here.
    mathematical_model(spec)
    if spec['version'] in (2,3):
        return _figure_bytes_v2(spec)
    return _figure_bytes_v1(spec)


def _figure_bytes_v2(spec: dict) -> tuple[bytes, dict]:
    """Fixed project-owned styling; mathematical inputs cannot control layout."""
    model=mathematical_model(spec)
    version3=spec['version']==3
    generator=GENERATOR_V3 if version3 else GENERATOR_V2
    try:
        import matplotlib as mpl
        from matplotlib.figure import Figure
        from matplotlib.backends.backend_agg import FigureCanvasAgg
    except ImportError as exc:
        raise MPresError('Install the project figures extra before generating/checking computed diagrams') from exc
    with _LOCK, mpl.rc_context({'font.size':24,'svg.fonttype':'none','svg.hashsalt':generator,
                               'text.usetex':False,'font.family':'DejaVu Sans'}):
        fig=Figure(figsize=(9,6));FigureCanvasAgg(fig)
        ax=fig.add_subplot(111)
        points=[(Fraction(0),Fraction(0))]
        colors=('#0072b2','#d55e00','#009e73','#cc79a7')
        if model['kind']=='lines':
            labelled={}
            for i,row in enumerate(model['lines']):
                a,b=_line_points(row);points.append(a)
                artist=ax.axline(_xy(a),_xy(b),color=colors[i],linestyle=('-','--')[i],
                                 linewidth=2.5,label=f'L{i+1}: '+_line_label(row))
                artist.set_gid(f'computed-line-{i}')
                for axis,p in model['intercepts'][i].items():
                    if p is None:continue
                    points.append(p)
                    marker,=ax.plot(*_xy(p),marker=('o','s')[i],linestyle='none',
                                    color=colors[i],fillstyle='none',markersize=8)
                    marker.set_gid(f'computed-intercept-{i}-{axis}')
                    labelled.setdefault(p,_point_label('',p).lstrip('='))
            p=model['intersection']
            if p is not None:
                points.append(p)
                marker,=ax.plot(*_xy(p),marker='o',linestyle='none',color='black')
                marker.set_gid('computed-intersection')
                labelled[p]=_point_label('p',p)
            else:
                ax.set_title(model['status'].capitalize())
            x_intercepts=sorted(p for p in labelled if p[1]==0)
            for i,(p,label) in enumerate(labelled.items()):
                if version3 and p in x_intercepts:
                    # Put the two x-intercept labels on the outside of their
                    # interval, below their markers. Do not shrink text or move
                    # mathematical points. v2's exact output remains unchanged.
                    left=p==x_intercepts[0]
                    annotation=ax.annotate(label,_xy(p),xytext=(-7 if left else 7,-10),
                                           textcoords='offset points',ha='right' if left else 'left',
                                           va='top',fontsize=22,annotation_clip=False)
                else:
                    annotation=ax.annotate(label,_xy(p),xytext=(7,7),textcoords='offset points',
                                           fontsize=22,annotation_clip=False)
                annotation.set_gid(f'computed-point-label-{i}')
        elif model['kind']=='projection':
            p,u,q=model['point'],model['direction'],model['foot'];points += [p,q]
            ax.axline((0,0),_xy(u),color=colors[0],linewidth=2.5,label='span(u)')
            ax.plot([0,float(p[0])],[0,float(p[1])],marker='o',color=colors[1],
                    label=_point_label('p',p))
            foot,=ax.plot(*_xy(q),marker='s',linestyle='none',color=colors[2],label=_point_label('proj',q))
            foot.set_gid('computed-projection')
            ax.plot([float(q[0]),float(p[0])],[float(q[1]),float(p[1])],linestyle='--',
                    color=colors[2],label='orthogonal residual')
        else:
            for i,(v,w) in enumerate(zip(model['vectors'],model['images'])):
                points += [v,w]
                ax.plot([0,float(v[0])],[0,float(v[1])],marker='o',linestyle='--',color=colors[i],
                        label=_point_label(f'v{i+1}',v))
                image,=ax.plot([0,float(w[0])],[0,float(w[1])],marker='s',color=colors[i],
                               label=_point_label(f'A v{i+1}',w))
                image.set_gid(f'computed-image-{i}')
        xs=[float(p[0]) for p in points];ys=[float(p[1]) for p in points]
        span=max(max(xs)-min(xs),max(ys)-min(ys),2.0);half=span*.85
        if not math.isfinite(half) or half>10**10:
            raise MPresError('Figure range is numerically unsuitable; choose a better teaching example')
        cx=(max(xs)+min(xs))/2;cy=(max(ys)+min(ys))/2
        ax.set_xlim(cx-half,cx+half);ax.set_ylim(cy-half,cy+half)
        ax.set_aspect('equal',adjustable='box');ax.set_xlabel('x');ax.set_ylabel('y')
        ax.grid(True)
        # Export includes the full legend and all text, not just the nominal
        # figure rectangle. Padding absorbs browser font-metric differences.
        ax.legend(loc='upper center',bbox_to_anchor=(.5,-.20),fontsize=24,ncol=1)
        data=io.BytesIO()
        fig.savefig(data,format='svg',bbox_inches='tight',pad_inches=.3,
                    metadata={'Date':None,'Creator':generator})
        return data.getvalue(),_plain(model)



def _canonical_svg(data: bytes) -> bytes:
    # No source checksum. Ignore only metadata and renderer-generated local IDs;
    # geometry, labels, transforms and styling all remain in the byte comparison.
    text=data.decode('utf-8')
    text=re.sub(r'<metadata>.*?</metadata>','',text,flags=re.S)
    ids=re.findall(r'\bid="([^"]+)"',text)
    mapping={v:f'local-{i}' for i,v in enumerate(ids)}
    for old in sorted(mapping,key=len,reverse=True):
        text=text.replace(f'id="{old}"',f'id="{mapping[old]}"')
        text=text.replace(f'#{old})',f'#{mapping[old]})').replace(f'href="#{old}"',f'href="#{mapping[old]}"')
    return text.encode('utf-8')


def reproduction_script(spec_name: str, image_name: str) -> str:
    return ('"""Rebuild this computed teaching figure; requires the project figures extra."""\n'
            'from pathlib import Path\nfrom mpres.geometry import build\n'
            'if __name__ == "__main__":\n'
            f'    build(Path(__file__).with_name({spec_name!r}), Path(__file__).with_name({image_name!r}))\n')


def build(spec_path: Path, output: Path | None = None) -> dict:
    spec_path=Path(spec_path)
    if not spec_path.name.endswith('.plot.json') or spec_path.is_symlink():
        raise MPresError('Use a regular <name>.plot.json mathematical input file')
    output=Path(output) if output else spec_path.with_name(spec_path.name[:-10]+'.svg')
    if output.suffix!='.svg' or output.name!=spec_path.name[:-10]+'.svg' or output.parent.resolve()!=spec_path.parent.resolve():
        raise MPresError('Output must be the paired sibling <name>.svg')
    script=output.with_suffix('.py')
    if output.is_symlink() or script.is_symlink():raise MPresError('Figure output links are forbidden')
    try:spec=json.loads(spec_path.read_text(encoding='utf-8'))
    except (ValueError,OSError) as exc:raise MPresError('Cannot read mathematical figure input') from exc
    data,model=figure_bytes(spec)
    output.write_bytes(data)
    script.write_text(reproduction_script(spec_path.name,output.name),encoding='utf-8')
    return {'success':True,'asset':str(output),'source':str(spec_path),'script':str(script),'model':model,
            'validation':'Exact mathematical relationships; deterministic generated asset'}


def inspect_figures(source: Path) -> dict:
    """Check declared computed assets without importing or executing submitted .py."""
    errors=[];figures=[];source=Path(source)
    specs=list(source.rglob('*.plot.json'))
    if len(specs)>256:return {'success':False,'errors':['Too many computed figures in one source revision']}
    covered=set()
    for path in specs:
        relative=path.relative_to(source).as_posix()
        image=path.with_name(path.name[:-10]+'.svg');covered.add(image)
        try:
            if any(p.is_symlink() for p in (path,image,image.with_suffix('.py'))):
                raise MPresError('Computed-figure links are forbidden')
            if path.stat().st_size>32768:raise MPresError('Mathematical figure input is too large')
            expected,model=figure_bytes(json.loads(path.read_text(encoding='utf-8')))
            if not image.is_file() or _canonical_svg(image.read_bytes())!=_canonical_svg(expected):
                raise MPresError('Computed SVG is missing or differs from its mathematical input; regenerate, never hand-edit it')
            script=image.with_suffix('.py')
            if not script.is_file() or script.read_text(encoding='utf-8')!=reproduction_script(path.name,image.name):
                raise MPresError('Missing or altered reproducible figure entry script')
            figures.append({'input':relative,'asset':image.relative_to(source).as_posix(),'model':model})
        except (MPresError,ValueError,TypeError,KeyError,OSError,OverflowError) as exc:
            errors.append(f'{relative}: {exc}')
    for path in source.rglob('*.svg'):
        if path not in covered and not path.is_symlink() and any(marker in path.read_text(encoding='utf-8') for marker in (GENERATOR,GENERATOR_V2,GENERATOR_V3)):
            errors.append(f'{path.relative_to(source)}: computed figure lacks paired .plot.json input')
    return {'success':not errors,'errors':errors,'figures':figures,
            'scope':'Only declared computed figures; external assets are not certified as mathematically correct'}
