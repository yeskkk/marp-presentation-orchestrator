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
