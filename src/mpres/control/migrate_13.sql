CREATE TABLE IF NOT EXISTS current_checkpoints (
 id TEXT PRIMARY KEY, state TEXT NOT NULL, created_at TEXT NOT NULL, finished_at TEXT,
 actor TEXT NOT NULL, plan_json TEXT NOT NULL, result_json TEXT
);
CREATE TABLE IF NOT EXISTS retention_tombstones (
 path TEXT PRIMARY KEY, kind TEXT NOT NULL, sha256 TEXT NOT NULL, bytes INTEGER NOT NULL,
 checkpoint_id TEXT NOT NULL REFERENCES current_checkpoints(id), removed_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS current_retention_policy (
 singleton INTEGER PRIMARY KEY CHECK(singleton=1), enabled INTEGER NOT NULL CHECK(enabled IN (0,1)),
 actor TEXT NOT NULL, confirmed_at TEXT NOT NULL, version INTEGER NOT NULL DEFAULT 1
);
