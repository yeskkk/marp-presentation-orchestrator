
CREATE TABLE IF NOT EXISTS maintenance_runs (id TEXT PRIMARY KEY, operation TEXT NOT NULL, actor TEXT NOT NULL, started_at TEXT NOT NULL, finished_at TEXT, state TEXT NOT NULL, plan_id TEXT, detail_json TEXT NOT NULL);
