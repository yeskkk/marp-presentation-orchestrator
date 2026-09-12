from pathlib import Path
from fractions import Fraction
from concurrent.futures import ThreadPoolExecutor
import json

import pytest

from mpres.geometry import mathematical_model,figure_bytes,inspect_figures,build
from mpres.control.files import prepare_edit_source
from mpres.control.runner import Runner
from mpres.control.repairs import Repairs
from mpres.util import MPresError
from test_relational_control import compact_root
from test_deck_workflow import native_double
from test_confirmed_repairs import completed,confirm
from test_review_first_repairs import proposal


def spec(version=3,lines=None):
    return {'version':version,'kind':'lines','lines':lines or [[1,1,6],[1,2,8]]}


@pytest.mark.parametrize('version',[1,2,3])
def test_versions_compute_same_exact_intersection(version):
    model=mathematical_model(spec(version))
    assert model['intersection']==(Fraction(4),Fraction(2))
    for a,b,c in model['lines']:assert a*model['intersection'][0]+b*model['intersection'][1]==c
    if version>=2:
        assert model['intercepts'][0]['x']==(Fraction(6),Fraction(0))


@pytest.mark.parametrize('version',[False,True,0,4,'3',None])
def test_unknown_or_boolean_version_never_silently_downgraded(version):
    with pytest.raises(MPresError):mathematical_model(spec(version))


def test_no_fabricated_unique_intercepts_for_axis_coincident_lines():
    m=mathematical_model(spec(3,[[1,0,0],[0,1,2]]))
    assert m['intersection']==(0,2)
    assert m['intercepts'][0]['y'] is None
    assert m['intercepts'][1]['x'] is None
    for v in [2,3]:
        m=mathematical_model(spec(v,[[1,1,6],[2,2,12]]))
        assert m['status']=='coincident' and m['intersection'] is None


def test_geometry_input_cannot_select_style_or_unsupported_kind():
    x=spec();x['font_size']=8
    with pytest.raises(MPresError):mathematical_model(x)
    with pytest.raises(MPresError):mathematical_model({'version':3,'kind':'transform','matrix':[[1,0],[0,1]],'vectors':[[1,2]]})


def source_tree(task):
    source=task/'.mpres/artifacts/old';source.mkdir(parents=True)
    (source/'presentation.md').write_text('---\nmarp: true\n---\n<!-- slide-id: p01-l01-s1 -->\n# Two conditions\n\n![Intersection](assets/charging.svg)\n')
    assets=source/'assets';assets.mkdir()
    path=assets/'charging.plot.json';path.write_text(json.dumps(spec()))
    (assets/'charging.svg').write_text('<svg xmlns="http://www.w3.org/2000/svg"><text>mpres-geometry-3 legacy renderer</text></svg>')
    (assets/'charging.py').write_text('raise RuntimeError("MUST NOT EXECUTE AUTHOR PYTHON")')
    for p in source.rglob('*'):
        if p.is_file():p.chmod(0o444)
    return source


def test_new_author_copy_regenerates_without_touching_old_evidence(tmp_path):
    source=source_tree(tmp_path);before={p:p.read_bytes() for p in source.rglob('*') if p.is_file()}
    target=tmp_path/'.mpres/work/a/output'
    report=prepare_edit_source(tmp_path,source,target)
    assert report['state']=='prepared' and len(report['regenerated'])==1
    assert inspect_figures(target)['success']
    assert (target/'presentation.md').read_bytes()==before[source/'presentation.md']
    assert all(p.read_bytes()==v for p,v in before.items())
    assert (target/'assets/charging.svg').read_bytes()!=before[source/'assets/charging.svg']


def test_existing_unsubmitted_work_is_not_replaced(tmp_path):
    source=source_tree(tmp_path);target=tmp_path/'.mpres/work/a/output'
    prepare_edit_source(tmp_path,source,target)
    (target/'presentation.md').write_text('Author edits in progress')
    report=prepare_edit_source(tmp_path,source,target)
    assert report['state']=='existing_output_preserved'
    assert (target/'presentation.md').read_text()=='Author edits in progress'


def test_only_private_new_work_copy_can_be_automatically_prepared(tmp_path):
    source=source_tree(tmp_path)
    with pytest.raises(MPresError):prepare_edit_source(tmp_path,source,tmp_path/'deliverables/p01')
    with pytest.raises(MPresError):prepare_edit_source(tmp_path,source,source)
    p=source/'assets/charging.plot.json';p.chmod(0o644);p.write_text(json.dumps(spec(99)))
    target=tmp_path/'.mpres/work/a/output'
    with pytest.raises(MPresError):prepare_edit_source(tmp_path,source,target)
    assert not target.exists()


def test_concurrent_prepare_keeps_complete_valid_work(tmp_path):
    source=source_tree(tmp_path);target=tmp_path/'.mpres/work/a/output'
    with ThreadPoolExecutor(max_workers=2) as pool:
        results=list(pool.map(lambda _:prepare_edit_source(tmp_path,source,target),range(2)))
    assert any(r['state']=='prepared' for r in results)
    assert inspect_figures(target)['success']
    assert not list(target.parent.glob('output.prepare-*'))


def test_version_three_marker_requires_math_input_and_does_not_hide_tampering(tmp_path):
    p=tmp_path/'a.plot.json';p.write_text(json.dumps(spec(3)))
    build(p);assert inspect_figures(tmp_path)['success']
    svg=tmp_path/'a.svg';svg.write_text(svg.read_text().replace('stroke-width: 2.5','stroke-width: 9.5'))
    assert not inspect_figures(tmp_path)['success']
    build(p);p.unlink()
    assert not inspect_figures(tmp_path)['success']


def test_runner_prepares_new_revision_once_before_author_work(compact_root,native_double):
    s,h,r=completed(compact_root,decks=1)
    repair,cid=proposal(s,r);confirm(repair,cid)
    preparations=[]
    def host(req):
        if req['operation']=='run' and req['packet']['kind']=='revise':
            preparations.append(req['packet']['source_preparation']['state'])
        return h(req)
    r.invoke=host;last=r.run(cycles=100,interval=0)
    assert repair.case(cid)['state']=='completed',last
    assert preparations==['prepared']


def test_prepare_reports_legacy_size_directives_without_mutating_text(tmp_path):
    source=source_tree(tmp_path);md=source/'presentation.md';md.chmod(0o644)
    md.write_text(md.read_text().replace('![Intersection]','![h:420px Intersection]'))
    before=md.read_bytes();target=tmp_path/'.mpres/work/a/output'
    report=prepare_edit_source(tmp_path,source,target)
    assert any('directives are forbidden' in e for e in report['remaining_source_errors'])
    assert (target/'presentation.md').read_bytes()==before==md.read_bytes()
    assert inspect_figures(target)['success']


def test_prepare_rejects_symlinked_image_before_overwriting_anywhere(tmp_path):
    source=source_tree(tmp_path);image=source/'assets/charging.svg';image.chmod(0o644);image.unlink()
    other=tmp_path/'outside.svg';other.write_text('user-owned file');image.symlink_to(other)
    target=tmp_path/'.mpres/work/a/output'
    with pytest.raises(MPresError,match='symlink'):prepare_edit_source(tmp_path,source,target)
    assert other.read_text()=='user-owned file' and not target.exists()


def test_legacy_v2_projection_and_transform_models_preserve_relationships():
    projection=mathematical_model({'version':2,'kind':'projection','point':[3,2],'direction':[1,0]})
    assert projection['foot']==(3,0) and projection['residual']==(0,2)
    transform=mathematical_model({'version':2,'kind':'transform','matrix':[[2,-1],[1,3]],'vectors':[[1,0],[0,1]]})
    assert transform['images']==[(2,1),(-1,3)]
