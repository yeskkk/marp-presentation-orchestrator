"""No-provider preflight of explicit local dependencies, before paid briefing."""
from __future__ import annotations
import json
import re
from .input_packet import safe_file, REFERENCE_SUFFIXES
from mpres.util import MPresError


def require_job_inputs(service, job):
    with service.store.transaction() as conn:
        cfg=service.confirmed(conn)
    task_text=cfg['task_text']
    refs=list(re.findall(r'`(sources/[^`\n]+\.txt)`',task_text))
    if job.get('plan_item_id'):
        rows=service.store.rows('SELECT sources_json FROM plan_items WHERE id=?',(job['plan_item_id'],))
    else:
        rows=service.store.rows('SELECT sources_json FROM plan_items WHERE presentation=? AND config_id=?',(job['presentation'],job['config_id']))
    refs.extend(name for row in rows for name in json.loads(row['sources_json']))
    resources=[]
    for name in dict.fromkeys(refs):
        path=safe_file(service.task,name)
        if path.suffix.lower() not in REFERENCE_SUFFIXES:raise MPresError('Preflight: reference must be extracted text/data: '+name)
        resources.append({'path':name,'bytes':path.stat().st_size,'read':True,'modify':False,'execute':False})
    if job.get('input_artifact_id'):
        artifact=service.store.rows('SELECT path,entrypoint FROM artifacts WHERE id=?',(job['input_artifact_id'],))
        if not artifact:raise MPresError('Preflight: frozen source is missing')
        root=service.task/artifact[0]['path'];safe_file(service.task,root/(artifact[0]['entrypoint'] or 'presentation.md'))
        from mpres.geometry import mathematical_model
        for spec in root.rglob('*.plot.json'):
            safe_file(service.task,spec)
            if spec.stat().st_size>32768:raise MPresError('Preflight: figure specification too large')
            mathematical_model(json.loads(spec.read_text()))
    return {'environment':environment_manifest(),'version':1,'state':'ready','model_calls':0,'required_resources':resources,
            'permission_boundary':{'frozen_inputs':'read only; do not modify or execute in place',
                'output_execution':'An explicit TASK+host authorization still applies to output copies. A read-only input flag neither grants nor revokes execute permission.'},
            'computed_figures':{'kinds':['lines','projection','transform'],
                'transform_labels':['labels.inputs','labels.images'],
                'unsupported':'Implement a bounded generator change before author work; do not invent unsupported parameters.'},
            'reading_status':'availability_checked_not_read_by_model'}


def environment_manifest() -> dict:
    """Report this actual interpreter and available modules; never install them."""
    import importlib.util
    import platform
    import sys
    from pathlib import Path
    root=Path(__file__).resolve().parents[3]
    return {'version':1,'python_executable':sys.executable,'python_version':platform.python_version(),
        'project_cli_argv':[sys.executable,str(root/'scripts'/'mpres_cli.py')],
        'available_modules':{name:importlib.util.find_spec(name) is not None for name in ('numpy','sympy','matplotlib','markdown_it')},
        'invocation':'Use argv exactly (shell quote each argument when a shell is required); do not guess python/python3 or repeatedly probe missing modules.',
        'permission':'Availability is not execute/network/install authorization. Use the existing TASK and host permissions; do not install missing modules silently.'}
