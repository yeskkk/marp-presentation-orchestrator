from pathlib import Path
import pytest
from mpres.control.guidance import compile_guidance, audience_guidance

ROOT=Path(__file__).resolve().parents[2]

@pytest.mark.parametrize('kind,channel', [('write',None),('edit',None),('revise',None),('review','pedagogy'),('review','audience')])
def test_active_input_includes_full_exercise_rule(kind,channel):
    g=compile_guidance(ROOT,kind,channel=channel)
    assert any(s.endswith('exercise-self-containment.md') for s in g['sources'])
    for text in ('全部子问','答案页','教师口头','一页','换成','A=LU','不新增审核角色'):
        assert text in g['text']
    from mpres import __version__
    assert g['version']==__version__

@pytest.mark.parametrize('channel',['domain_accuracy','pedagogy','audience','language','layout'])
def test_every_reviewer_receives_invented_example_principles(channel):
    text=compile_guidance(ROOT,'review',channel=channel)['text']
    for value in ('可以编拟或简化','不要求完全真实','单位','不要求查新闻','假设……','教学假设','无上下文根据'):
        assert value in text


def test_student_segments_cannot_use_adjacent_pages_for_question_data():
    text=audience_guidance(ROOT,'student')['text']
    assert '不得用邻页、答案或备注补题设' in text


def test_new_task_template_uses_same_principles():
    text=(ROOT/'templates/compact/TASK.template.md').read_text()
    assert '题设不可跨页' in text
    assert '检索新闻或提供/核验出处' in text
    assert '不因无来源阻塞' in text
