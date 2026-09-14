from __future__ import annotations
from copy import deepcopy
import json
import pytest
from mpres.control.review_data import prepare, storage_result
from mpres.control.semantic import validate
from mpres.control.feedback import Feedback
from mpres.util import MPresError
from test_relational_control import compact_root
from test_deck_workflow import native_double
from test_audience_reading import audience_ready

class Rows:
    def __init__(self,steps): self.steps=steps
    def rows(self,*args):return self.steps
class Service:
    def __init__(self,steps): self.store=Rows(steps)

def fixture():
    f={'message':'Explain the mathematical object.','slide_ids':['s1'],'severity':'major'}
    step={'sequence':0,'phase':'student','state':'completed','result_json':json.dumps({'summary':'Meaning is missing','findings':[f]})}
    return Service([step]),{'id':'j1','kind':'review','channel':'audience'},f

def test_prior_findings_merge_without_model_copy():
    s,j,f=fixture();raw={'summary':'Combined review','findings':[]}
    out=prepare(s,j,'a1',raw)
    assert out['findings']==[f] and raw['findings']==[]
    assert storage_result(j,out)=={'summary':'Combined review','finding_ids':['j1:1'],'storage_schema':'review-references-v1'}

def test_exact_duplicate_coalesces_but_similar_is_preserved():
    s,j,f=fixture();other={**f,'message':f['message']+' Explain units as well.'}
    out=prepare(s,j,'a1',{'summary':'Review','findings':[f,other]})
    assert out['findings']==[f,other]

@pytest.mark.parametrize('reference',['step:2:1','other-job:1','new:0','new:2'])
def test_foreign_or_unknown_reference_rejected(reference):
    s,j,f=fixture()
    with pytest.raises(MPresError,match='reference'):
        prepare(s,j,'a1',{'summary':'Review','findings':[f],'finding_refs':[reference]})

def test_feedback_and_repair_share_single_problem():
    s,j,f=fixture();raw={'summary':'Review','findings':[],
       'feedback_checks':[{'id':'F1','version':1,'status':'issue','finding_refs':['step:0:1']}],
       'repair_checks':[{'problem_id':'P1','status':'needs_decision','finding_refs':['step:0:1']}]}
    validate('review-result',raw)
    out=prepare(s,j,'a1',raw)
    assert out['findings']==[f]
    assert out['feedback_checks'][0]['finding_refs']==['j1:1']
    assert out['repair_checks'][0]['finding_refs']==['j1:1']
    assert out['feedback_checks'][0]['evidence']==[] # no invented quote
    assert out['repair_checks'][0]['slide_ids']==[] # evidence is linked, not copied

@pytest.mark.parametrize('status',['satisfied','not_applicable'])
def test_problem_reference_cannot_certify_success(status):
    s,j,f=fixture();row={'id':'F','version':1,'status':status,'finding_refs':['step:0:1'],'explanation':'Claim','evidence':[]}
    with pytest.raises(MPresError):prepare(s,j,'a1',{'summary':'R','findings':[],'feedback_checks':[row]})

def test_non_audience_review_links_its_local_problem():
    s,j,f=fixture();j['channel']='domain_accuracy'
    out=prepare(s,j,'a',{'summary':'R','findings':[f],'repair_checks':[{'problem_id':'P','status':'needs_decision','finding_refs':['new:1']}]})
    assert out['repair_checks'][0]['finding_refs']==['j1:1']
    with pytest.raises(MPresError):prepare(s,j,'a',{'summary':'R','findings':[],'finding_refs':['step:0:1']})

def test_existing_steps_required_before_merge():
    s,j,f=fixture();s.store.steps[0]['state']='dispatched'
    with pytest.raises(MPresError,match='passes must finish'):prepare(s,j,'a',{'summary':'R','findings':[]})

def test_step_catalog_does_not_repeat_problem_text_in_final_packet(compact_root,native_double):
    s,r,h,req=audience_ready(compact_root)
    f={'message':'A long explanation of the missing relation. '*200,'slide_ids':[req['packet']['read_slide_ids'][0]],'severity':'major'}
    result=h(req);result['result']['findings']=[f];r.accept(req,result)
    req=r.tick()['requests'][0];r.accept(req,h(req))
    final=r.tick()['requests'][0]
    assert 'findings' not in final['packet']['audience_reading'][0]
    assert f['message'] not in json.dumps(final['packet'],ensure_ascii=False)
    assert 'merged by the control plane' in final['packet']['instructions']
    response=h(final);response['result']['finding_refs']=['step:0:1']
    r.accept(final,response)
    a=s.attempt(final['attempt_id']);stored=json.loads(a['result_json'])
    assert stored['finding_ids'] and 'findings' not in stored
    assert json.loads(s.store.rows('SELECT detail_json FROM findings WHERE job_id=?',(a['job_id'],))[0]['detail_json'])==f
    assert r.accept(final,response)['already_submitted']
    assert len(s.store.rows("SELECT id FROM events WHERE kind='review.result_received' AND job_id=?",(a['job_id'],)))==1


def test_quote_relocation_only_unique_verbatim_known_coordinates():
    from mpres.control.review_data import relocate_exact_quotes
    slides={'s1':'First slide.','s2':'The exact quoted sentence. Shared text.','s3':'Shared text.'}
    for quote,old,wanted in [('The exact quoted sentence.','s1','s2'),('Shared text.','s1','s1'),('Invented wording','s1','s1'),('The exact quoted sentence.','unknown','unknown'),('First slide.','s1','s1')]:
        raw={'feedback_checks':[{'id':'F','status':'satisfied','explanation':'unchanged','evidence':[{'quote':quote,'slide_id':old}]}],'findings':[]}
        value=deepcopy(raw);relocate_exact_quotes(value,slides)
        expected=deepcopy(raw);expected['feedback_checks'][0]['evidence'][0]['slide_id']=wanted
        assert value==expected and raw['feedback_checks'][0]['evidence'][0]['slide_id']==old
