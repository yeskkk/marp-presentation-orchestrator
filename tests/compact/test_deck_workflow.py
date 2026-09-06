from __future__ import annotations

import json
import shutil
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

import fitz
import pytest

from mpres.control.quality import Quality
from mpres.control.runner import Runner
from mpres.control.service import CHANNELS, Service
from mpres.control.workflow import Workflow
from mpres.marp_source import parse_deck
from mpres.pdf_inspection import inspect_pdf_file
from mpres.util import MPresError, read_yaml, write_yaml_atomic
from test_relational_control import compact_root
from test_revision_quality import HEADER


def full_task(root, *, delivery='all', decks=2, units=2):
    s=Service.create(root,'full','Full workflow fixture')
    cfg=read_yaml(s.task/'task.yaml')
    cfg.update(workflow='full',delivery=delivery,author_concurrency=2)
    cfg['provider'].update(mode='command',command=['fixture-not-a-real-provider'],handle_limit=12,external_handles=1)
    cfg['presentations']=[{'id':f'p{i+1:02d}','title':'Coordinates','units':[
        {'id':f'l{j+1:02d}','title':'Quantities','brief':'Explain coordinates with units, an example, and a diagnostic question.','sources':[]}
        for j in range(units)]} for i in range(decks)]
    write_yaml_atomic(s.task/'task.yaml',cfg);s.present();s.confirm('user')
    return s


@pytest.fixture
def native_double(monkeypatch):
    """Only full rendering is simulated; source and PDF inspectors remain real.

    This fixture is not a selectable production adapter. It does not validate
    Marp/DOM rendering and must not be represented as a real browser acceptance.
    """
    original=Quality._run
    def checker(self, artifact, gate_id, level, settings):
        report=original(self,artifact,gate_id,'source',settings)
        if level=='source' or not report['success']:
            return report
        source=self.task/artifact['path']/'presentation.md';deck=parse_deck(source)
        output=self.task/'.mpres'/'gates'/gate_id/'presentation.pdf';output.parent.mkdir(parents=True)
        doc=fitz.open()
        for slide in deck.slides:
            page=doc.new_page(width=960,height=540)
            page.insert_text((72,92),slide.title or 'Coordinates',fontsize=28)
            page.insert_text((72,155),'Quantities and coordinates',fontsize=22)
        doc.save(output);doc.close();output.chmod(0o444)
        report['checks']['pdf']=inspect_pdf_file(output,expected_pages=len(deck.slides))
        report.update(success=report['checks']['pdf']['success'],pdf_path=str(output.relative_to(self.task)),test_double_not_native_renderer=True)
        return report
    monkeypatch.setattr(Quality,'_run',checker)
    return checker


class Host:
    """Deterministic semantic test double, not a model or quality evaluation."""
    def __init__(self, *, findings=False, malformed=None):
        self.handles={};self.calls=[];self.findings=findings;self.malformed=malformed
    def __call__(self, req):
        op=req['operation']
        if op=='capabilities':
            return {'handle_limit':12,'handles':['main',*self.handles], 'supports_close':False,'supports_reset':False,'usage_reporting':True,'receipt':'fixture-host-inventory'}
        if op=='create':
            handle='h-'+req['request_id'];self.handles[handle]=req['runtime']
            return {'handle':handle,'model':req['runtime']['model'],'reasoning_effort':req['runtime']['reasoning_effort'],'receipt':'fixture-created:'+handle}
        packet=req['packet'];self.calls.append(req)
        kind=packet['kind'];result={'summary':'Explained quantities with units and preserved the intended lesson scope.'}
        source=None
        if kind in {'write','edit','revise'}:
            output=Path(packet['writable_directory']);source='output'
            if kind=='write':
                sid=f"{packet['presentation']}-{packet['unit']['id']}-s1"
                (output/'presentation.md').write_text(HEADER+f'<!-- slide-id: {sid} -->\n<!-- _class: core -->\n# Quantities\n\nUse coordinates for two quantities.\n')
            else:
                assert (output/'presentation.md').is_file(), 'Editor must get a real writable copy'
                assert (output/'presentation.md').stat().st_mode & 0o200
            if kind=='revise':
                result['resolutions']=[{'finding_id':f['finding_id'],'status':'addressed','explanation':'Clarified the coordinate units at the cited slide.'} for f in packet['findings']]
                if self.malformed=='revision':result['resolutions']=[]
        if kind=='review':
            assert packet['scope']=='full_frozen_deck'
            assert packet['writable_directory'] is None
            assert Path(packet['frozen_pdf']).is_file()
            deck=parse_deck(Path(packet['frozen_source_directory'])/'presentation.md')
            findings=[]
            if self.findings and packet['channel']=='domain_accuracy':
                findings=[{'message':'Explain which units the coordinates carry.','slide_ids':[deck.slides[0].slide_id],'severity':'major'}]
            if self.malformed=='review':findings=[{'message':'Bad coordinate reference.','slide_ids':['invented-id'],'severity':'major'}]
            result['findings']=findings
        return {'runtime':req['runtime'],'receipt':'fixture-executed:'+req['attempt_id'],'source_dir':source,'result':result,
                'usage':[{'call_id':'fixture-call','counters':{'input_tokens':100,'cached_input_tokens':80,'output_tokens':5,'reasoning_tokens':0,'total_tokens':105}}]}


def run_host(service, host, cycles=60):
    runner=Runner(service.task);runner.invoke=host
    return runner,runner.run(cycles=cycles,interval=0)


def test_complete_two_decks_full_review_revision_release(compact_root,native_double):
    service=full_task(compact_root);host=Host(findings=True)
    runner,last=run_host(service,host)
    assert service.status()['status']=='completed', (last,Workflow(service.task).status())
    assert last['release_pipeline_enabled'] is True
    assert sorted(p.name for p in (service.task/'deliverables').iterdir())==['p01.pdf','p02.pdf']
    assert len(service.store.rows('SELECT * FROM releases'))==2
    assert len(service.store.rows("SELECT * FROM jobs WHERE kind='review' AND state='succeeded'"))==10
    assert len(service.store.rows("SELECT * FROM jobs WHERE kind='revise' AND state='succeeded'"))==2
    for d in service.store.rows('SELECT * FROM decks'):
        Workflow(service.task)._review_proof(d)
    assert len(host.handles)<=9  # two writers + one editor + five reviewers
    assert service.metrics()['attempt_coverage']==1
    assert not list(service.task.rglob('ASSIGNMENT-*'))
    assert not list(service.task.rglob('STAGE-ARTIFACT.md'))


def test_zero_findings_skips_model_revision(compact_root,native_double):
    service=full_task(compact_root,decks=1);host=Host()
    run_host(service,host)
    assert service.status()['status']=='completed'
    assert not service.store.rows("SELECT * FROM jobs WHERE kind='revise'")


@pytest.mark.parametrize('mode',['pilot','each'])
def test_feedback_pause_does_not_start_next_deck(compact_root,native_double,mode):
    service=full_task(compact_root,delivery=mode);host=Host()
    runner,result=run_host(service,host)
    assert result['status']=='paused'
    assert not [c for c in host.calls if c['packet']['presentation']=='p02']
    before=service.store.rows('SELECT * FROM configs')
    Workflow(service.task).continue_delivery('user','Continue with the same confirmed course plan.')
    runner.run(cycles=60,interval=0)
    assert service.status()['status']=='completed'
    assert service.store.rows('SELECT * FROM configs')==before


def test_missing_full_tool_blocks_before_any_reviewer(compact_root,monkeypatch):
    service=full_task(compact_root,decks=1);host=Host()
    import mpres.control.quality as module
    def missing(*a,**kw):raise MPresError('Pinned renderer unavailable')
    monkeypatch.setattr(module,'require_pinned_marp',missing)
    _,last=run_host(service,host)
    assert last['status']=='blocked'
    assert not [c for c in host.calls if c['packet']['kind']=='review']
    assert not list((service.task/'deliverables').iterdir())
    assert Workflow(service.task).status()['decisions']


def test_invented_review_evidence_never_becomes_finding(compact_root,native_double):
    service=full_task(compact_root,decks=1);host=Host(malformed='review')
    _,last=run_host(service,host)
    assert any(r['status']=='uncertain' for r in last.get('results',[]))
    assert not service.store.rows('SELECT * FROM findings')
    assert not list((service.task/'deliverables').iterdir())


def test_revision_cannot_omit_a_finding(compact_root,native_double):
    service=full_task(compact_root,decks=1);host=Host(findings=True,malformed='revision')
    _,last=run_host(service,host)
    assert any(r['status']=='uncertain' for r in last.get('results',[]))
    assert not service.store.rows('SELECT * FROM releases')


def test_completed_runner_does_not_duplicate_deliveries(compact_root,native_double):
    service=full_task(compact_root,decks=1);host=Host();runner,_=run_host(service,host)
    calls=len(host.calls);releases=service.store.rows('SELECT * FROM releases')
    events=service.store.rows("SELECT * FROM events WHERE kind='deck.delivered'")
    runner.run(cycles=2,interval=0)
    assert len(host.calls)==calls and service.store.rows('SELECT * FROM releases')==releases
    assert service.store.rows("SELECT * FROM events WHERE kind='deck.delivered'")==events


def test_release_cannot_rely_on_old_source_only_check(compact_root,native_double):
    service=full_task(compact_root,decks=1);host=Host();run_host(service,host)
    d=service.store.rows('SELECT * FROM decks')[0]
    with service.store.transaction() as c:
        c.execute("UPDATE gate_runs SET state='failed' WHERE artifact_id=? AND level='full'",(d['candidate_id'],))
    with pytest.raises(MPresError,match='successful full gate'):Workflow(service.task).publish(d)


def test_failed_native_gate_can_retry_without_model_call(compact_root,native_double,monkeypatch):
    service=full_task(compact_root,decks=1);host=Host()
    original=Quality._run
    def failure(self,artifact,gate_id,level,settings):
        if level=='full':return {'success':False,'checks':{},'failure_kind':'tool_or_input','errors':['fixture missing browser']}
        return original(self,artifact,gate_id,level,settings)
    monkeypatch.setattr(Quality,'_run',failure)
    runner,_=run_host(service,host);calls=len(host.calls)
    monkeypatch.setattr(Quality,'_run',original)
    assert Workflow(service.task).retry_checks('p01','Installed the required local rendering toolchain.')['state']=='passed'
    assert len(host.calls)==calls
    runner.run(cycles=60,interval=0)
    assert service.status()['status']=='completed'


def test_source_failure_is_routed_to_bounded_editor(compact_root,native_double):
    service=full_task(compact_root,decks=1,units=1);host=Host()
    def bad_unit(req):
        response=host(req)
        if req['operation']=='run' and req['packet']['kind']=='write':
            Path(req['packet']['writable_directory'],'presentation.md').write_text('# Broken unit without metadata')
        return response
    runner=Runner(service.task);runner.invoke=bad_unit;runner.run(cycles=60,interval=0)
    assert service.status()['status']=='running'
    deck=Workflow(service.task).status()['decks'][0]
    assert deck['phase']=='blocked' and 'budget' in deck['block_reason']
    repairs=service.store.rows("SELECT * FROM jobs WHERE kind='edit' AND plan_item_id IS NOT NULL")
    assert len(repairs)==2
    assert not list((service.task/'deliverables').iterdir())


def test_publication_crash_after_file_before_database_is_reconciled(compact_root,native_double,monkeypatch):
    import mpres.control.workflow as module
    service=full_task(compact_root,decks=1);host=Host()
    original_event=module.event;failed=[False]
    def crash(conn,kind,detail,job=None):
        if kind=='deck.delivered' and not failed[0]:
            failed[0]=True
            raise OSError('Injected interruption after exclusive file publication')
        return original_event(conn,kind,detail,job)
    monkeypatch.setattr(module,'event',crash)
    runner,last=run_host(service,host)
    assert service.status()['status']=='running'
    assert (service.task/'deliverables/p01.pdf').is_file()
    assert service.store.rows('SELECT state FROM releases')[0]['state']=='prepared'
    report=Workflow(service.task).retry_publish('p01','Verified the previous publisher stopped; reconcile its prepared release.')
    assert service.status()['status']=='completed'
    assert service.store.rows('SELECT state FROM releases')[0]['state']=='committed'
    assert len(service.store.rows("SELECT * FROM events WHERE kind='deck.delivered'"))==1


def test_explicit_repeat_publish_never_repauses_task(compact_root,native_double):
    service=full_task(compact_root,delivery='pilot');host=Host();runner,_=run_host(service,host)
    old=service.store.rows("SELECT * FROM decks WHERE presentation='p01'")[0]
    Workflow(service.task).continue_delivery('user','Proceed unchanged.')
    assert Workflow(service.task).publish(old)['already_published']
    assert service.status()['status']=='running'
    assert len(service.store.rows("SELECT * FROM events WHERE kind='deck.delivered'"))==1


def test_full_workflow_empty_source_checks_cannot_fake_completion(compact_root,native_double):
    service=full_task(compact_root,decks=1);Workflow(service.task).ensure()
    d=Workflow(service.task).status()['decks'][0]
    with pytest.raises(MPresError):Workflow(service.task).publish(d)
    assert not service.store.rows('SELECT * FROM releases')


def test_concurrent_advance_never_creates_duplicate_editor(compact_root,native_double):
    service=full_task(compact_root,decks=1,units=1);host=Host();runner=Runner(service.task);runner.invoke=host
    runner.run_once();runner.run_once()  # create writer, then one actual write
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(lambda _:Workflow(service.task).advance(),range(2)))
    assert len(service.store.rows("SELECT * FROM jobs WHERE kind='assemble'"))==1
    assert len(service.store.rows("SELECT * FROM jobs WHERE kind='edit' AND plan_item_id IS NULL"))==1
