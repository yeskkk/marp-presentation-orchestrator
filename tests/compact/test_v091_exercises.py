import json
from pathlib import Path
import pytest
from mpres.control.exercises import (FILE, read_manifest, isolated_question, review_scope,
    validate_checks, validate_author, source_check, merge_manifests)
from mpres.control.quote_evidence import quoted_evidence_present
from mpres.control.input_packet import snapshot_reference
from mpres.util import MPresError

HEADER='---\nmarp: true\ntheme: mathist-academic\n---\n'

def source(tmp_path,question='沿用上一页矩阵 A，求 Ax=b。',answer='A=2，b=4。'):
    tmp_path.mkdir(parents=True,exist_ok=True)
    (tmp_path/'presentation.md').write_text(HEADER+'<!-- slide-id: q -->\n# 随堂练习\n'+question+'\n\n---\n<!-- slide-id: a -->\n# 解答\n'+answer)
    (tmp_path/FILE).write_text(json.dumps({'version':1,'exercises':[{'exercise_id':'e1','question_slide_id':'q','answer_slide_ids':['a'],'learning_goal':'求解已给定的系统'}]}))
    return tmp_path


def test_legacy_source_not_retroactively_approved(tmp_path):
    s=source(tmp_path);(s/FILE).unlink()
    assert read_manifest(s) is None
    assert source_check(s)['semantic_sufficiency']=='not_proven_by_program'
    assert review_scope(s)['manifest_status']=='historical_unindexed'
    with pytest.raises(MPresError,match='required'):read_manifest(s,required=True)


def test_question_isolation_excludes_answer_and_notes(tmp_path):
    s=source(tmp_path,'求 Ax=b。\n<!-- A=7; b=14; teacher notes -->')
    q=isolated_question(s,'q')
    assert 'A=7' not in q['markdown'] and 'A=2' not in q['markdown']
    assert q['question_slide_id']=='q' and '解答' not in q['markdown']


@pytest.mark.parametrize('mutation', ['question_array','missing_answer','same_answer','duplicate','unclassified'])
def test_manifest_cannot_split_or_lose_identity(tmp_path,mutation):
    s=source(tmp_path);m=json.loads((s/FILE).read_text());r=m['exercises'][0]
    if mutation=='question_array':r['question_slide_id']=['q','a']
    elif mutation=='missing_answer':r['answer_slide_ids']=['absent']
    elif mutation=='same_answer':r['answer_slide_ids']=['q']
    elif mutation=='duplicate':m['exercises'].append(r.copy())
    else:m['exercises']=[]
    (s/FILE).write_text(json.dumps(m))
    with pytest.raises(MPresError):read_manifest(s,required=True)


def test_coverage_is_not_an_author_boolean(tmp_path):
    s=source(tmp_path)
    with pytest.raises(MPresError):validate_author(s,{'self_contained':True},required=True)
    validate_author(s,{'exercise_checked_slide_ids':['q']},required=True)
    # Program explicitly does not claim that the missing A became sufficient.
    assert source_check(s)['semantic_sufficiency']=='not_proven_by_program'


def test_semantic_missing_information_requires_blocking_finding(tmp_path):
    s=source(tmp_path);scope=review_scope(s)
    result={'exercise_checks':[{'question_slide_id':'q','status':'missing_information','finding_index':0}],
            'findings':[{'message':'本页缺少矩阵 A 和右端 b，不能独立求解。','slide_ids':['q'],'severity':'major'}]}
    validate_checks(result,scope,{'q','a'})
    result['findings'][0]['severity']='minor'
    with pytest.raises(MPresError,match='blocking'):validate_checks(result,scope,{'q','a'})
    result['findings']=[]
    with pytest.raises(MPresError,match='same-page'):validate_checks(result,scope,{'q','a'})


def test_coverage_omission_and_renaming_rejected(tmp_path):
    s=source(tmp_path);scope=review_scope(s)
    with pytest.raises(MPresError,match='omitted'):validate_checks({'findings':[]},scope,{'q','a'})
    bad={'findings':[],'exercise_checks':[{'question_slide_id':'q','status':'not_exercise','reason':'一页写不下','finding_index':None}]}
    with pytest.raises(MPresError,match='rename'):validate_checks(bad,scope,{'q','a'})


@pytest.mark.parametrize('question',[
    '已知 A=LU，L=[1,0;2,1]，U=[3,1;0,2]，求 Ax=(1,4)。',
    '向矩阵添加一列已有列的线性组合，秩怎样变化？',
    '已知 det(B)=2det(A)，det(B)=6，求 det(A)。'])
def test_sufficient_relationships_not_lexically_rejected(tmp_path,question):
    s=source(tmp_path,question)
    assert read_manifest(s)['exercises']
    validate_checks({'exercise_checks':[{'question_slide_id':'q','status':'sufficient','finding_index':None}]},review_scope(s),{'q','a'})


@pytest.mark.parametrize('quote,text',[
    ('存在 $x$。','存在 x；'),('A=LU','A = L U'),('a  b','a\nb'),
    ('向量 \\(v_1\\) 不变。','向量 $v_1$ 不变；')])
def test_format_only_evidence(quote,text):
    # A=LU and A=L U use different identifier tokens and are NOT normalized.
    assert quoted_evidence_present(quote,text)==(quote!='A=LU')


@pytest.mark.parametrize('quote,text', [('12','1 2'),('A=-1','A=1'),('不成立','成立'),('x_1','x_2'),('价格 $2','价格 2'),('det(A)=1','det(A)=10')])
def test_evidence_cannot_change_numbers_signs_negation_or_currency(quote,text):
    assert not quoted_evidence_present(quote,text)


def test_shared_reference_cache_pins_attempts_without_duplicate_books(tmp_path):
    s=tmp_path/'sources';s.mkdir();(s/'book.txt').write_text('Reference text'*1000)
    a=snapshot_reference(tmp_path,'sources/book.txt',tmp_path/'.mpres/work/a/input',0)
    b=snapshot_reference(tmp_path,'sources/book.txt',tmp_path/'.mpres/work/b/input',0)
    assert a==b and len(list((tmp_path/'.mpres/resource-cache').iterdir()))==1
    assert len(list((tmp_path/'.mpres/work').rglob('*.reference.json')))==2
    assert not list((tmp_path/'.mpres/work').rglob('book.txt'))
