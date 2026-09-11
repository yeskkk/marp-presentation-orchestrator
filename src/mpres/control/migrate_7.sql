CREATE TABLE audience_steps (
 attempt_id TEXT NOT NULL REFERENCES attempts(id), sequence INTEGER NOT NULL,
 phase TEXT NOT NULL CHECK(phase IN ('student','production_language')),
 artifact_id TEXT NOT NULL REFERENCES artifacts(id), slide_ids_json TEXT NOT NULL,
 state TEXT NOT NULL CHECK(state IN ('pending','dispatched','completed')),
 receipt TEXT, result_json TEXT, completed_at TEXT,
 PRIMARY KEY(attempt_id,sequence)
);
