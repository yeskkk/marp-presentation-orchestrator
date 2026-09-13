CREATE TABLE host_requests (
    request_id TEXT PRIMARY KEY, attempt_id TEXT REFERENCES attempts(id),
    operation TEXT NOT NULL CHECK(operation IN ('create','brief','run','audience_step')),
    session_id TEXT REFERENCES sessions(id), request_json TEXT NOT NULL,
    state TEXT NOT NULL DEFAULT 'issued' CHECK(state IN ('issued','received','rejected','accepted')),
    created_at TEXT NOT NULL, accepted_at TEXT, last_error TEXT
);
CREATE TABLE host_responses (
    request_id TEXT PRIMARY KEY REFERENCES host_requests(request_id),
    response_json TEXT NOT NULL, received_at TEXT NOT NULL
);
CREATE INDEX host_requests_attempt ON host_requests(attempt_id,created_at);
CREATE INDEX host_requests_state ON host_requests(state,created_at);
CREATE INDEX events_kind_job_id ON events(kind,job_id,id);
CREATE INDEX events_request_kind ON events(kind,json_extract(detail_json,'$.request_id'),id);
