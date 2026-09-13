from __future__ import annotations
import json
import pytest
from mpres.control.inspection import normalize_check, normalize_report, page_check, plan_checks
from mpres.control.quality import Quality
from mpres.control.delivery import Delivery
from mpres.control.workflow import Workflow
from mpres.util import MPresError, read_yaml, write_yaml_atomic
from test_relational_control import compact_root, prepare
from test_revision_quality import revision, good_source, HEADER
from test_deck_workflow import full_task, Host, run_host, native_double

@pytest.mark.parametrize('stage,count,severity',[
 ('plan',100,None),('plan',101,'error'),('draft',100,None),('draft',120,None),
 ('draft',121,'warning'),('draft',130,'warning'),('draft',131,'error'),
 ('delivery',100,None),('delivery',120,None),('delivery',121,'error'),('delivery',130,'error'),('delivery',131,'error')])
def test_page_boundaries(stage,count,severity):
    c=page_check(count,stage)
    assert [r['severity'] for r in c['issues']]==([] if severity is None else [severity])
    assert c['success']==(severity!='error')

@pytest.mark.parametrize('count',[0,-1,True,1.5])
def test_invalid_page_counts(count):
    with pytest.raises(MPresError):page_check(count)

def test_warning_does_not_block_and_error_cannot_be_downgraded():
    r=normalize_check('density',{'success':False,'warnings':['Possibly dense']})
    assert r['success'] and r['issues'][0]['severity']=='warning'
    assert normalize_check('density',r)==r
    assert not normalize_check('math',{'success':True,'errors':['Wrong'], 'warnings':['Dense']})['success']
    assert not normalize_check('browser',{'success':True,'returncode':1,'warnings':['Unavailable']})['success']
    assert not normalize_check('browser',{'execution_state':'not_run'})['success']
    assert not normalize_check('unknown',{'success':False})['success']
    assert not normalize_report({'success':False,'checks':{'source':{'success':True}}})['success']

def test_plan_can_be_presented_but_oversize_not_confirmed(compact_root):
    from mpres.control.service import Service
    s=Service.create(compact_root,'large','Large lesson');cfg=read_yaml(s.task/'task.yaml')
    cfg['presentations']=[{'id':'p01','title':'Lesson','estimated_pages':101,'units':[{'id':'l01','title':'Topic','brief':'Explain a quantity with examples','sources':[]}]}]
    write_yaml_atomic(s.task/'task.yaml',cfg)
    assert not s.present()['page_estimates']['p01']['success']
    with pytest.raises(MPresError,match='100 estimated'):s.confirm('user')
    assert not s.store.rows('SELECT * FROM configs')

def test_missing_legacy_estimate_is_unknown_not_zero():
    c=plan_checks({'presentations':[{'id':'p01'}]})['p01']
    assert c['success'] and c['estimated_pages'] is None and len(c['warnings'])==1

@pytest.mark.parametrize('count,success',[(121,True),(130,True),(131,False)])
def test_source_gate_page_policy(compact_root,count,success):
    s=prepare(compact_root);src=good_source(s)
    src.joinpath('presentation.md').write_text(HEADER+'\n\n---\n\n'.join(f'<!-- slide-id: p01-l01-s{i} -->\n<!-- _class: core -->\n# Page {i}\n\nA mathematical relation.' for i in range(count)))
    aid=revision(s,src);g=Quality(s.task).inspect(aid);r=json.loads(g['detail_json'])
    assert (g['state']=='passed')==success,r
    assert r['checks']['pages']['page_count']==count
    assert r['warning_count']==(1 if success else 0)

def test_delivery_current_warning_report(compact_root,native_double,monkeypatch):
    original=Quality._run
    def warnings(self,*args):
        r=original(self,*args);r['checks']['source'].setdefault('warnings',[]).append('A density concern remains.');return r
    monkeypatch.setattr(Quality,'_run',warnings)
    s=full_task(compact_root,decks=1);_,done=run_host(s,Host(findings=True))
    assert done['status']=='completed',done
    folder=s.task/'deliverables/p01';note=json.loads((folder/'WARNINGS.json').read_text())
    assert note['unresolved_count']==1
    assert '未处理 warning：1 条' in (folder/'WARNINGS.md').read_text()
    r=s.store.rows('SELECT * FROM releases')[0]
    assert (note['gate_id'],note['artifact_id'])==(r['gate_id'],r['artifact_id'])
    assert Delivery(s.task).status()['entries'][0]['warning_report']['unresolved_count']==1
    before=(folder/'WARNINGS.md').stat().st_mtime_ns
    assert Delivery(s.task).materialize()['already_materialized']
    assert (folder/'WARNINGS.md').stat().st_mtime_ns==before

def test_zero_report_explicit_not_part_of_source(compact_root,native_double):
    s=full_task(compact_root,decks=1);_,done=run_host(s,Host())
    assert done['status']=='completed',done
    r=s.store.rows('SELECT * FROM releases')[0]
    a=s.store.rows('SELECT path FROM artifacts WHERE id=?',(r['artifact_id'],))[0]
    assert not (s.task/a['path']/'WARNINGS.md').exists()
    assert json.loads((s.task/'deliverables/p01/WARNINGS.json').read_text())['unresolved_count']==0

def test_historical_release_is_not_blanket_pid_exemption(compact_root,native_double):
    s=full_task(compact_root,decks=1);_,done=run_host(s,Host())
    d=s.store.rows('SELECT * FROM decks')[0];g=Quality(s.task).latest(d['candidate_id'],'full')
    g['detail_json']=json.dumps({'checks':{'pdf':{'page_count':194}}})
    Workflow(s.task)._delivery_pages(d,g)
    with s.store.transaction() as c:c.execute("UPDATE release_versions SET state='prepared'")
    with pytest.raises(MPresError,match='delivery limit 120'):Workflow(s.task)._delivery_pages(d,g)
    g['detail_json']=json.dumps({'checks':{'pdf':{'page_count':120}}})
    Workflow(s.task)._delivery_pages(d,g)


def test_warning_export_failure_retries_without_models_or_new_gates(compact_root,native_double,monkeypatch):
    import shutil
    import mpres.control.inspection as module
    s=full_task(compact_root,decks=1);host=Host();_,done=run_host(s,host)
    assert done['status']=='completed'
    attempts=s.store.rows('SELECT * FROM attempts');gates=s.store.rows('SELECT * FROM gate_runs');calls=len(host.calls)
    shutil.rmtree(s.task/'deliverables/p01')
    original=module.write_warning_report;count=[0]
    def temporary_failure(*args):
        count[0]+=1
        if count[0]==1:raise OSError('temporary warning export failure')
        return original(*args)
    monkeypatch.setattr(module,'write_warning_report',temporary_failure)
    assert Delivery(s.task).ensure()['state']=='failed'
    assert Delivery(s.task).ensure()['state']=='ready'
    assert s.store.rows('SELECT * FROM attempts')==attempts
    assert s.store.rows('SELECT * FROM gate_runs')==gates
    assert len(host.calls)==calls
    assert (s.task/'deliverables/p01/WARNINGS.md').is_file()
