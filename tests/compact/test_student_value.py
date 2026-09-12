"""Student-facing reasoning contracts, not a claim of model teaching quality."""
from __future__ import annotations
import copy,json
from pathlib import Path
import pytest
import yaml
from mpres.control.audience import Audience, attention_candidates
from mpres.control.feedback import Feedback
from mpres.control.runner import Runner
from mpres.control.service import Service, settings_document
from mpres.control.semantic import teaching_context, teaching_conflicts
from mpres.util import MPresError
from test_relational_control import compact_root, prepare, register
from test_deck_workflow import full_task, Host, native_double
from test_revision_quality import HEADER

BAD='''# 几个条件能否同时满足？

先修：平面直角坐标系。

目标：定义解与解集，分别论证存在性与唯一性。

这些数字是教学模拟，不是充电站的实际统计。

本页已按要求增加近期案例。
'''


def value_ready(root):
    service=full_task(root,decks=1,units=1);host=Host();runner=Runner(service.task)
    def invoke(req):
        response=host(req)
        if req['operation']=='run' and req['packet']['kind']=='write':
            (Path(req['packet']['writable_directory'])/'presentation.md').write_text(
                HEADER+'<!-- slide-id: p01-l01-s1 -->\n<!-- _class: core -->\n'+BAD+'\n---\n<!-- slide-id: p01-l01-s2 -->\n<!-- _class: core -->\n# Check both conditions\n\nSubstitute the pair into each equation.\n')
        return response
    runner.invoke=invoke
    for _ in range(45):
        runner.observe_host(host({'operation':'capabilities'}))
        for req in runner.tick()['requests']:
            if req['operation']=='audience_step' and req['packet']['phase']=='production_language':
                return service,runner,host,req
            runner.accept(req,invoke(req))
    raise AssertionError('Did not reach attention reading')


def decisions(host,req):
    response=host(req);result=response['result'];result['attention_checks']=[]
    for candidate in req['packet']['attention_candidates']:
        is_assumption='教学模拟' in candidate['quote']
        index=None
        if not is_assumption:
            index=len(result['findings'])
            result['findings'].append({'slide_ids':[candidate['slide_id']],'severity':'minor',
                'message':'移走备课/合规自述，让学生直接做坐标回顾问题。片段：'+candidate['quote']})
        result['attention_checks'].append({'candidate_id':candidate['candidate_id'],
            'disposition':'keep' if is_assumption else 'move_to_notes',
            'learning_loss_if_removed':('学生会误把假定的充电量用于估算真实站点需求，丢失模型与统计的边界。' if is_assumption
                                        else '无数学学习损失；本段不定义对象、不参与例题，也没有给必要条件。'),
            'reason':'保护解释结果的真实模型条件，而不是保护制作口吻。' if is_assumption else '先修和合规是制作者记录，学习通过后续实际任务发生。',
            'finding_index':index})
    return response


def test_candidate_signals_cover_reported_examples_but_never_delete_source():
    snippets=['先修：二元一次方程。','核心约40分钟。','目标：定义解；分别论证。',
              '教学假设：功率固定。','不代表充电站的地理位置。','阅读：book.txt L12-L15',
              '代数证明保证结论适用于一般维数。','本页已按要求补充资料。']
    source=[{'slide_id':f's{i}','markdown':text} for i,text in enumerate(snippets)]
    before=copy.deepcopy(source);c=attention_candidates(source)
    assert {x['slide_id'] for x in c}=={x['slide_id'] for x in source}
    assert source==before and all(x['quote'] and x['question'] for x in c)


def test_code_and_mathematical_notation_do_not_become_attention_signals():
    source=[{'slide_id':'s1','markdown':'```text\n先修：example\n```\n\n`教学假设` 是待编辑文本。\n\n$\\text{核心}$\n\n假设矩阵可逆，则解唯一。'}]
    assert attention_candidates(source)==[]


def test_each_candidate_has_explicit_learning_loss_and_route(compact_root,native_double):
    s,r,h,req=value_ready(compact_root);p=req['packet']
    assert p['reading_protocol']==2 and len(p['attention_candidates'])>=3
    assert 'attention_checks' in p['result_schema']['required']
    assert 'ATTENTION VALUE' in p['instructions']
    assert '删除反事实' in p['teaching_context']['rubric']['test']
    before=s.store.rows('SELECT * FROM artifacts')
    response=decisions(h,req);r.accept(req,response)
    assert s.store.rows('SELECT * FROM artifacts')==before
    final=r.tick()['requests'][0]
    context=final['packet']['audience_reading']
    assert any(step.get('attention_checks') for step in context)
    assert len(s.store.rows("SELECT * FROM jobs WHERE channel='audience'"))==1


@pytest.mark.parametrize('fault',['missing','duplicate','unknown','generic','unrouted','wrong_page'])
def test_cannot_bypass_question_with_old_compliance_reason(compact_root,native_double,fault):
    s,r,h,req=value_ready(compact_root);response=decisions(h,req);result=response['result']
    if fault=='missing':result.pop('attention_checks')
    elif fault=='duplicate':result['attention_checks'].append(copy.deepcopy(result['attention_checks'][0]))
    elif fault=='unknown':result['attention_checks'][0]['candidate_id']='invented'
    elif fault=='generic':result['attention_checks'][0].update(disposition='keep',finding_index=None,learning_loss_if_removed='属于教学内容。')
    elif fault=='unrouted':result['attention_checks'][0]['finding_index']=None
    elif fault=='wrong_page':result['findings'][0]['slide_ids']=['unread-page']
    with pytest.raises(MPresError):r.accept(req,response)
    assert s.store.rows("SELECT state FROM audience_steps WHERE phase='production_language'")[0]['state']=='dispatched'


def test_replay_does_not_duplicate_reading_or_turns(compact_root,native_double):
    s,r,h,req=value_ready(compact_root);response=decisions(h,req)
    assert not r.accept(req,response)['already_recorded']
    before=s.store.rows('SELECT * FROM usage')
    assert r.accept(req,response)['already_recorded']
    assert s.store.rows('SELECT * FROM usage')==before


def test_old_dispatched_contract_receipt_is_not_reinterpreted(compact_root,native_double):
    s,r,h,req=value_ready(compact_root)
    with s.store.transaction() as conn:
        conn.execute("DELETE FROM events WHERE kind='audience.contract'")
    before=s.store.rows('SELECT * FROM configs');a=Audience(s.task)
    a.ensure(req['attempt_id']);assert a.protocol(req['attempt_id'])==1
    old=h(req);assert 'attention_checks' not in old['result']
    assert not r.accept(req,old)['already_recorded']
    assert s.store.rows('SELECT * FROM configs')==before


def test_new_concern_seed_is_additive_and_does_not_change_runtime(compact_root):
    s=prepare(compact_root,count=1)
    with s.store.transaction() as conn:conn.execute("DELETE FROM feedback_rules WHERE id='student-learning-value'")
    before=s.store.rows('SELECT * FROM configs')
    old=s.store.rows('SELECT * FROM feedback_rules')
    Feedback(s.task).seed()
    assert any(x['id']=='student-learning-value' for x in Feedback(s.task).list())
    assert all(row in s.store.rows('SELECT * FROM feedback_rules') for row in old)
    assert s.store.rows('SELECT * FROM configs')==before


@pytest.mark.parametrize('depth',['minimal','explanatory','rigorous'])
def test_proof_depth_is_user_configured_not_guessed(compact_root,depth):
    s=Service.create(compact_root,'teaching','Algebra')
    settings=yaml.safe_load((s.task/'task.yaml').read_text())
    settings['presentations']=[{'id':'p01','title':'Conditions','units':[{'id':'l01','title':'Solutions','brief':'Learn what satisfies all conditions.','sources':[]}]}]
    settings['teaching']={'audience':'Students new to mathematics','proof_depth':depth}
    (s.task/'task.yaml').write_text(yaml.safe_dump(settings))
    (s.task/'TASK.md').write_text('Teach meaningful linear equations with accurate terms.')
    shown=s.present();assert shown['teaching_context']['proof_depth']==depth
    s.confirm('user');stored=s.store.rows('SELECT settings_json FROM configs')[0]['settings_json']
    assert json.loads(stored)['teaching']['proof_depth']==depth


def test_legacy_teaching_absence_not_silently_filled_or_confirmed():
    assert teaching_context({})['proof_depth'] is None
    assert teaching_context({})['status']=='from_confirmed_task_and_feedback'


def test_minimal_proof_conflict_is_presented_as_specific_hint(compact_root):
    s=Service.create(compact_root,'conflict','Algebra')
    cfg=yaml.safe_load((s.task/'task.yaml').read_text())
    cfg['presentations']=[{'id':'p01','title':'Solutions','units':[{'id':'l01','title':'Sets','brief':'保留所有证明，练习两包含证明。','sources':[]}]}]
    (s.task/'task.yaml').write_text(yaml.safe_dump(cfg));(s.task/'TASK.md').write_text('保留正确证明。')
    shown=s.present();hints=shown['teaching_conflicts']
    assert {h['location'] for h in hints}=={'TASK.md','p01/l01'}
    assert all(h['quote'] in ['保留正确证明。','保留所有证明，练习两包含证明。'] for h in hints)
    assert teaching_conflicts({**cfg,'presentations':[]},'不要保留所有证明。')==[]


def test_writer_packet_receives_same_learning_value_without_process_files(compact_root):
    s=prepare(compact_root,count=1);register(s);attempt=s.bind(s.jobs()[0]['id'],'h1')
    packet=Runner(s.task).packet(s.jobs()[0],attempt['id'])
    assert '学习损失' in packet['teaching_context']['rubric']['test']
    assert '先修' in packet['semantic_guidance'] and '删除反事实' in packet['semantic_guidance']
    assert not list(s.task.rglob('TEACHING-*.md'))


def test_reject_unknown_teaching_keys(compact_root):
    s=prepare(compact_root,count=1);cfg=json.loads(s.store.rows('SELECT settings_json FROM configs')[0]['settings_json'])
    cfg['teaching']['auto_change_model']=True
    with pytest.raises(MPresError,match='audience and proof_depth'):settings_document(cfg)
