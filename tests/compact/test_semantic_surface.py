from pathlib import Path
import json
import os
import subprocess
import tomllib

import pytest

from mpres.control.semantic import guidance, gate_excerpt, schema, validate
from mpres.util import MPresError
from test_relational_control import compact_root, prepare, completed
from test_job_runner import ready, attach_requests

ROOT=Path(__file__).resolve().parents[2]


def test_only_six_semantic_skills_and_no_resident_coordinator():
    dirs={p.parent.name for p in (ROOT/'.agents/skills').glob('*/SKILL.md')}
    assert dirs=={'course-planning','marp-writing','deck-editing','specialist-review','problem-diagnosis','resource-design'}
    assert not (ROOT/'.codex/agents/author-coordinator.toml').exists()
    assert not (ROOT/'.codex/agents/review-coordinator.toml').exists()
    assert not (ROOT/'.codex/agents/release-coordinator.toml').exists()
    for file in (ROOT/'.codex/agents').glob('*.toml'):
        profile=tomllib.loads(file.read_text())
        assert 'model' not in profile and 'model_reasoning_effort' not in profile
        assert 'STAGE-ARTIFACT' not in profile.get('developer_instructions','')


def test_four_schemas_are_real_validation_not_unused_files():
    for name in ['plan','author-result','review-result','diagnosis-result']:
        assert schema(name)['additionalProperties'] is False
    validate('author-result',{'summary':'Explained coordinates.'})
    with pytest.raises(MPresError):validate('author-result',{'summary':'Done','gate_passed':True})
    with pytest.raises(MPresError):validate('review-result',{'summary':'Checked','findings':[{'message':'Unclear','slide_ids':['s1']}]})
    with pytest.raises(MPresError):validate('diagnosis-result',{'summary':'Guessed'})


def test_job_packet_gets_one_guide_and_result_schema(compact_root):
    service,runner=ready(compact_root,count=1)
    attach_requests(runner,runner.tick())
    packet=runner.tick()['requests'][0]['packet']
    assert '本课 brief' in packet['semantic_guidance']
    assert packet['result_schema']['required']==['summary']
    assert 'course-planning/SKILL.md' not in json.dumps(packet)
    assert 'ASSIGNMENT-DECISION' not in json.dumps(packet)


def test_gate_excerpt_does_not_duplicate_slide_text():
    full={'success':True,'gate_id':'g1','artifact_id':'r1','checks':{
        'source':{'success':True,'errors':[],'warnings':[],'slides':[{'visible_text':'entire duplicated deck'}]},
        'pdf':{'success':True,'errors':[],'page_count':3,'pages':[{'spans':['many copies of source text']}]}}}
    small=gate_excerpt(full)
    assert 'duplicated' not in json.dumps(small)
    assert small['checks']['pdf']['page_count']==3


def test_invalid_semantic_fields_never_replace_accepted_result(compact_root):
    service=prepare(compact_root);attempt,_=completed(service)
    with pytest.raises(MPresError,match='schema'):
        service.submit(attempt['id'],{'summary':'A worked example','gate_passed':True})
    assert 'gate_passed' not in service.attempt(attempt['id'])['result_json']


def test_explicit_cli_launchers_preserve_arguments_without_model():
    import sys
    for name in ['start.sh','start-safe.sh','start.ps1','start-safe.ps1']:
        text=(ROOT/name).read_text()
        assert '--dangerously' not in text and 'log_daemon' not in text
        assert 'PROMPT=' not in text and '$Prompt' not in text
    result=subprocess.run(['bash',str(ROOT/'start.sh'),'--cli','workflow','--help'],env={**os.environ,'PYTHON_BIN':sys.executable,'PYTHONPATH':str(ROOT/'src')},capture_output=True,text=True)
    assert result.returncode==0 and 'retry-publish' in result.stdout


def test_doctor_command_is_present_and_bootstrap_uses_it():
    from mpres.control.cli import build_parser
    parsed=build_parser().parse_args(['toolchain','doctor','--timeout','10'])
    assert parsed.timeout==10
    assert '"mpres", "toolchain", "doctor"' in (ROOT/'scripts/bootstrap.py').read_text()


def test_optional_resource_role_uses_fixed_author_family(compact_root):
    from mpres.runtime_profile import resolve_runtime
    from mpres.util import read_yaml
    service=prepare(compact_root)
    profile=read_yaml(service.task/'TASK-RUNTIME-PROFILE.yaml')
    runtime=resolve_runtime(profile,'resource-designer')
    assert runtime['runtime_family']=='author'
    assert runtime['reasoning_effort']=='medium'
    assert runtime['model']=='gpt-5.6-sol'
