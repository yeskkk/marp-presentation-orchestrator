-- Additive v0.9.7 migration. v0.9.6 checkpoint/tombstone schema is unchanged.
CREATE TABLE IF NOT EXISTS job_cost_context (
 job_id TEXT PRIMARY KEY REFERENCES jobs(id),
 repair_case_id TEXT REFERENCES repair_cases(id),
 batch_id TEXT REFERENCES production_batches(id),
 source TEXT NOT NULL, recorded_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS scheduler_observation (
 singleton INTEGER PRIMARY KEY CHECK(singleton=1),
 reason TEXT, started_at TEXT, detail_json TEXT NOT NULL, updated_at TEXT NOT NULL
);
