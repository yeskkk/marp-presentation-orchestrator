PRAGMA user_version = 10;
CREATE TABLE task (
    singleton INTEGER PRIMARY KEY CHECK (singleton=1), title TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('draft','running','paused','completed')),
    created_at TEXT NOT NULL, presented_json TEXT, author_slots_limit INTEGER, config_id INTEGER REFERENCES configs(id)
);
CREATE TABLE configs (
    id INTEGER PRIMARY KEY, settings_json TEXT NOT NULL, runtime_json TEXT NOT NULL,
    task_text TEXT NOT NULL, task_digest TEXT NOT NULL,
    confirmed_by TEXT NOT NULL, confirmed_at TEXT NOT NULL
);
CREATE TRIGGER immutable_config_update BEFORE UPDATE ON configs BEGIN
    SELECT RAISE(ABORT, 'confirmed configuration is immutable'); END;
CREATE TRIGGER immutable_config_delete BEFORE DELETE ON configs BEGIN
    SELECT RAISE(ABORT, 'confirmed configuration is immutable'); END;
CREATE TABLE plan_items (
    id INTEGER PRIMARY KEY, config_id INTEGER NOT NULL REFERENCES configs(id),
    presentation TEXT NOT NULL, unit TEXT NOT NULL, deck_title TEXT NOT NULL,
    title TEXT NOT NULL, ordinal INTEGER NOT NULL, brief TEXT NOT NULL,
    sources_json TEXT NOT NULL, UNIQUE(config_id,presentation,unit), UNIQUE(config_id,ordinal)
);
CREATE TABLE jobs (
    id TEXT PRIMARY KEY, key TEXT NOT NULL UNIQUE, config_id INTEGER NOT NULL REFERENCES configs(id),
    plan_item_id INTEGER REFERENCES plan_items(id), presentation TEXT NOT NULL,
    kind TEXT NOT NULL CHECK(kind IN ('write','assemble','edit','review','revise','gate','release','diagnose')),
    family TEXT CHECK(family IN ('planner','author','reviewer')),
    round INTEGER NOT NULL DEFAULT 0, channel TEXT NOT NULL DEFAULT '',
    input_artifact_id TEXT REFERENCES artifacts(id),
    state TEXT NOT NULL DEFAULT 'queued' CHECK(state IN ('queued','running','succeeded','failed','blocked')),
    created_at TEXT NOT NULL, UNIQUE(presentation,kind,plan_item_id,round,channel,input_artifact_id)
);
CREATE TABLE dependencies (
    job_id TEXT NOT NULL REFERENCES jobs(id), needs_id TEXT NOT NULL REFERENCES jobs(id),
    PRIMARY KEY(job_id,needs_id), CHECK(job_id<>needs_id)
);
CREATE TABLE sessions (
    id TEXT PRIMARY KEY, family TEXT NOT NULL CHECK(family IN ('planner','author','reviewer')),
    model TEXT NOT NULL, effort TEXT NOT NULL CHECK(effort IN ('low','medium','high','max')),
    state TEXT NOT NULL DEFAULT 'open' CHECK(state IN ('open','uncertain','closed')),
    receipt TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE attempts (
    id TEXT PRIMARY KEY, job_id TEXT NOT NULL REFERENCES jobs(id),
    session_id TEXT REFERENCES sessions(id), sequence INTEGER NOT NULL,
    state TEXT NOT NULL CHECK(state IN ('reserved','running','uncertain','succeeded','failed')),
    started_at TEXT NOT NULL, finished_at TEXT, provider_receipt TEXT,
    result_json TEXT, error TEXT, UNIQUE(job_id,sequence)
);
CREATE UNIQUE INDEX one_live_job ON attempts(job_id) WHERE state IN ('reserved','running','uncertain');
CREATE UNIQUE INDEX one_live_session ON attempts(session_id) WHERE session_id IS NOT NULL AND state IN ('reserved','running','uncertain');
CREATE TABLE participation (
    session_id TEXT NOT NULL REFERENCES sessions(id), presentation TEXT NOT NULL,
    kind TEXT NOT NULL, round INTEGER NOT NULL, channel TEXT NOT NULL,
    PRIMARY KEY(session_id,presentation,kind,round,channel)
);
CREATE TABLE artifacts (
    id TEXT PRIMARY KEY, attempt_id TEXT REFERENCES attempts(id), presentation TEXT NOT NULL,
    unit TEXT, path TEXT NOT NULL UNIQUE, entrypoint TEXT NOT NULL DEFAULT 'presentation.md', created_at TEXT NOT NULL,
    origin TEXT NOT NULL CHECK(origin IN ('submission','import','assembly')),
    verified INTEGER NOT NULL DEFAULT 0 CHECK(verified IN (0,1))
);
CREATE TABLE checks (
    id INTEGER PRIMARY KEY, artifact_id TEXT NOT NULL REFERENCES artifacts(id),
    name TEXT NOT NULL, success INTEGER NOT NULL CHECK(success IN (0,1)),
    detail_json TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE findings (
    id TEXT PRIMARY KEY, job_id TEXT NOT NULL REFERENCES jobs(id),
    artifact_id TEXT NOT NULL REFERENCES artifacts(id), channel TEXT NOT NULL,
    detail_json TEXT NOT NULL, resolution_json TEXT
);
CREATE TABLE decisions (
    id INTEGER PRIMARY KEY, kind TEXT NOT NULL, presentation TEXT,
    detail_json TEXT NOT NULL, resolved_at TEXT, answer TEXT
);
CREATE TABLE events (
    id INTEGER PRIMARY KEY, kind TEXT NOT NULL, job_id TEXT REFERENCES jobs(id),
    detail_json TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE usage (
    attempt_id TEXT NOT NULL REFERENCES attempts(id), call_id TEXT NOT NULL,
    input_tokens INTEGER CHECK(input_tokens>=0), cached_input_tokens INTEGER CHECK(cached_input_tokens>=0),
    output_tokens INTEGER CHECK(output_tokens>=0), reasoning_tokens INTEGER CHECK(reasoning_tokens>=0),
    total_tokens INTEGER CHECK(total_tokens>=0), created_at TEXT NOT NULL,
    PRIMARY KEY(attempt_id,call_id),
    CHECK(cached_input_tokens IS NULL OR input_tokens IS NULL OR cached_input_tokens<=input_tokens)
);
CREATE UNIQUE INDEX one_unit_write ON jobs(plan_item_id) WHERE kind='write';

CREATE TABLE pool_slots (
    id INTEGER PRIMARY KEY, key TEXT NOT NULL UNIQUE,
    kind TEXT NOT NULL CHECK(kind IN ('write','edit','review')),
    channel TEXT NOT NULL, family TEXT NOT NULL, model TEXT NOT NULL, effort TEXT NOT NULL,
    ordinal INTEGER NOT NULL, session_id TEXT UNIQUE REFERENCES sessions(id),
    state TEXT NOT NULL CHECK(state IN ('pending','creating','ready','uncertain'))
);
CREATE TABLE runtime_host (
    singleton INTEGER PRIMARY KEY CHECK(singleton=1), report_json TEXT NOT NULL, observed_at TEXT NOT NULL
);

CREATE TABLE gate_runs (
    id TEXT PRIMARY KEY, artifact_id TEXT NOT NULL REFERENCES artifacts(id),
    level TEXT NOT NULL CHECK(level IN ('source','full')),
    sequence INTEGER NOT NULL, state TEXT NOT NULL CHECK(state IN ('running','passed','failed','interrupted')),
    started_at TEXT NOT NULL, finished_at TEXT, detail_json TEXT, pdf_path TEXT,
    UNIQUE(artifact_id,level,sequence)
);
CREATE UNIQUE INDEX one_active_gate ON gate_runs(artifact_id,level) WHERE state='running';

CREATE TABLE decks (
 presentation TEXT PRIMARY KEY, config_id INTEGER NOT NULL REFERENCES configs(id), ordinal INTEGER NOT NULL UNIQUE,
 phase TEXT NOT NULL CHECK(phase IN ('units','editing','preflight','reviewing','revising','postflight','releasing','delivered','blocked')),
 candidate_id TEXT REFERENCES artifacts(id), frozen_id TEXT REFERENCES artifacts(id), active_job_id TEXT REFERENCES jobs(id),
 repair_count INTEGER NOT NULL DEFAULT 0, blocked_from TEXT, block_reason TEXT, delivered_at TEXT
);
CREATE TABLE releases (
 presentation TEXT PRIMARY KEY REFERENCES decks(presentation), artifact_id TEXT NOT NULL REFERENCES artifacts(id),
 gate_id TEXT NOT NULL REFERENCES gate_runs(id), pdf_path TEXT NOT NULL UNIQUE,
 state TEXT NOT NULL CHECK(state IN ('prepared','committed')), created_at TEXT NOT NULL, committed_at TEXT
);

CREATE TABLE feedback_rules (
 id TEXT NOT NULL, version INTEGER NOT NULL CHECK(version>0),
 payload_json TEXT NOT NULL, actor TEXT NOT NULL, created_at TEXT NOT NULL,
 PRIMARY KEY(id,version)
);
CREATE TABLE attempt_briefings (
 attempt_id TEXT PRIMARY KEY REFERENCES attempts(id), snapshot_json TEXT NOT NULL,
 acknowledgement_json TEXT, receipt TEXT, brief_dispatched INTEGER NOT NULL DEFAULT 0,
 run_dispatched INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL
);

CREATE TABLE repair_cases (
 id TEXT PRIMARY KEY, report TEXT NOT NULL, requested_by TEXT NOT NULL, created_at TEXT NOT NULL,
 state TEXT NOT NULL CHECK(state IN ('diagnosing','proposed','presented','running','completed','cancelled')),
 proposal_json TEXT, proposal_version INTEGER NOT NULL DEFAULT 0, presented_json TEXT,
 confirmed_by TEXT, confirmed_at TEXT, previous_task_status TEXT
);
CREATE TABLE repair_targets (
 case_id TEXT NOT NULL REFERENCES repair_cases(id), presentation TEXT NOT NULL REFERENCES decks(presentation),
 baseline_artifact_id TEXT NOT NULL REFERENCES artifacts(id), baseline_pdf_path TEXT NOT NULL,
 release_revision INTEGER NOT NULL, delivered_at TEXT,
 PRIMARY KEY(case_id,presentation)
);
CREATE TABLE repair_jobs (
 job_id TEXT PRIMARY KEY REFERENCES jobs(id), case_id TEXT NOT NULL REFERENCES repair_cases(id),
 stage TEXT NOT NULL CHECK(stage IN ('proposal','edit'))
);
CREATE TABLE release_versions (
 presentation TEXT NOT NULL REFERENCES decks(presentation), revision INTEGER NOT NULL,
 artifact_id TEXT NOT NULL REFERENCES artifacts(id), gate_id TEXT NOT NULL REFERENCES gate_runs(id),
 pdf_path TEXT NOT NULL UNIQUE, state TEXT NOT NULL CHECK(state IN ('prepared','committed')),
 created_at TEXT NOT NULL, committed_at TEXT, case_id TEXT REFERENCES repair_cases(id),
 PRIMARY KEY(presentation,revision)
);
ALTER TABLE decks ADD COLUMN repair_case TEXT REFERENCES repair_cases(id);
ALTER TABLE decks ADD COLUMN review_round INTEGER NOT NULL DEFAULT 1;
INSERT INTO release_versions(presentation,revision,artifact_id,gate_id,pdf_path,state,created_at,committed_at)
 SELECT presentation,1,artifact_id,gate_id,pdf_path,state,created_at,committed_at FROM releases;

CREATE TABLE audience_steps (
 attempt_id TEXT NOT NULL REFERENCES attempts(id), sequence INTEGER NOT NULL,
 phase TEXT NOT NULL CHECK(phase IN ('student','production_language')),
 artifact_id TEXT NOT NULL REFERENCES artifacts(id), slide_ids_json TEXT NOT NULL,
 state TEXT NOT NULL CHECK(state IN ('pending','dispatched','completed')),
 receipt TEXT, result_json TEXT, completed_at TEXT,
 PRIMARY KEY(attempt_id,sequence)
);

ALTER TABLE repair_cases ADD COLUMN mode TEXT NOT NULL DEFAULT 'edit-first' CHECK(mode IN ('edit-first','review-first'));
ALTER TABLE repair_cases ADD COLUMN allow_slide_changes INTEGER NOT NULL DEFAULT 0 CHECK(allow_slide_changes IN (0,1));

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

CREATE TABLE policy_values (
 config_id INTEGER NOT NULL REFERENCES configs(id), name TEXT NOT NULL,
 event_id INTEGER NOT NULL REFERENCES events(id), PRIMARY KEY(config_id,name)
);
CREATE TABLE policy_cursor (singleton INTEGER PRIMARY KEY CHECK(singleton=1), event_id INTEGER NOT NULL);
INSERT INTO policy_cursor VALUES(1,0);
CREATE INDEX events_kind_id ON events(kind,id);
CREATE TABLE production_batches (
 id TEXT PRIMARY KEY, config_id INTEGER NOT NULL REFERENCES configs(id),
 state TEXT NOT NULL CHECK(state IN ('presented','running','completed')),
 snapshot_json TEXT NOT NULL, created_at TEXT NOT NULL, confirmed_at TEXT, confirmed_by TEXT
);
CREATE UNIQUE INDEX one_running_batch ON production_batches(state) WHERE state='running';
CREATE TABLE production_batch_targets (
 batch_id TEXT NOT NULL REFERENCES production_batches(id),
 presentation TEXT NOT NULL REFERENCES decks(presentation), ordinal INTEGER NOT NULL,
 PRIMARY KEY(batch_id,presentation), UNIQUE(batch_id,ordinal)
);
