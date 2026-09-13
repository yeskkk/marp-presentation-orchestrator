from pathlib import Path
import importlib.util
import json
import shutil

import pytest
import yaml
from mpres.control.cli import build_parser
from mpres.control.service import Service

ROOT=Path(__file__).resolve().parents[2]


def checker():
    spec=importlib.util.spec_from_file_location('documentation_check',ROOT/'scripts/check_documentation.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module.check


def test_active_documentation_links_and_boundaries():
    report=checker()(ROOT)
    assert report['success'],report
    assert report['semantic_skills']==6
    assert report['active_configuration_templates']==3
    assert report['legacy_templates']>100


def test_no_legacy_templates_in_new_task(tmp_path):
    shutil.copytree(ROOT/'templates',tmp_path/'templates')
    # Compatibility folder deliberately absent: new creation must not need it.
    service=Service.create(tmp_path,'new-course','Real title')
    public={p.name for p in service.task.iterdir() if p.is_file()}
    assert public=={'TASK.md','task.yaml','TASK-RUNTIME-PROFILE.yaml'}
    assert not list(service.task.rglob('ASSIGNMENT-*.yaml'))
    assert not list(service.task.rglob('STAGE-ARTIFACT.md'))
    assert '学习所得' in (service.task/'TASK.md').read_text()


def test_configuration_runtime_defaults_unchanged():
    task=yaml.safe_load((ROOT/'templates/compact/task.template.yaml').read_text())
    assert task['workflow']=='full' and task['delivery']=='all'
    assert task['teaching']['proof_depth']=='minimal'
    assert task['presentations']==[]
    assert task['context_budget_bytes']==262144
    assert task['provider']['handle_limit'] is None
    profile=yaml.safe_load((ROOT/'templates/compact/TASK-RUNTIME-PROFILE.template.yaml').read_text())
    assert profile['defaults']=={
        'planner':{'model':'gpt-5.6-sol','reasoning_effort':'high'},
        'author':{'model':'gpt-5.6-sol','reasoning_effort':'medium'},
        'reviewer':{'model':'gpt-5.6-sol','reasoning_effort':'low'}}
    assert profile['runtime_changes_during_task']=='forbidden'


@pytest.mark.parametrize('arguments',[
    'task init economics --title Course',
    'task present economics',
    'task confirm economics --by user',
    'task materialize economics',
    'runner run economics --cycles 100 --interval 1',
    'repair open economics --presentation p01 --mode review-first --allow-slide-changes --report issue --by user',
    'repair present economics case1',
    'repair confirm economics case1 --version 2 --by user',
    'repair amend economics case1 --proposal proposal.json --by user',
    'workflow materialize economics',
    'task backup-db economics /safe/task.sqlite3',
    'task import-legacy /old/task --slug economics-imported',
    'artifact interrupt-gate economics gate1 --reason stopped',
    'workflow retry-checks economics --presentation p01 --note repaired',
])
def test_documented_commands_are_actual_parser_paths(arguments):
    args=build_parser().parse_args(['--root',str(ROOT),*arguments.split()])
    assert args.command


def test_old_template_consumers_are_explicit():
    for name in ['production','tasks','review','diagnostics','stages','maintenance','control_jobs']:
        source=(ROOT/f'src/mpres/{name}.py').read_text()
        assert '"compat" / "legacy" / "templates"' in source or 'compat/legacy/templates/' in source
    assert 'compat/legacy' not in (ROOT/'src/mpres/control/service.py').read_text()


def test_runtime_templates_do_not_author_student_text():
    text=(ROOT/'templates/compact/TASK.template.md').read_text()
    assert '不是学生页' in text and '生产回执' in text
    assert '不默认保留所有正确证明' in text
