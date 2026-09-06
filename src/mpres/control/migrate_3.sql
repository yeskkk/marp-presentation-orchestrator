CREATE TABLE gate_runs (
    id TEXT PRIMARY KEY, artifact_id TEXT NOT NULL REFERENCES artifacts(id),
    level TEXT NOT NULL CHECK(level IN ('source','full')),
    sequence INTEGER NOT NULL, state TEXT NOT NULL CHECK(state IN ('running','passed','failed','interrupted')),
    started_at TEXT NOT NULL, finished_at TEXT, detail_json TEXT, pdf_path TEXT,
    UNIQUE(artifact_id,level,sequence)
);
CREATE UNIQUE INDEX one_active_gate ON gate_runs(artifact_id,level) WHERE state='running';
