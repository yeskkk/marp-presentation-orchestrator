"""Only for deterministic source fixtures with no learner exercises."""
import json

def empty_manifest(source):
    path=source/'exercises.json'
    if not path.exists():path.write_text(json.dumps({'version':1,'exercises':[]})+'\n')
