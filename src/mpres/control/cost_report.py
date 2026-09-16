"""Read-only usage and wall-time accounting; unknown is not zero or idle.

Cached inputs are a subset of inputs; reasoning is a subset of outputs. This
report never infers a price, provider turn, reading completion or waiting cause.
"""
from __future__ import annotations
import csv
import io
import json
from collections import defaultdict
from contextlib import closing
from datetime import datetime,timezone
from pathlib import Path
from mpres.util import MPresError
from .maintenance_lock import readonly_connection
from .storage import stamp

FIELDS=('input_tokens','cached_input_tokens','output_tokens','reasoning_tokens','total_tokens')

def wall_now():return datetime.now(timezone.utc).isoformat(timespec='milliseconds').replace('+00:00','Z')

def _rows(c,table):
    if not c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",(table,)).fetchone():return []
    return [dict(r) for r in c.execute('SELECT * FROM '+table)]

def counters(rows):
    result={}
    for name in FIELDS:
        known=[r[name] for r in rows if type(r.get(name)) is int and r[name]>=0]
        result[name]={'total':sum(known) if rows and len(known)==len(rows) else None,'known_sum':sum(known),'known_records':len(known),'unknown_records':len(rows)-len(known)}
    fresh=[r['input_tokens']-r['cached_input_tokens'] for r in rows if type(r.get('input_tokens')) is int and type(r.get('cached_input_tokens')) is int and 0<=r['cached_input_tokens']<=r['input_tokens']]
    result['uncached_input_tokens']={'total':sum(fresh) if rows and len(fresh)==len(rows) else None,'known_sum':sum(fresh),'known_records':len(fresh),'unknown_records':len(rows)-len(fresh)}
    return result

def union(intervals):
    merged=[]
    for start,end in sorted((a,b) for a,b in intervals if a is not None and b is not None and b>=a):
        if merged and start<=merged[-1][1]:merged[-1]=(merged[-1][0],max(end,merged[-1][1]))
        else:merged.append((start,end))
    return merged

def seconds(intervals):return sum(b-a for a,b in union(intervals))

def _interval(event):
    d=event['detail'];start=stamp(d.get('started_at'));end=stamp(d.get('finished_at')) or stamp(event['created_at'])
    duration=d.get('seconds')
    if end and not start and isinstance(duration,(float,int)) and duration>=0:
        return (end.timestamp()-duration,end.timestamp()),'finish_minus_monotonic_seconds'
    if start and end and end>=start:return (start.timestamp(),end.timestamp()),'explicit_endpoints'
    return None,'unavailable'

def report(task: Path, presentations=None, *, case_id=None, batch_id=None, since=None, until=None):
    from .cost_scope import boundary,lineage,grouping
    lower,upper=boundary(since,'since'),boundary(until,'until')
    if lower is not None and upper is not None and lower>=upper:raise MPresError('since must be earlier than until')
    def in_time(value):
        dt=stamp(value) if isinstance(value,str) else None
        v=dt.timestamp() if dt else value if isinstance(value,(int,float)) else None
        return (lower is None and upper is None) or (v is not None and (lower is None or v>=lower) and (upper is None or v<upper))
    with closing(readonly_connection(task/'.mpres/task.sqlite3')) as c:
        c.execute('BEGIN')  # one read snapshot; no migration or writes
        attempts={a['id']:a for a in _rows(c,'attempts')};jobs={j['id']:j for j in _rows(c,'jobs')}
        sessions={s['id']:s for s in _rows(c,'sessions')};artifacts={a['id']:a for a in _rows(c,'artifacts')}
        cases={r['id']:r for r in _rows(c,'repair_cases')};batches={r['id']:r for r in _rows(c,'production_batches')}
        links=_rows(c,'repair_jobs');contexts=_rows(c,'job_cost_context')
        observations=_rows(c,'scheduler_observation')
        usage=_rows(c,'usage');requests={q['request_id']:json.loads(q['request_json']) for q in _rows(c,'host_requests')}
        replies=[(r['request_id'],json.loads(r['response_json'])) for r in _rows(c,'host_responses')]
        events=[{**r,'detail':json.loads(r['detail_json'])} for r in _rows(c,'events')]
        gates=_rows(c,'gate_runs');releases=_rows(c,'releases')+_rows(c,'release_versions')
    # Legacy calls can be attributed from their actual retained envelopes, not
    # inferred from token size or from a thread's newest purpose.
    bridge=task/'.mpres/codex-bridge.sqlite3'
    if bridge.is_file():
        with closing(readonly_connection(bridge)) as c:
            for r in c.execute('SELECT id,request,response FROM requests'):
                q=json.loads(r['request']);existing=requests.get(r['id'])
                if existing is None:requests[r['id']]=q
                elif existing!=q:continue  # conflicting envelopes never guessed
                if r['response']:replies.append((r['id'],json.loads(r['response'])))
    if case_id and case_id not in cases:raise MPresError('Unknown repair case filter: '+case_id)
    if batch_id and batch_id not in batches:raise MPresError('Unknown production batch filter: '+batch_id)
    scopes=lineage(jobs,attempts,artifacts,links,contexts,requests,cases)
    def scope_ok(co):return (not case_id or co.get('repair_case_id')==case_id) and (not batch_id or co.get('batch_id')==batch_id)
    attribution=defaultdict(set)
    for rid,r in replies:
        q=requests.get(rid,{})
        for call in r.get('usage',[]):
            if isinstance(call,dict) and isinstance(call.get('call_id'),str):
                key=f"audience:{q['sequence']}:{call['call_id']}" if q.get('operation')=='audience_step' and type(q.get('sequence')) is int else call['call_id']
                attribution[(q.get('attempt_id'),key)].add(rid)
    turn_index={};index_path=task/'.mpres/codex-index.sqlite3';index_coverage={'present':index_path.is_file(),'stale':None}
    if index_path.is_file():
        with closing(readonly_connection(index_path)) as c:
            for row in _rows(c,'turns'):
                if row.get('request_id'):turn_index[(row['request_id'],row['id'])]=row
            source=_rows(c,'source')
            if source and bridge.is_file():
                with closing(readonly_connection(bridge)) as b:
                    top=b.execute('SELECT COALESCE(MAX(id),0) FROM wire').fetchone()[0]
                index_coverage.update(cursor=source[0]['cursor'],source_highwater=top,stale=source[0]['cursor']!=top)
    selected=set(presentations or [])
    known_presentations={j['presentation'] for j in jobs.values()}
    if selected-known_presentations:raise MPresError('Unknown presentation filter: '+', '.join(sorted(selected-known_presentations)))
    def coordinates(aid):
        a=attempts.get(aid,{});j=jobs.get(a.get('job_id'),{});s=sessions.get(a.get('session_id'),{})
        return {'presentation':j.get('presentation'),'kind':j.get('kind'),'channel':j.get('channel'),'job_id':j.get('id'),
                'attempt_sequence':a.get('sequence'),'attempt_state':a.get('state'),'model':s.get('model'),'effort':s.get('effort'),**scopes.get(j.get('id'),{'repair_case_id':None,'batch_id':None,'scope_attribution':'historical_unassigned'})}
    calls=[];selected_attempts=set();model_intervals=[]
    for row in usage:
        co=coordinates(row['attempt_id'])
        if selected and co['presentation'] not in selected:continue
        if not scope_ok(co):continue
        ids=attribution[(row['attempt_id'],row['call_id'])]
        rid=next(iter(ids)) if len(ids)==1 else None;q=requests.get(rid,{})
        provider_turn=row['call_id'].split(':',2)[2] if q.get('operation')=='audience_step' and row['call_id'].startswith('audience:') else row['call_id']
        t=turn_index.get((rid,provider_turn),{});a=t.get('started_ms');b=t.get('completed_ms')
        interval=(a/1000,b/1000) if type(a) is int and type(b) is int and b>=a and not t.get('runtime_error') else None
        selected_at=a/1000 if type(a) is int else row.get('created_at')
        if not in_time(selected_at):continue
        selected_attempts.add(row['attempt_id'])
        if interval:model_intervals.append(interval)
        calls.append({**row,**co,'selected_at':selected_at,'time_selection_basis':'provider_turn_start' if type(a) is int else 'usage_recorded_at','provider_turn_id':provider_turn,'provider_seconds':(b-a)/1000 if interval else None,'provider_interval':interval,'request_id':rid,'operation':q.get('operation'),'attribution':'exact_retained_envelope' if rid else 'unknown_or_ambiguous',
            'packet_context_bytes':q.get('packet',{}).get('context_bytes'),'task_context_action':q.get('packet',{}).get('task_context',{}).get('action')})
    phases=defaultdict(list)
    for r in calls:phases[(r['presentation'],r['kind'],r['channel'],r['operation'])].append(r)
    grouped=[{'presentation':k[0],'kind':k[1],'channel':k[2],'operation':k[3],'calls':len(v),'counters':counters(v)} for k,v in sorted(phases.items(),key=lambda x:str(x[0]))]
    selected_requests={r['request_id'] for r in calls if r['request_id']}
    durations=[];provider_intervals=[];gate_intervals=[];wait_intervals=[];waits=[]
    scoped=bool(case_id or batch_id or since or until)
    for e in events:
        if e['kind']!='provider.duration':continue
        d=e['detail'];q=requests.get(d.get('request_id'),{});co=coordinates(q.get('attempt_id'))
        if selected and co['presentation'] not in selected:continue
        if scoped and d.get('request_id') not in selected_requests:continue
        interval,method=_interval(e)
        if interval:provider_intervals.append(interval)
        durations.append({**co,'event_id':e['id'],'request_id':d.get('request_id'),'operation':q.get('operation'),'seconds':d.get('seconds'),
            'invocation_kind':d.get('invocation_kind','historical_unspecified'),'interval_method':method,'interval':interval})
    gate_rows=[]
    for g in gates:
        presentation=artifacts.get(g['artifact_id'],{}).get('presentation')
        if selected and presentation not in selected:continue
        co=coordinates(artifacts.get(g['artifact_id'],{}).get('attempt_id'))
        if not scope_ok(co) or not in_time(g['started_at']):continue
        a,b=stamp(g['started_at']),stamp(g.get('finished_at'));detail=json.loads(g['detail_json'] or '{}')
        if a and b and b>=a:gate_intervals.append((a.timestamp(),b.timestamp()))
        gate_rows.append({'id':g['id'],'presentation':presentation,'state':g['state'],'seconds':detail.get('seconds'),'start':g['started_at'],'end':g.get('finished_at')})
    # A global/multi-deck wait is not charged separately to each selected deck.
    # Include it only for the whole scope or an unambiguous matching target set.
    def wait_scope_ok(detail):
        if not scope_ok(detail):return False
        if not selected:return True
        targets=set(detail.get('presentations') or ([detail['presentation']] if detail.get('presentation') else []))
        return bool(targets) and targets<=selected
    def wait_range(a,b):
        if a is None:return None
        left=a.timestamp()
        right=b.timestamp() if b is not None else None
        if right is not None and right<left:return None
        if upper is not None and left>=upper:return None
        if lower is not None and right is not None and right<=lower:return None
        clipped_left=max(left,lower) if lower is not None else left
        clipped_right=min(right,upper) if right is not None and upper is not None else right
        return (clipped_left,clipped_right)
    ends={e['detail']['wait_id']:e for e in events if e['kind']=='main.wait_ended'}
    for e in events:
        if e['kind']!='main.wait_started':continue
        d=e['detail']
        if not wait_scope_ok(d):continue
        finish=ends.get(d['wait_id']);a=stamp(e['created_at']);b=stamp(finish['created_at']) if finish else None
        interval=wait_range(a,b)
        if interval is None:continue
        left,right=interval
        if right is not None:wait_intervals.append((left,right))
        waits.append({'wait_id':d['wait_id'],'reason':d['reason'],'presentation':d.get('presentation'),
            'repair_case_id':d.get('repair_case_id'),'batch_id':d.get('batch_id'),
            'seconds':right-left if right is not None else None,'open':finish is None,
            'started_at':e['created_at'],'finished_at':finish['created_at'] if finish else None})
    automatic_waits=[];automatic_intervals=[]
    for e in events:
        if e['kind']!='scheduler.wait_closed':continue
        d=e['detail'];previous=d.get('previous',{})
        if not wait_scope_ok(previous):continue
        a,b=stamp(d.get('started_at')),stamp(d.get('finished_at'))
        interval=wait_range(a,b)
        if interval is None or interval[1] is None:continue
        left,right=interval;automatic_intervals.append((left,right))
        automatic_waits.append({'event_id':e['id'],'wait_id':d.get('wait_id'),'reason':d['reason'],
            'started_at':d['started_at'],'finished_at':d['finished_at'],'seconds':right-left,
            'repair_case_id':previous.get('repair_case_id'),'batch_id':previous.get('batch_id'),
            'presentations':previous.get('presentations',[]),'open':False,'evidence':d.get('evidence')})
    for observation in observations:
        if not observation.get('reason'):continue
        detail=json.loads(observation['detail_json'])
        if not wait_scope_ok(detail) or wait_range(stamp(observation.get('started_at')),None) is None:continue
        automatic_waits.append({'wait_id':detail.get('wait_id'),'reason':observation['reason'],
            'started_at':observation['started_at'],'finished_at':None,'seconds':None,'open':True,
            'repair_case_id':detail.get('repair_case_id'),'batch_id':detail.get('batch_id'),
            'presentations':detail.get('presentations',[]),'evidence':'observed_control_state_transition'})
    # Provider turn timestamps exclude client-side resume/transport/reconcile.
    # Adapter intervals remain separately visible, never counted as new usage.
    timing_intervals=model_intervals if model_intervals else provider_intervals
    observed=union(timing_intervals+gate_intervals);bounds=[]
    for row in releases:
        if selected and row.get('presentation') not in selected:continue
        co=coordinates(artifacts.get(row.get('artifact_id'),{}).get('attempt_id'))
        if not scope_ok(co) or not in_time(row.get('committed_at')):continue
        dt=stamp(row.get('committed_at'))
        if dt:bounds.append(dt.timestamp())
    start=min((a for a,b in observed),default=None);end=max([b for a,b in observed]+bounds,default=None)
    window=(end-start) if start is not None and end is not None else None
    manual_wait_intervals=list(wait_intervals)
    wait_intervals+=automatic_intervals
    clipped_waits=[(max(a,start),min(b,end)) for a,b in wait_intervals if start is not None and end is not None and min(b,end)>=max(a,start)]
    expected=[a for a in attempts.values() if a.get('session_id') and (not selected or coordinates(a['id'])['presentation'] in selected)]
    if scoped:expected=[a for a in expected if scope_ok(coordinates(a['id'])) and (a['id'] in selected_attempts or in_time(a.get('started_at')))]
    for group in grouped:
        matches=[r for r in calls if all(r[k]==group[k] for k in ('presentation','kind','channel','operation'))]
        known=[r['provider_seconds'] for r in matches if r['provider_seconds'] is not None]
        group['provider_seconds']={'total':sum(known) if known and len(known)==len(matches) else None,'known_sum':sum(known),'known_records':len(known),'unknown_records':len(matches)-len(known)}
        ds=[d['seconds'] for d in durations if all(d[k]==group[k] for k in ('presentation','kind','channel','operation')) and type(d.get('seconds')) in (int,float)]
        group['adapter_seconds_known_sum']=sum(ds);group['adapter_duration_events']=len(ds)
    known_turn_seconds=[r['provider_seconds'] for r in calls if r['provider_seconds'] is not None]
    invalid=[{'call_id':r['call_id'],'issue':label} for r in calls for inner,outer,label in [('cached_input_tokens','input_tokens','cached_input_exceeds_input'),('reasoning_tokens','output_tokens','reasoning_exceeds_output')] if type(r.get(inner)) is int and type(r.get(outer)) is int and r[inner]>r[outer]]
    attempts_summary=grouping(calls,'attempt_id',counters)
    retired={e['detail'].get('attempt_id'):e['detail'] for e in events if e['kind']=='attempt.out_of_scope_retired'}
    for item in attempts_summary:
        aid=item['attempt_id'];item.update(coordinates(aid));item['recorded_error']=attempts.get(aid,{}).get('error');item['retirement']=retired.get(aid)
        item['reason_basis']='explicit_retirement_event' if aid in retired else 'recorded_attempt_error' if item['recorded_error'] else 'no_additional_reason_recorded'
    result={'version':2,'scope':{'task':str(task.resolve()),'presentations':sorted(selected) if selected else 'all','read_only':True,'model_calls':0,'repair_case_id':case_id,'batch_id':batch_id,'since':since,'until':until,'filter_combination':'intersection','time_selection':'whole_call_by_provider_start_else_usage_recorded_at; until_exclusive; no_token_proration'},
        'calls_observed':len(calls),'counters':counters(calls),'by_phase':grouped,'calls':calls,'by_case':grouping(calls,'repair_case_id',counters),'by_batch':grouping(calls,'batch_id',counters),'by_attempt':attempts_summary,'automatic_waits':automatic_waits,
        'coverage':{'calls_with_case':sum(bool(r['repair_case_id']) for r in calls),'calls_with_batch':sum(bool(r['batch_id']) for r in calls),'historical_scope_unassigned_calls':sum(r['scope_attribution']=='historical_unassigned' for r in calls),'attempts_with_usage':len(selected_attempts),'attempts_expected':len(expected),'calls_with_operation':sum(r['operation'] is not None for r in calls),'duration_events':len(durations),'calls_with_provider_timestamps':len(known_turn_seconds),'retained_index':index_coverage,'calls_with_duration_request':sum(any(d['request_id']==r['request_id'] for d in durations) for r in calls if r['request_id'])},
        'timing':{'provider_sum_seconds':sum(known_turn_seconds) if calls and len(known_turn_seconds)==len(calls) else None,'provider_known_sum_seconds':sum(known_turn_seconds),'provider_union_seconds':seconds(model_intervals) if model_intervals else None,
            'adapter_observed_sum_seconds':sum(d['seconds'] for d in durations if type(d.get('seconds')) in (int,float)) if durations else None,'adapter_observed_union_seconds':seconds(provider_intervals) if provider_intervals else None,
            'gate_sum_seconds':sum(g['seconds'] for g in gate_rows) if gate_rows and all(type(g.get('seconds')) in (int,float) for g in gate_rows) else None,'gate_known_sum_seconds':sum(g['seconds'] for g in gate_rows if type(g.get('seconds')) in (int,float)),'gate_union_seconds':seconds(gate_intervals) if gate_intervals else None,
            'observed_window_seconds':window,'observed_window_start':start,'observed_window_end':end,'call_and_gate_union_seconds':seconds(observed) if observed else None,'window_provider_basis':'indexed_turn_timestamps' if model_intervals else 'adapter_event_intervals' if provider_intervals else 'no_provider_timing',
            'automatic_observed_wait_union_seconds':seconds(automatic_intervals),'explicit_and_automatic_wait_union_seconds':seconds(clipped_waits),'explicit_wait_union_seconds':seconds([(max(a,start),min(b,end)) for a,b in manual_wait_intervals if start is not None and end is not None and min(b,end)>=max(a,start)]),'unattributed_seconds':max(0,window-seconds(observed+clipped_waits)) if window is not None else None,
            'coverage_warning':'Window starts at first recorded provider/gate interval, not necessarily task start. Gaps are NOT automatically idle. Historical event endpoints may have one-second precision.'},
        'duration_events':durations,'gates':gate_rows,'waits':waits,'cost_currency':None,'data_issues':invalid,
        'notes':['Cached input is INCLUDED in input; reasoning tokens are INCLUDED in output.','Unknown fields stay null; known sums are not complete totals.','Packet bytes are not full model context or token counts.','Reconciliation durations are observations, not additional paid model turns.','No price inferred. No main-agent/external provider usage is invented.','Historical missing case/batch attribution stays null. No date or current deck owner is used as a substitute.','Automatic waits measure time between control-state observations, not continuous monitoring or human inactivity. Open waits remain unknown. Scoped reports omit unscoped historical waits and never allocate a global wait to individual decks.']}
    return result

def render(value,format='json'):
    if format=='json':return json.dumps(value,ensure_ascii=False,indent=2)+'\n'
    if format=='csv':
        stream=io.StringIO();fields=['presentation','kind','channel','operation','attempt_id','attempt_sequence','call_id','request_id','model','effort','provider_turn_id','provider_seconds',*FIELDS,'packet_context_bytes','task_context_action','attribution','repair_case_id','batch_id','scope_attribution','selected_at','time_selection_basis']
        w=csv.DictWriter(stream,fields,extrasaction='ignore');w.writeheader();w.writerows(value['calls']);return stream.getvalue()
    if format!='md':raise MPresError('Report format must be json, md or csv')
    def number(x):return '未记录' if x is None else f'{x:,.0f}'
    out=['# Token 与耗时报告','',f"范围：返修案 {value['scope'].get('repair_case_id') or '全部'}；批次 {value['scope'].get('batch_id') or '全部'}；起点 {value['scope'].get('since') or '不限'}；终点 {value['scope'].get('until') or '不限'}（不含终点）。多个筛选条件取交集。",'',f"调用记录：{value['calls_observed']}；只读生成，未调用模型。",'', '|课件|阶段|通道|操作|调用数|总 token|供应端秒数|','|---|---|---|---|---:|---:|---:|']
    for r in value['by_phase']:out.append('|'+ '|'.join(str(r[k] or '—') for k in ('presentation','kind','channel','operation'))+f"|{r['calls']}|{number(r['counters']['total_tokens']['total'])}|{number(r['provider_seconds']['total'])}|")
    t=value['timing'];out+=['',f"总 token：{number(value['counters']['total_tokens']['total'])}；输入：{number(value['counters']['input_tokens']['total'])}（其中缓存：{number(value['counters']['cached_input_tokens']['total'])}）；输出：{number(value['counters']['output_tokens']['total'])}（其中推理：{number(value['counters']['reasoning_tokens']['total'])}）。",f"供应端时间覆盖：{value['coverage']['calls_with_provider_timestamps']}/{value['calls_observed']}；适配器观测累计（不同边界，不另算付费调用）：{number(t['adapter_observed_sum_seconds'])} 秒。",f"供应端调用累计：{number(t['provider_sum_seconds'])} 秒；去重覆盖：{number(t['provider_union_seconds'])} 秒。",f"机械门禁累计：{number(t['gate_sum_seconds'])} 秒；观测窗口：{number(t['observed_window_seconds'])} 秒。",f"尚不能归因的时间：{number(t['unattributed_seconds'])} 秒，不能直接解释为空等。",'', f"具有可靠返修案归属的调用：{value['coverage']['calls_with_case']}；具有批次归属的调用：{value['coverage']['calls_with_batch']}。未归属不等于没有发生，也不按时间猜测。", '缓存输入已包含在输入中，推理 token 已包含在输出中；缺失不是零。这里只统计本任务实际留下的供应端证据，不是完整费用账单。', '',t['coverage_warning']]
    out += ['', '## 实际记录的返工与退役', '', '|课件|阶段|attempt|序号|总 token|记录依据|', '|---|---|---|---:|---:|---|']
    problematic=[r for r in value['by_attempt'] if r.get('retirement') or r.get('recorded_error') or (r.get('attempt_sequence') or 0)>1]
    for r in problematic:
        out.append(f"|{r.get('presentation') or '—'}|{r.get('kind') or '—'}|{r['attempt_id']}|{r.get('attempt_sequence') or '—'}|{number(r['counters']['total_tokens']['total'])}|{r['reason_basis']}|")
    if not problematic:out.append('未找到可明确归入返工、错误或退役的记录；这不证明不存在额外开销。')
    out += ['', '## 已观察的调度阻塞', '', '|原因|状态|秒数|', '|---|---|---:|']
    for r in value['automatic_waits']:
        out.append(f"|{r['reason']}|{'尚未结束' if r['open'] else '已观察到结束'}|{number(r['seconds'])}|")
    if not value['automatic_waits']:out.append('没有可归属到此范围的自动阻塞记录，不用历史空档补造。')
    out += ['', '自动阻塞是两个控制状态观测之间的间隔，不证明期间人员或模型一直空闲。未结束间隔不补时长，多课件全局等待不重复分摊。']
    return '\n'.join(out)+'\n'
