from pathlib import Path
import copy
import json
import shutil

import pytest
import yaml
from jsonschema import Draft202012Validator

from mpres.control.guidance import compile_guidance, audience_guidance, read_fragment, skill_root
from mpres.control.semantic import schema, validate
from mpres.control.audience import validate_attention
from mpres.control.runner import Runner
from mpres.marp_source import parse_deck
from mpres.source_policy import inspect_source
from mpres.util import MPresError
from test_relational_control import compact_root, prepare, register
from test_deck_workflow import native_double
from test_audience_reading import audience_ready, finish_steps

ROOT=Path(__file__).resolve().parents[2]
EXAMPLES=ROOT/'tests/fixtures/semantic'


@pytest.mark.parametrize('kind,repair,correction,mode,sections',[
    ('write',False,False,'write',[]),
    ('write',False,True,'write-correction',['correction']),
    ('edit',False,False,'integration',['integration']),
    ('edit',False,True,'correction',['correction']),
    ('edit',True,False,'integration',['integration','repair']),
    ('edit',True,True,'correction',['correction','repair']),
    ('revise',False,False,'revision',['revision']),
    ('revise',True,False,'revision',['revision','repair']),
    ('revise',True,True,'revision',['revision','correction','repair']),
    ('diagnose',False,False,'diagnose:bounded',['bounded']),
    ('diagnose',True,False,'diagnose:expansion',['expansion']),
])
def test_mutually_distinct_role_modes(kind,repair,correction,mode,sections):
    g=compile_guidance(ROOT,kind,repair=repair,correction=correction)
    assert g['mode']==mode
    assert [p.split('#')[1] for p in g['sources'] if '#' in p]==sections
    assert g['text'].count('# 共同教学边界')==1
    assert len(g['sources'])==len(set(g['sources']))
    assert g['bytes']==len(g['text'].encode())
    assert 'compat/legacy' not in g['text']


@pytest.mark.parametrize('channel',['domain_accuracy','pedagogy','audience','language','layout'])
def test_one_channel_only_not_five_concatenated(channel):
    g=compile_guidance(ROOT,'review',channel=channel)
    from mpres.control.guidance import REVIEW_GUIDES
    assert g['sources'][-1].endswith(REVIEW_GUIDES[channel]+'/SKILL.md')
    assert sum(p.endswith('/SKILL.md') for p in g['sources'])==1
    assert 'deck-editing/references' not in str(g['sources'])
    repair=compile_guidance(ROOT,'review',channel=channel,repair=True)
    assert repair['sources'][-1].endswith('_shared/review-scope.md')
    assert 'review-scope.md' in str(repair['sources'])


@pytest.mark.parametrize('phase',['student','production_language'])
def test_audience_has_only_the_current_small_step(phase):
    g=audience_guidance(ROOT,phase)
    assert len(g['sources'])==1
    assert g['sources'][0].endswith('steps.md#'+phase)
    assert 'TASK.md' not in g['sources'][0]


def test_unknown_role_channel_or_phase_fails_closed():
    with pytest.raises(MPresError):compile_guidance(ROOT,'release-coordinator')
    with pytest.raises(MPresError):compile_guidance(ROOT,'review',channel='all-five')
    with pytest.raises(MPresError):audience_guidance(ROOT,'skip-to-final')


def test_partial_project_guides_do_not_silently_mix_installed_version(tmp_path):
    target=tmp_path/'.agents/skills'
    shutil.copytree(ROOT/'.agents/skills',target)
    (target/'deck-editing/references/modes.md').unlink()
    with pytest.raises(MPresError,match='Missing'):
        compile_guidance(tmp_path,'edit')


def test_missing_section_or_duplicate_is_rejected(tmp_path):
    base=tmp_path/'skills';base.mkdir()
    p=base/'modes.md';p.write_text('## integration\nSome work\n')
    with pytest.raises(MPresError):read_fragment(base,'modes.md','repair')
    p.write_text('## integration\nFirst\n## integration\nSecond\n')
    with pytest.raises(MPresError):read_fragment(base,'modes.md','integration')


def test_fragment_cannot_escape_guide_tree(tmp_path):
    base=tmp_path/'skills';base.mkdir();outside=tmp_path/'outside.md';outside.write_text('outside')
    (base/'escape.md').symlink_to(outside)
    for path in ('../outside.md','escape.md'):
        with pytest.raises(MPresError):read_fragment(base,path)


def test_real_writer_packet_uses_selected_guides_and_existing_budget(compact_root):
    service=prepare(compact_root,count=1);register(service)
    job=service.jobs()[0];attempt=service.bind(job['id'],'h1')
    before=service.store.rows('SELECT * FROM configs')
    p=Runner(service.task).packet(job,attempt['id'])
    assert p['semantic_guidance_mode']=='write'
    assert len(p['semantic_guidance_sources'])==5
    assert any(x.endswith('student-facing-expression.md') for x in p['semantic_guidance_sources'])
    assert any(x.endswith('mathematical-expression.md') for x in p['semantic_guidance_sources'])
    assert any(x.endswith('exercise-self-containment.md') for x in p['semantic_guidance_sources'])
    assert '本课 brief' in p['semantic_guidance']
    assert p['context_bytes']>len(p['semantic_guidance'].encode())
    assert service.store.rows('SELECT * FROM configs')==before
    assert not list(service.task.rglob('SKILL.md'))


def test_real_audience_steps_and_final_get_different_guides(compact_root,native_double):
    service,runner,host,req=audience_ready(compact_root,pages=2)
    before=service.store.rows('SELECT * FROM configs')
    requests,last=finish_steps(runner,host,req)
    assert [r['packet']['semantic_guidance_mode'] for r in requests]==[
        'audience:student','audience:production_language']
    assert len(requests[0]['packet']['semantic_guidance_sources'])==4
    assert len(requests[1]['packet']['semantic_guidance_sources'])==1
    assert last['packet']['semantic_guidance_mode']=='review:audience:synthesis'
    assert last['packet']['semantic_guidance_sources'][-1].endswith('#synthesis')
    assert len(service.store.rows("SELECT * FROM jobs WHERE channel='audience'"))==1
    assert service.store.rows('SELECT * FROM configs')==before


@pytest.mark.parametrize('filename,schema_name',[
    ('plan.json','plan'),('author-result.json','author-result'),
    ('revision-result.json','author-result'),('review-result.json','review-result'),
    ('diagnosis-result.json','diagnosis-result'),
])
def test_result_examples_use_actual_schemas(filename,schema_name):
    value=json.loads((EXAMPLES/filename).read_text())
    validate(schema_name,value)
    with pytest.raises(MPresError):validate(schema_name,{**value,'gate_passed':True})


def test_source_and_evidence_examples_are_real_not_invented():
    source=EXAMPLES/'review-fixture'
    report=inspect_source(source)
    assert report['success'],report
    slides={s.slide_id:s.source for s in parse_deck(source/'presentation.md').slides}
    author=json.loads((EXAMPLES/'author-result.json').read_text())
    for check in author['feedback_checks']:
        for ev in check['evidence']:assert ev['quote'] in slides[ev['slide_id']]
    review=json.loads((EXAMPLES/'review-result.json').read_text())
    assert all(set(f['slide_ids'])<=set(slides) for f in review['findings'])
    diagnosis=json.loads((EXAMPLES/'diagnosis-result.json').read_text())
    assert diagnosis['expansion']['related_problems'][0]['evidence_status']=='possible'
    assert diagnosis['expansion']['related_problems'][0]['slide_ids']==[]


def test_attention_examples_and_negative_mutation():
    packet=json.loads((EXAMPLES/'attention-input.json').read_text())
    result=json.loads((EXAMPLES/'audience-attention-result.json').read_text())
    validator=Draft202012Validator(schema('review-result')['$defs']['audience_step'])
    validator.validate(result)
    validate_attention(result,packet['attention_candidates'])
    broken=copy.deepcopy(result);broken['attention_checks'][0]['finding_index']=None
    with pytest.raises(MPresError):validate_attention(broken,packet['attention_candidates'])
    validator.validate(json.loads((EXAMPLES/'audience-student-result.json').read_text()))


def test_calibration_examples_are_not_claims_of_model_execution():
    cases=json.loads((EXAMPLES/'calibration-cases.json').read_text())
    assert len(cases)>=7
    assert all(c['automatic_verdict'] is False and c['expected'] and c['protect'] for c in cases)
    assert {c['id'] for c in cases}>={'necessary-assumption','mispaired-resolution','recent-but-unused'}


def test_every_review_channel_resolves_to_its_own_full_skill():
    from mpres.control.guidance import REVIEW_GUIDES
    assert len(set(REVIEW_GUIDES.values()))==5
    for channel, name in REVIEW_GUIDES.items():
        routed=compile_guidance(ROOT,'review',channel=channel)
        assert '.agents/skills/'+name+'/SKILL.md' in routed['sources']
        assert read_fragment(skill_root(ROOT),name+'/SKILL.md') in routed['text']
