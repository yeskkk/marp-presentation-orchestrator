"""Explicit main scope decisions over immutable author reports, not semantic auto-approval."""
import hashlib
import json


def accepted_boundary(service, artifact):
    rows=service.store.rows("SELECT detail_json FROM events WHERE kind='author.verification_boundary_resolved' AND json_extract(detail_json,'$.artifact_id')=? ORDER BY id DESC LIMIT 1",(artifact,))
    if not rows: return {}
    decision=json.loads(rows[0]['detail_json'])
    report=service.store.rows('SELECT a.id,a.result_json FROM attempts a JOIN artifacts r ON r.attempt_id=a.id WHERE r.id=?',(artifact,))
    if not report or report[0]['id']!=decision['attempt_id']: return {}
    if hashlib.sha256(report[0]['result_json'].encode()).hexdigest()!=decision['report_sha256']: return {}
    from .quality import Quality
    gate=Quality(service.task).require_pass(artifact)
    if gate['id']!=decision['gate_id']: return {}
    return decision
