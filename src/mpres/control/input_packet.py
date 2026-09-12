"""Required text and safe on-demand resources; availability is not read evidence.

No content is silently truncated. A host reads input_files in full, then fetches
relevant resources using permitted tools. Subsequent reads enter actual usage.
"""
from __future__ import annotations
import os
import stat
import tempfile
from pathlib import Path
from mpres.util import MPresError
from .files import inside
from .store import encode

REFERENCE_SUFFIXES={'.md','.txt','.json','.csv'}


def safe_file(task: Path,path: str|Path) -> Path:
    path=Path(path)
    if not path.is_absolute():path=task/path
    try:relative=path.relative_to(task.resolve()).as_posix()
    except ValueError as exc:raise MPresError('Input file is outside this task') from exc
    value=inside(task,relative)
    if not value.is_file() or not stat.S_ISREG(value.stat().st_mode):
        raise MPresError(f'Input must be an existing regular file: {relative}')
    return value


def snapshot_reference(task: Path,relative: str,directory: Path,index: int) -> Path:
    source=inside(task,relative)
    if source.suffix.lower() not in REFERENCE_SUFFIXES:
        raise MPresError('Approved references must be extracted text/data, not PDF or executable files')
    safe_file(task,source);directory.mkdir(parents=True,exist_ok=True)
    target=directory/f'{index:03d}-{source.name}';data=source.read_bytes()
    if target.exists():
        if safe_file(task,target).read_bytes()!=data:
            raise MPresError('Approved input snapshot changed; do not mutate an execution packet')
        return target
    fd,temporary=tempfile.mkstemp(prefix='.reference-',dir=directory);pending=Path(temporary)
    try:
        with os.fdopen(fd,'wb') as f:f.write(data);f.flush();os.fsync(f.fileno())
        pending.chmod(0o444)
        try:os.link(pending,target)
        except FileExistsError:
            if safe_file(task,target).read_bytes()!=data:raise MPresError('Conflicting concurrent reference snapshot')
    finally:pending.unlink(missing_ok=True)
    return target


def compile_inputs(task: Path,packet: dict,*,references: list[str]|None=None) -> dict:
    refs={str(safe_file(task,p)) for p in references or []}
    unique=dict.fromkeys(str(safe_file(task,p)) for p in packet.get('input_files',[]))
    required=[];resources=[]
    for name in unique:
        path=Path(name);suffix=path.suffix.lower()
        if name in refs:kind='approved_reference'
        elif suffix=='.pdf':kind='published_pdf'
        elif suffix in {'.svg','.png','.jpg','.jpeg','.webp','.gif'}:kind='teaching_image'
        elif suffix=='.css':kind='fixed_theme'
        elif suffix=='.py':kind='reproduction_source'
        elif suffix in {'.md','.txt','.json','.csv','.yaml','.yml'}:
            required.append(name);continue
        else:kind='binary_resource'
        resources.append({'path':name,'kind':kind,'bytes':path.stat().st_size,'read_policy':'on_demand',
                          'read_when':'Inspect when relevant to this judgment; listing is not proof of inspection.'})
    packet['input_files']=required;packet['resource_manifest']=resources
    packet['input_policy']={
        'version':1,
        'input_files':'Read every listed text file in full. Never summarize/truncate before the worker reads it.',
        'resource_manifest':'Available via permitted tools. Do not auto-inline SVG/PDF/CSS/scripts/references. Read relevant resources and report unavailable evidence.',
        'reproduction_source':'Read as source only; this manifest does not grant execution permission.',
        'coverage':'A resource listing is not a reading receipt. All subsequent reads enter actual usage.'}
    packet['attachment_bytes']=sum(x['bytes'] for x in resources)
    packet['required_text_bytes']=sum(Path(p).stat().st_size for p in required)
    return packet


def check_budget(packet: dict,budget: int) -> None:
    count=len(encode(packet).encode('utf-8'))+packet['required_text_bytes']
    if count>budget:
        raise MPresError(f'Context packet is {count} bytes, over confirmed budget {budget}; full required text is never truncated')
    packet['context_bytes']=count
