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
