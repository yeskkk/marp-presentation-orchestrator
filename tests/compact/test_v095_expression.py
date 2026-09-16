from pathlib import Path
import pytest
from mpres.control.prose_layout import inspect
from mpres.control.guidance import compile_guidance
from mpres.control.expression import discipline
from mpres.control.repairs import Repairs
from test_relational_control import compact_root
from test_deck_workflow import native_double
from test_confirmed_repairs import completed, confirm

HEADER='---\nmarp: true\n---\n<!-- slide-id: p01-a -->\n'

@pytest.mark.parametrize('body,ok',[
    ('设 $A$ 为方阵。求 $A$ 的行列式。',False),
    ('设 $A$ 为方阵。\n求 $A$ 的行列式。',False),
    ('设 $A$ 为方阵。  \n求 $A$ 的行列式。',True),
    ('设 $A$ 为方阵。\\\n求 $A$ 的行列式。',True),
    ('设 $A$ 为方阵。\n\n求 $A$ 的行列式。',True),
    ('若 $A$ 可逆，则 $Ax=b$ 有唯一解。',True),
    ('# 矩阵乘法\n\n计算 $AB$。',True),
    ('$$\nA=1.2\n$$\n\n求 $A$。',True),
    ('`第一句。第二句。` 是代码。',True),
    ('[文献](https://example.com/a.b) 给出数值 1.2。',True),
    ('> 先计算。再验算。',False),
    ('- 先计算。  \n  再验算。',True),
    ('“这个方程无解。”该判断对吗？',False),
])
def test_sentence_runs_preserve_math_and_markdown(tmp_path,body,ok):
    p=tmp_path/'presentation.md';p.write_text(HEADER+body+'\n');before=p.read_bytes()
    result=inspect(tmp_path)
    assert result['success'] is ok,result
    assert not result['title_required'] and p.read_bytes()==before


def test_guidance_routes_mathematics_without_enforcing_it_on_other_courses():
    root=Path(__file__).resolve().parents[2]
    m=compile_guidance(root,'review',channel='language',repair=True,discipline='mathematics')
    g=compile_guidance(root,'review',channel='language',discipline='general')
    assert '矩阵是“可逆”' in m['text'] and '矩阵是“可逆”' not in g['text']
    assert '标题是可选组件' in m['text'] and '白名单' in m['text']
    assert discipline({'title':'线性代数','teaching':{}})=='mathematics'
    assert discipline({'title':'线性代数','teaching':{'discipline':'general'}})=='general'


def test_incidental_finding_is_not_filtered_by_initial_repair_focus(compact_root,native_double):
    s,h,r=completed(compact_root,decks=1)
    repair=Repairs(s.task)
    case=repair.open('修复术语问题。',['p01'],'user',focus='student-expression')
    r.run(cycles=80,interval=0);confirm(repair,case['case_id'])
    seen=[]
    def adapter(req):
        reply=h(req)
        if req['operation']=='run' and req['packet'].get('repair_scope'):
            p=req['packet']
            if p['kind']=='review' and p['channel']=='language':
                from mpres.marp_source import parse_deck
                sid=parse_deck(Path(p['frozen_source_directory'])/'presentation.md').slides[0].slide_id
                reply['result']['findings'].append({'message':'Fixture incidental page-caption issue outside the initial terminology family.','slide_ids':[sid],'severity':'major'})
            if p['kind']=='revise':seen.extend(p['findings'])
        return reply
    r.invoke=adapter
    final=r.run(cycles=120,interval=0)
    assert repair.case(case['case_id'])['state']=='completed',final
    assert any('incidental' in f['message'] for f in seen)
    assert all(x['resolution_json'] for x in s.store.rows('SELECT * FROM findings'))
    assert len(s.store.rows("SELECT * FROM jobs WHERE kind='review' AND round=2"))==5
