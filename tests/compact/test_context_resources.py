from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import json
import pytest
from mpres.control.input_packet import compile_inputs,check_budget,safe_file,snapshot_reference
from mpres.control.runner import Runner
from mpres.control.service import Service
from mpres.util import MPresError,read_yaml,write_yaml_atomic
from test_relational_control import compact_root,register
from test_deck_workflow import native_double
from test_review_first_repairs import proposal
from test_confirmed_repairs import completed,confirm


def make(root,name,data):
    p=root/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(data.encode() if isinstance(data,str) else data);return str(p)


def test_required_full_source_without_inline_xml(tmp_path):
    md=make(tmp_path,'presentation.md','# Lesson\n'+'Real content.\n'*1000)
    svg=make(tmp_path,'assets/a.svg','<svg>'+(' '*500000)+'</svg>');before=Path(md).read_bytes()
    packet=compile_inputs(tmp_path,{'input_files':[md,svg],'scope':'full_frozen_deck'});check_budget(packet,50000)
    assert packet['input_files']==[md] and packet['resource_manifest'][0]['path']==svg
    assert packet['context_bytes']<50000 and Path(md).read_bytes()==before


def test_math_data_is_required_scripts_not_executed(tmp_path):
    data=make(tmp_path,'a.plot.json','{"version":1}');script=make(tmp_path,'a.py','raise RuntimeError("never run")')
    packet=compile_inputs(tmp_path,{'input_files':[data,script]})
    assert packet['input_files']==[data] and packet['resource_manifest'][0]['kind']=='reproduction_source'


def test_reference_availability_is_not_a_reading_receipt(tmp_path):
    ref=make(tmp_path,'sources/book.txt','Textbook'*10000);md=make(tmp_path,'presentation.md','# Complete source')
    p=compile_inputs(tmp_path,{'input_files':[md,ref]},references=[ref])
    assert p['input_files']==[md] and p['resource_manifest'][0]['kind']=='approved_reference'
    assert 'not a reading receipt' in p['input_policy']['coverage']


def test_full_required_text_over_budget_never_truncated(tmp_path):
    md=make(tmp_path,'presentation.md','x'*50000);p=compile_inputs(tmp_path,{'input_files':[md]})
    with pytest.raises(MPresError,match='never truncated'):check_budget(p,2000)
    assert Path(md).stat().st_size==50000


def test_deduplicates_paths_not_content(tmp_path):
    md=make(tmp_path,'presentation.md','# Source');svg=make(tmp_path,'a.svg','<svg/>')
    p=compile_inputs(tmp_path,{'input_files':[md,md,svg,svg]})
    assert p['input_files']==[md] and len(p['resource_manifest'])==1 and p['required_text_bytes']==len('# Source')


@pytest.mark.parametrize('kind',['outside','inward_link','directory','missing','traversal'])
def test_unsafe_or_missing_file_is_rejected(tmp_path,kind):
    task=tmp_path/'task';task.mkdir();real=task/'real.txt';real.write_text('text')
    choices={'outside':tmp_path/'outside.txt','directory':task,'missing':task/'absent.txt','traversal':task/'..'/'outside.txt'}
    if kind=='inward_link':
        link=task/'link.txt';link.symlink_to(real);choices[kind]=link
    with pytest.raises(MPresError):safe_file(task,choices[kind])


def test_concurrent_reference_snapshot_readonly_and_immutable(tmp_path):
    make(tmp_path,'sources/book.txt','original')
    def create(_):return snapshot_reference(tmp_path,'sources/book.txt',tmp_path/'input',0)
    with ThreadPoolExecutor(max_workers=5) as pool:paths=list(pool.map(create,range(10)))
    assert len(set(paths))==1 and paths[0].read_text()=='original'
    assert not paths[0].stat().st_mode & 0o222
    (tmp_path/'sources/book.txt').write_text('changed')
    with pytest.raises(MPresError,match='snapshot changed'):create(0)
    assert paths[0].read_text()=='original'


def test_executable_not_allowed_as_reference(tmp_path):
    make(tmp_path,'sources/x.py','pass')
    with pytest.raises(MPresError):snapshot_reference(tmp_path,'sources/x.py',tmp_path/'input',0)


def test_missing_reference_is_not_dropped(tmp_path):
    with pytest.raises(MPresError,match='existing regular'):snapshot_reference(tmp_path,'missing.txt',tmp_path/'input',0)


def test_unit_writer_references_still_required(compact_root):
    from feedback_fixtures import infrastructure_only
    s=Service.create(compact_root,'unit','Unit');infrastructure_only(s)
    make(s.task,'sources/book.txt','Important definition')
    cfg=read_yaml(s.task/'task.yaml');cfg['workflow']='authoring'
    cfg['presentations']=[{'id':'p01','title':'Coordinates','units':[{'id':'l01','title':'Lesson','brief':'Explain coordinates.','sources':['sources/book.txt']}]}]
    write_yaml_atomic(s.task/'task.yaml',cfg);s.present();s.confirm('user');s.materialize()
    register(s);job=s.jobs()[0];a=s.bind(job['id'],'h1');packet=Runner(s.task).packet(job,a['id'])
    assert any(Path(p).read_text()=='Important definition' for p in packet['input_files'])


def test_deck_inherits_only_own_approved_references(compact_root,native_double):
    s,h,r=completed(compact_root,decks=2)
    make(s.task,'sources/p01.txt','Relevant theorem');make(s.task,'sources/p02.txt','Other theorem')
    # Structural fixture: populate the same approved dependency rows that planning creates.
    with s.store.transaction() as c:
        c.execute('UPDATE plan_items SET sources_json=? WHERE presentation=?',(json.dumps(['sources/p01.txt']),'p01'))
        c.execute('UPDATE plan_items SET sources_json=? WHERE presentation=?',(json.dumps(['sources/p02.txt']),'p02'))
    repair,cid=proposal(s,r);confirm(repair,cid);seen=[]
    def host(req):
        if req['operation']=='run' and req['packet'].get('repair_scope'):seen.append(req['packet'])
        return h(req)
    r.invoke=host;last=r.run(cycles=100,interval=0)
    assert repair.case(cid)['state']=='completed',last
    assert seen
    for p in seen:
        refs=[x for x in p['resource_manifest'] if x['kind']=='approved_reference']
        assert len(refs)==1 and Path(refs[0]['path']).read_text()=='Relevant theorem'
        assert refs[0]['path'] not in p['input_files']
        assert any(Path(f).name=='presentation.md' for f in p['input_files'])


def test_audience_uses_resource_policy_but_not_whole_pdf(compact_root,native_double):
    from mpres.control.audience import Audience
    s,h,r=completed(compact_root,decks=1);repair,cid=proposal(s,r);confirm(repair,cid)
    job=s.store.rows("SELECT * FROM jobs WHERE kind='review' AND round=2 AND channel='audience'")[0]
    session=s.store.rows("SELECT DISTINCT a.session_id FROM attempts a JOIN jobs j ON j.id=a.job_id WHERE j.kind='review' AND j.channel='audience'")[0]['session_id']
    a=s.bind(job['id'],session)
    with s.store.transaction() as c:runtime=s.expected_runtime(c,job)
    req=Audience(s.task).request(job,a,runtime);p=req['packet']
    assert p['slides'] and 'frozen_pdf' not in p and p['input_policy']['version']==1


def test_unrecognized_binary_is_not_required_text(tmp_path):
    blob=make(tmp_path,'a.bin',b'\xff\x00');p=compile_inputs(tmp_path,{'input_files':[blob]})
    assert not p['input_files'] and p['resource_manifest'][0]['kind']=='binary_resource'
