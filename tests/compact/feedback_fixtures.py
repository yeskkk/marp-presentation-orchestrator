"""Explicit policies for deterministic fixtures, never a production bypass flag."""
from mpres.control.feedback import Feedback


def infrastructure_only(service):
    # Pre-existing tests concern execution mechanics, not the mathematical quality
    # of their one-line fake slides. They explicitly retire the default semantic
    # requirements through the public, attributed API. New feedback tests re-enable
    # them and exercise the actual before/after gates and independent review.
    f=Feedback(service.task)
    for rule in f.list():
        f.record({k:(False if k=='enabled' else v) for k,v in rule.items() if k!='version'},
                 'deterministic-infrastructure-fixture owner')


def teaching_policy(service):
    f=Feedback(service.task)
    latest={r['id']:r for r in f.list(True)}
    for rule in latest.values():
        f.record({k:(True if k=='enabled' else v) for k,v in rule.items()
                  if k not in {'version','actor','created_at'}},'teaching-quality-fixture owner')
    return f


def readback(rules):
    return [{'id':r['id'],'version':r['version'],
             'approach':'Check the precise requirement against the lesson content and cite its actual slide evidence: '+r['expectation']}
            for r in rules]


def checks(rules, slide_id, quote):
    # This is structural evidence from an explicitly fake model, not a quality claim.
    return [{'id':r['id'],'version':r['version'],'status':'satisfied',
             'explanation':'Deterministic protocol fixture; a real reviewer must judge the content.',
             'evidence':[{'slide_id':slide_id,'quote':quote}]} for r in rules]
