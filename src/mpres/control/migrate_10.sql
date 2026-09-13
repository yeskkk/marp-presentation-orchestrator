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
