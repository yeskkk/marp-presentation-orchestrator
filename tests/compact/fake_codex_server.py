"""JSON-RPC subprocess fixture, never a selectable production model."""
import json
import sys
import threading
import time
from test_deck_workflow import Host

host=Host(findings=True)
lock=threading.RLock();output=threading.Lock();threads={};sequence=0

def emit(message):
    with output:print(json.dumps(message),flush=True)

def turn(message):
    global sequence
    p=message['params'];h=p['threadId'];text=p['input'][0]['text']
    packet=json.loads(text[text.index('{'):]);op=text.split('exact ',1)[1].split(' request.',1)[0]
    with lock:
        sequence+=1;t='t'+str(sequence);runtime=threads[h]['runtime']
    emit({'method':'turn/started','params':{'threadId':h,'turn':{'id':t,'status':'inProgress'}}})
    emit({'id':message['id'],'result':{'turn':{'id':t,'status':'inProgress'}}})
    time.sleep(.03)
    req={'operation':op,'packet':packet,'request_id':t,'attempt_id':t,'runtime':runtime}
    if op=='brief':
        result={'readback':[{'id':f['id'],'version':f['version'],'approach':'Use page-specific evidence and the stated teaching scope.'} for f in packet['historical_feedback']]}
    else:
        with lock:result=host(req)['result']
    with lock:
        threads[h]['used']+=105;used=threads[h]['used']
    emit({'method':'thread/tokenUsage/updated','params':{'threadId':h,'turnId':t,'tokenUsage':{'total':{'inputTokens':used//105*100,'cachedInputTokens':used//105*80,'outputTokens':used//105*5,'reasoningOutputTokens':0,'totalTokens':used}}}})
    emit({'method':'item/completed','params':{'threadId':h,'turnId':t,'item':{'type':'agentMessage','phase':'final_answer','text':json.dumps(result)}}})
    emit({'method':'turn/completed','params':{'threadId':h,'turn':{'id':t,'status':'completed'}}})

for line in sys.stdin:
    m=json.loads(line);method=m.get('method');p=m.get('params',{})
    if method=='initialized':continue
    if method=='turn/start':threading.Thread(target=turn,args=(m,)).start();continue
    if method=='initialize':result={'fixture':'not-a-real-model'}
    elif method=='thread/loaded/list':result={'data':list(threads)}
    elif method=='thread/start':
        with lock:
            h='h'+str(len(threads)+1);runtime={'model':p['model'],'reasoning_effort':p['config']['model_reasoning_effort']}
            threads[h]={'runtime':runtime,'used':0}
        result={'thread':{'id':h},'model':runtime['model'],'reasoningEffort':runtime['reasoning_effort']}
    elif method in {'thread/resume','thread/read'}:
        h=p['threadId'];r=threads[h]['runtime'];result={'thread':{'id':h},'model':r['model'],'reasoningEffort':r['reasoning_effort']}
    else:emit({'id':m['id'],'error':{'code':-32601,'message':'fixture unsupported'}});continue
    emit({'id':m['id'],'result':result})
