from pathlib import Path
import shutil
import json
import tomllib

import pytest

from mpres.control.guidance import (compile_guidance, REVIEW_GUIDES, read_fragment,
    skill_root, audience_guidance, audience_synthesis_guidance)
from mpres.control.semantic import guidance
from mpres.control.runner import Runner
from mpres.util import MPresError
from test_relational_control import compact_root, prepare, register, completed
from test_deck_workflow import native_double
from test_audience_reading import audience_ready, finish_steps

ROOT=Path(__file__).resolve().parents[2]


@pytest.mark.parametrize('channel',list(REVIEW_GUIDES))
def test_actual_review_packet_gets_whole_assigned_skill_only(compact_root,channel):
    s=prepare(compact_root,count=1);_,done=completed(s);aid=done['artifact_id']
    with s.store.transaction() as c:
        jid=s.ensure_job(c,key='review:'+channel,presentation='p01',kind='review',
                         channel=channel,round=1,artifact=aid)
    register(s,'reviewer','reviewer','low');a=s.bind(jid,'reviewer')
    packet=Runner(s.task).packet(s.job(jid),a['id'])
    role=REVIEW_GUIDES[channel]
    assert read_fragment(skill_root(ROOT),role+'/SKILL.md') in packet['semantic_guidance']
    assert [p for p in packet['semantic_guidance_sources'] if p.endswith('/SKILL.md')]==[
        '.agents/skills/'+role+'/SKILL.md']
    assert s.job(jid)['family']=='reviewer'
    assert packet['task_context']['action']=='read_full'
    assert packet['reading_order'][0]=='task_context'


@pytest.mark.parametrize('channel',[None,'','unknown'])
def test_review_without_precise_channel_does_not_guess(channel):
    with pytest.raises(MPresError,match='assigned channel'):
        compile_guidance(ROOT,'review',channel=channel)


def test_old_general_helper_requires_explicit_review_channel():
    with pytest.raises(MPresError):guidance(ROOT,'review')
    assert guidance(ROOT,'review',channel='domain_accuracy')==compile_guidance(ROOT,'review',channel='domain_accuracy')['text']


def test_missing_independent_skill_does_not_fall_back_to_other_reviewers(tmp_path):
    shutil.copytree(ROOT/'.agents/skills',tmp_path/'.agents/skills')
    (tmp_path/'.agents/skills/language-review/SKILL.md').unlink()
    with pytest.raises(MPresError,match='Missing'):
        compile_guidance(tmp_path,'review',channel='language')


def test_maintenance_materials_are_not_read_by_guide_compiler(tmp_path,monkeypatch):
    shutil.copytree(ROOT/'.agents/skills',tmp_path/'.agents/skills')
    for rel in ('tests/fixtures/semantic/SECRET.md','docs/development/SECRET.md'):
        p=tmp_path/rel;p.parent.mkdir(parents=True,exist_ok=True);p.write_text('MAINTENANCE_ONLY_SENTINEL')
    original=Path.read_text
    def guarded(path,*a,**k):
        if 'SECRET.md'==path.name:raise AssertionError('Runtime opened maintenance data')
        return original(path,*a,**k)
    monkeypatch.setattr(Path,'read_text',guarded)
    bundles=[compile_guidance(tmp_path,k) for k in ('write','edit','revise','diagnose')]
    bundles += [compile_guidance(tmp_path,'review',channel=c) for c in REVIEW_GUIDES]
    bundles += [audience_guidance(tmp_path,'student',introduce=True),
                audience_guidance(tmp_path,'production_language'),audience_synthesis_guidance(tmp_path)]
    assert all('MAINTENANCE_ONLY_SENTINEL' not in b['text'] for b in bundles)
    assert not (tmp_path/'.agents/skills/specialist-review').exists()


def test_audience_gets_full_profession_once_then_narrow_steps(compact_root,native_double):
    s,runner,host,req=audience_ready(compact_root,pages=25)
    requests,last=finish_steps(runner,host,req)
    sources=[r['packet']['semantic_guidance_sources'] for r in requests]
    full='.agents/skills/audience-review/SKILL.md'
    assert full in sources[0] and all(full not in x for x in sources[1:])
    assert full not in last['packet']['semantic_guidance_sources']
    assert last['packet']['semantic_guidance_mode']=='review:audience:synthesis'
    assert len({r['session_id'] for r in requests} | {last['session_id']})==1
    assert sum(r['packet']['task_context']['action']=='read_full' for r in requests)==1
    assert all(r['packet']['task_context']['action']=='reuse' for r in requests[1:])


def test_agent_files_and_runtime_family_stay_unsplit():
    paths={p.stem:p for p in (ROOT/'.codex/agents').glob('*.toml')}
    assert set(paths)=={'lesson-author','deck-revision-author','delegated-planner',
                        'diagnostic-reviewer','resource-designer','specialist-reviewer'}
    document=tomllib.loads(paths['specialist-reviewer'].read_text())
    assert document['name']=='specialist-reviewer'
    assert all(name in document['developer_instructions'] for name in REVIEW_GUIDES.values())
    assert 'model' not in document and 'model_reasoning_effort' not in document


def test_mid_review_upgrade_introduces_method_without_repeating_task(compact_root,native_double):
    s,runner,host,req=audience_ready(compact_root,pages=25)
    # Complete an old-runtime segment, keeping the actual result and TASK receipt.
    runner.accept(req,host(req))
    with s.store.transaction() as c:
        for row in c.execute("SELECT id,detail_json FROM events WHERE kind='audience.step_requested'").fetchall():
            data=json.loads(row['detail_json']);data.pop('role_introduction',None);data.pop('semantic_guidance_version',None)
            c.execute('UPDATE events SET detail_json=? WHERE id=?',(json.dumps(data),row['id']))
    a=s.attempt(req['attempt_id'])
    next_req=runner.execution_request(s.job(a['job_id']),a)
    assert next_req['sequence']>0
    assert '.agents/skills/audience-review/SKILL.md' in next_req['packet']['semantic_guidance_sources']
    assert next_req['packet']['task_context']['action']=='reuse'
    runner.accept(next_req,host(next_req))
    following=runner.execution_request(s.job(a['job_id']),s.attempt(a['id']))
    assert '.agents/skills/audience-review/SKILL.md' not in following['packet']['semantic_guidance_sources']


def test_completed_old_steps_get_full_role_at_synthesis_without_rerun(compact_root,native_double):
    s,runner,host,req=audience_ready(compact_root,pages=2)
    # Complete the two old steps but do not dispatch final synthesis yet.
    runner.accept(req,host(req));a=s.attempt(req['attempt_id'])
    second=runner.execution_request(s.job(a['job_id']),a);runner.accept(second,host(second))
    with s.store.transaction() as c:
        for row in c.execute("SELECT id,detail_json FROM events WHERE kind='audience.step_requested'").fetchall():
            data=json.loads(row['detail_json']);data.pop('role_introduction',None);data.pop('semantic_guidance_version',None)
            c.execute('UPDATE events SET detail_json=? WHERE id=?',(json.dumps(data),row['id']))
    final=runner.execution_request(s.job(a['job_id']),s.attempt(a['id']))
    assert final['operation']=='run'
    assert '.agents/skills/audience-review/SKILL.md' in final['packet']['semantic_guidance_sources']
    assert final['packet']['task_context']['action']=='reuse'
    assert len(s.store.rows("SELECT * FROM audience_steps WHERE attempt_id=? AND state='completed'",(a['id'],)))==2
