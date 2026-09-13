CREATE TABLE plan_changes (
 id TEXT PRIMARY KEY, config_id INTEGER NOT NULL REFERENCES configs(id),
 state TEXT NOT NULL CHECK(state IN ('presented','confirmed','cancelled')),
 proposal_json TEXT NOT NULL, baseline_json TEXT NOT NULL, created_at TEXT NOT NULL,
 confirmed_at TEXT, confirmed_by TEXT
);
CREATE TABLE delivery_parts (
 presentation TEXT PRIMARY KEY REFERENCES decks(presentation),
 parent TEXT NOT NULL REFERENCES decks(presentation),
 ordinal INTEGER NOT NULL, title TEXT NOT NULL,
 estimated_pages INTEGER NOT NULL CHECK(estimated_pages BETWEEN 1 AND 100),
 change_id TEXT NOT NULL REFERENCES plan_changes(id), UNIQUE(parent,ordinal)
);
CREATE INDEX delivery_parts_parent ON delivery_parts(parent,ordinal);
CREATE TABLE plan_item_origins (
 plan_item_id INTEGER PRIMARY KEY REFERENCES plan_items(id),
 source_plan_item_id INTEGER NOT NULL REFERENCES plan_items(id),
 baseline_artifact_id TEXT REFERENCES artifacts(id)
);
