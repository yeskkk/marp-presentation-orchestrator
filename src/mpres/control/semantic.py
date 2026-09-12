"""Four semantic result schemas; six guides, with no workflow instructions to AI."""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from jsonschema import Draft202012Validator

from mpres.util import MPresError, SubmissionRejected

SCHEMAS = {'plan','author-result','review-result','diagnosis-result'}
GUIDES = {'write':'marp-writing','edit':'deck-editing','revise':'deck-editing',
          'review':'specialist-review','diagnose':'problem-diagnosis'}


@lru_cache(maxsize=4)
def schema(name: str) -> dict:
    if name not in SCHEMAS:
        raise MPresError('Unknown semantic schema')
    value=json.loads(Path(__file__).with_name('schemas').joinpath(name+'.json').read_text())
    Draft202012Validator.check_schema(value)
    return value


def validate(name: str, value) -> None:
    errors=sorted(Draft202012Validator(schema(name)).iter_errors(value),key=lambda e:str(list(e.path)))
    if errors:
        first=errors[0]
        where='/'.join(str(x) for x in first.path) or '<result>'
        raise SubmissionRejected(f'Semantic schema {name} at {where}: {first.message}')


def result_schema_name(kind: str) -> str:
    if kind in {'write','edit','revise'}:return 'author-result'
    if kind=='review':return 'review-result'
    if kind=='diagnose':return 'diagnosis-result'
    raise MPresError('Mechanical jobs do not request AI result schemas')


def guidance(root: Path, kind: str) -> str:
    if kind not in GUIDES:
        raise MPresError('No semantic guide for a mechanical job')
    relative=Path('.agents/skills')/GUIDES[kind]/'SKILL.md'
    path=root/relative
    if not path.is_file():
        path=Path(__file__).resolve().parents[3]/relative
    if not path.is_file():
        raise MPresError('Install the source checkout with its semantic skills; no implicit old-skill fallback')
    # Skill metadata helps discovery, not model execution. The role body is small.
    text=path.read_text(encoding='utf-8')
    return text.split('---',2)[-1].strip() if text.startswith('---') else text


def gate_excerpt(report: dict) -> dict:
    """Pass errors/warnings, not a second copy of every slide and PDF span."""
    return {
        'gate_id': report.get('gate_id'), 'artifact_id': report.get('artifact_id'),
        'success': report.get('success'), 'failure_kind': report.get('failure_kind'),
        'errors': report.get('errors', []),
        'checks': {name: {key: detail[key] for key in ('success','errors','warnings','slide_count','page_count') if key in detail}
                   for name, detail in report.get('checks', {}).items()},
    }


# Semantic questions, not a keyword deletion policy or a layout override.
STUDENT_VALUE_RUBRIC = {
    'test': '学习损失删除反事实：删去这句话后，学生对当前问题、数学关系或必要模型条件会具体失去什么？没有损失就删除，制作信息移到结果 JSON。',
    'not_sufficient': ['不是自夸', '属于教学内容', '可以避免误解', '有利于学习', '符合要求'],
    'attention_costs': [
        '先修清单、核心/扩展和授课时长是备课信息，不直接复制到投影片。需要旧知识就给实际回顾问题。',
        '开场说学生要解决什么，不把一个引例说成整门概念的唯一用途，不把规划动作“定义/论证”当学习动机。',
        '现实资料必须参与变量、单位、建模、计算或解释，不用年份/新闻页单独证明“够新”。',
        '来源的 TXT 行号留在内部；必要事实/图片出处简短可访问，孤立引文不能代替具体解释。',
        '误区应由当前任务或真实易错点支撑，不能凭空制造“不是地理位置”等免责声明。',
        '结论说出数学关系或可执行判断，不用“分别论证/保证一般维数”等方法口号充数。',
    ],
    'protect': '保留规范术语、数学含义、必要条件和真实数据出处；精确不等于证明密集。不做“定义→知道”等机械替词。',
    'proof_rule': '按已确认的证明深度处理；最低要求是数学准确，不是保留每段正确证明。任务书与后来用户意见冲突时明确指出，不能自行声称它们一致。',
    'output_boundary': '学生页只有教学内容；检查声明、资料缺口、反馈处置、教师备课信息只进入结果 JSON/数据库。',
}


def teaching_context(settings: dict) -> dict:
    value = settings.get('teaching')
    return {
        'status': 'explicit' if value else 'from_confirmed_task_and_feedback',
        'audience': value.get('audience') if value else None,
        'proof_depth': value.get('proof_depth') if value else None,
        'proof_depth_meanings': {
            'minimal': '以理解、计算、图形与例子为主；只给必要理由，不安排形式证明训练。',
            'explanatory': '允许必要的短推导，解释它解决的具体问题；不为完整性保留全部证明。',
            'rigorous': '用户要求证明训练；仍须说明动机，避免无学习作用的制作自述。',
        },
        'rubric': STUDENT_VALUE_RUBRIC,
        'scope': 'Confirmed teaching settings and explicit later feedback; never change runtime or silently rewrite old config.',
    }


def teaching_conflicts(settings: dict, task_text: str) -> list[dict]:
    """Bounded planning hints, not a semantic verdict or a new blocking gate."""
    import re
    if settings.get('teaching', {}).get('proof_depth') != 'minimal':
        return []
    texts = [('TASK.md', task_text)] + [
        (f"{deck['id']}/{unit['id']}", unit['brief'])
        for deck in settings['presentations'] for unit in deck['units']]
    pattern = re.compile(r'保留(?:所有|全部|正确|完整)?证明|严格证明|两包含证明|证明训练|preserve all proofs', re.I)
    hints=[]
    for location, text in texts:
        for line in text.splitlines():
            if pattern.search(line) and not re.search(r'不(?:要|必|需)|避免|禁止|无需|do not|avoid',line,re.I):
                hints.append({'location':location,'quote':line[:600],
                              'question':'proof_depth=minimal 与此处证明要求可能冲突；规划时向用户澄清，不推定规范术语等于保留证明。'})
    return hints
