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
