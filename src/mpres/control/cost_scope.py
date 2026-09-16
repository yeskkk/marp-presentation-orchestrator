"""Exact historical/job attribution. Dates and today's deck state are NOT lineage."""
from __future__ import annotations
from collections import defaultdict
from datetime import datetime
from mpres.util import MPresError


def boundary(value, name):
    if value is None:return None
    try:
        dt=datetime.fromisoformat(value.replace('Z','+00:00'))
        if dt.tzinfo is None:raise ValueError('timezone missing')
    except (ValueError,TypeError,AttributeError) as exc:
        raise MPresError(f'{name} must be an ISO timestamp with an explicit timezone') from exc
    return dt.timestamp()


def lineage(jobs,attempts,artifacts,links,contexts,requests,cases):
    """Persisted pins, explicit repair links, then exact artifact ancestry only.

    An old input draft is never enough to pin a NEW edit/diagnosis/write job to
    the old repair case. Those are explicit scope boundaries. Review/revise/gate
    nodes can inherit their one exact input's producer. Ambiguity stays unknown.
    """
    result={};claims=defaultdict(set)
    for r in links:claims[r['job_id']].add(r['case_id'])
    for q in requests.values():
        a=attempts.get(q.get('attempt_id'),{});jid=a.get('job_id')
        if not jid:continue
        packet=q.get('packet',{});scope=packet.get('repair_scope') or {}
        case=scope.get('case_id')
        if case in cases:claims[jid].add(case)
    pins={r['job_id']:r for r in contexts}
    for jid,j in jobs.items():
        if jid in pins:
            p=pins[jid];result[jid]={'repair_case_id':p['repair_case_id'],'batch_id':p['batch_id'],'scope_attribution':p['source']}
        elif len(claims[jid])==1:
            result[jid]={'repair_case_id':next(iter(claims[jid])),'batch_id':None,'scope_attribution':'exact_repair_link_or_packet'}
        else:result[jid]={'repair_case_id':None,'batch_id':None,'scope_attribution':'ambiguous' if claims[jid] else 'historical_unassigned'}
    # Review-first jobs encode the exact case as a delimited key field. Use the
    # stored key definition, not arbitrary substring search or date matching.
    for jid,j in jobs.items():
        if jid in pins or claims[jid]:continue
        fields=(j.get('key') or '').split(':')
        matched=fields[1] if len(fields)==4 and fields[0]=='repair-review' and fields[1] in cases else None
        if matched and j['kind']=='review':
            result[jid]={'repair_case_id':matched,'batch_id':None,'scope_attribution':'exact_review_first_job_key'}
    for _ in range(len(jobs)+1):
        changed=False
        for jid,j in jobs.items():
            if jid in pins or result[jid]['scope_attribution']!='historical_unassigned':continue
            if j['kind'] not in {'review','revise','gate','release'}:continue
            a=artifacts.get(j.get('input_artifact_id'),{});parent=attempts.get(a.get('attempt_id'),{}).get('job_id')
            p=result.get(parent,{})
            if p.get('repair_case_id'):
                result[jid]={'repair_case_id':p['repair_case_id'],'batch_id':p.get('batch_id'),'scope_attribution':'exact_input_artifact_lineage'};changed=True
        if not changed:break
    return result


def grouping(calls,field,counters):
    groups=defaultdict(list)
    for r in calls:groups[r.get(field)].append(r)
    return [{field:k,'calls':len(v),'counters':counters(v)} for k,v in sorted(groups.items(),key=lambda x:str(x[0]))]
