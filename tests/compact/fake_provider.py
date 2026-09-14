"""Deterministic JSON-stdio test adapter. This is NOT a real model provider."""
import json
import sqlite3
import sys
from pathlib import Path

request=json.load(sys.stdin)
database=Path(sys.argv[1])
conn=sqlite3.connect(database,timeout=20)
conn.execute('CREATE TABLE IF NOT EXISTS handles(id TEXT PRIMARY KEY, model TEXT, effort TEXT)')
op=request['operation']
if op=='capabilities':
    response={'handle_limit':16,'handles':['main',*[row[0] for row in conn.execute('SELECT id FROM handles')]],
              'supports_close':False,'supports_reset':False,'usage_reporting':True,'receipt':'fixture-inventory'}
elif op=='create':
    handle='fixture-'+request['request_id'];spec=request['runtime']
    conn.execute('INSERT OR IGNORE INTO handles VALUES(?,?,?)',(handle,spec['model'],spec['reasoning_effort']));conn.commit()
    response={'handle':handle,'model':spec['model'],'reasoning_effort':spec['reasoning_effort'],'receipt':'created:'+handle}
elif op=='run':
    packet=request['packet'];out=Path(packet['writable_directory'])
    out.mkdir(parents=True,exist_ok=True)
    (out/'presentation.md').write_text('---\nmarp: true\n---\n<!-- slide-id: '+packet['presentation']+'-'+packet.get('unit',{}).get('id','deck')+'-s1 -->\n# Deterministic test content\n')
    if packet.get('exercise_contract'):
        (out/'exercises.json').write_text(json.dumps({'version':1,'exercises':[]}))
    response={'runtime':request['runtime'],'receipt':'executed:'+request['attempt_id'],'source_dir':'output','result':{'summary':'Deterministic fixture content, not an AI result'},
              'usage':[{'call_id':'fixture-call','counters':{'input_tokens':100,'cached_input_tokens':80,'output_tokens':5,'reasoning_tokens':0,'total_tokens':105}}]}
else:raise ValueError(op)
conn.close();print(json.dumps(response))
