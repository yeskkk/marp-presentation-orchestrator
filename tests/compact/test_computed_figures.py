from __future__ import annotations
import json
from fractions import Fraction
from pathlib import Path
import pytest

from mpres.geometry import (build, figure_bytes, inspect_figures, mathematical_model,
                           number, projection, solve_lines, transformation)
from mpres.source_policy import inspect_source
from mpres.util import MPresError
from test_relational_control import compact_root, prepare, register, source_for


def make_plot(path, spec=None):
    path.mkdir(parents=True,exist_ok=True)
    target=path/'intersection.plot.json'
    target.write_text(json.dumps(spec or {'version':1,'kind':'lines','lines':[[1,1,2],[1,-1,0]]}))
    return target


@pytest.mark.parametrize('lines,status,point',[
    ([[1,1,2],[1,-1,0]],'intersecting',(1,1)),
    ([[1,0,2],[0,1,3]],'intersecting',(2,3)),
    ([[1,1,2],[2,2,4]],'coincident',None),
    ([[1,1,2],[2,2,5]],'parallel',None),
    ([[3,1,1],[1,-1,0]],'intersecting',(Fraction(1,4),Fraction(1,4))),
])
def test_exact_line_relationships(lines,status,point):
    model=solve_lines(lines)
    assert model['status']==status and model['intersection']==point
    if point:
        for a,b,c in model['lines']:assert a*point[0]+b*point[1]==c


@pytest.mark.parametrize('invalid',[True,'nan',float('inf'),'1/0','__import__("os")',[],10**12])
def test_only_bounded_numeric_inputs(invalid):
    with pytest.raises(MPresError):number(invalid)


def test_zero_normals_directions_rejected():
    with pytest.raises(MPresError):solve_lines([[0,0,2],[1,1,0]])
    with pytest.raises(MPresError):projection([1,2],[0,0])


def test_projection_and_transform_exact():
    p=projection([2,1],[1,1])
    assert p['foot']==(Fraction(3,2),Fraction(3,2))
    assert sum(a*b for a,b in zip(p['residual'],p['direction']))==0
    t=transformation([[1,2],[0,1]],[[1,1],[-1,0]])
    assert t['images']==[(3,1),(-1,0)]


def test_no_pixel_positions_or_style_parameters():
    for key in ['intersection','color','xlim','style','marker_coordinates']:
        with pytest.raises(MPresError):
            mathematical_model({'version':1,'kind':'lines','lines':[[1,1,2],[1,-1,0]],key:[9,9]})


@pytest.mark.parametrize('spec',[
    {'version':1,'kind':'lines','lines':[[1,0,2],[0,1,3]]},
    {'version':1,'kind':'lines','lines':[[1,1,2],[2,2,5]]},
    {'version':1,'kind':'lines','lines':[[1,1,2],[2,2,4]]},
    {'version':1,'kind':'projection','point':[2,1],'direction':[1,1]},
    {'version':1,'kind':'transform','matrix':[[1,2],[0,1]],'vectors':[[1,0],[0,1]]},
])
def test_real_matplotlib_roundtrip(tmp_path,spec):
    path=make_plot(tmp_path,spec);result=build(path)
    assert result['success'] and path.with_name('intersection.py').is_file()
    assert inspect_figures(tmp_path)['success']
    data=path.with_name('intersection.svg').read_bytes()
    build(path)
    assert data==path.with_name('intersection.svg').read_bytes()


def test_hand_edit_and_stale_math_data_rejected(tmp_path):
    path=make_plot(tmp_path);build(path)
    image=path.with_name('intersection.svg')
    image.write_text(image.read_text().replace('computed-intersection','wrong-intersection').replace('stroke-width: 1.5','stroke-width: 7'))
    assert not inspect_figures(tmp_path)['success']
    build(path)
    spec=json.loads(path.read_text());spec['lines'][0][2]=3;path.write_text(json.dumps(spec))
    assert not inspect_figures(tmp_path)['success']
    build(path);assert inspect_figures(tmp_path)['success']


def test_missing_spec_and_script_are_not_certified(tmp_path):
    path=make_plot(tmp_path);build(path)
    path.with_name('intersection.py').unlink()
    assert not inspect_figures(tmp_path)['success']
    build(path);path.unlink()
    assert not inspect_figures(tmp_path)['success']


def test_plain_external_assets_not_falsely_certified(tmp_path):
    (tmp_path/'photo.svg').write_text('<svg xmlns="http://www.w3.org/2000/svg"/>')
    result=inspect_figures(tmp_path)
    assert result['success'] and result['figures']==[]
    assert 'not certified' in result['scope']


def test_submission_enforces_derived_geometry_and_retains_sources(compact_root):
    service=prepare(compact_root);source=source_for(service)
    spec=make_plot(source/'assets'/'l01');build(spec)
    with (source/'presentation.md').open('a') as f:f.write('\n![computed intersection](assets/l01/intersection.svg)\n')
    assert inspect_source(source)['success']
    register(service);a=service.bind(service.jobs()[0]['id'],'h1');service.started(a['id'],'executed')
    artifact=service.submit(a['id'],{'summary':'Exact line intersection'},source=source)['artifact_id']
    row=service.store.rows('SELECT * FROM artifacts WHERE id=?',(artifact,))[0]
    frozen=service.task/row['path']
    assert (frozen/'assets/l01/intersection.plot.json').read_bytes()==spec.read_bytes()
    assert (frozen/'assets/l01/intersection.py').is_file()
    p=source/'assets/l01/intersection.svg'
    p.write_text(p.read_text().replace('stroke-width: 1.5','stroke-width: 7'))
    with pytest.raises(MPresError,match='Computed SVG'):service.submit(a['id'],{'summary':'Exact line intersection'},source=source)
