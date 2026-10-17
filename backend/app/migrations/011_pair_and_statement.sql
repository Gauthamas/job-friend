-- Milestone 3: pair builder and similarity
-- statements. New tables only -- nothing existing changes.

CREATE TABLE pair (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  job_id INTEGER NOT NULL REFERENCES job(id),
  unit_a_id INTEGER NOT NULL REFERENCES unit(id),
  unit_b_id INTEGER NOT NULL REFERENCES unit(id),
  score REAL NOT NULL,
  model TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  UNIQUE(job_id, unit_a_id, unit_b_id)
);

CREATE TABLE statement (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  pair_id INTEGER NOT NULL UNIQUE REFERENCES pair(id),
  status TEXT NOT NULL DEFAULT 'unanswered' CHECK(status IN ('unanswered', 'written', 'none')),
  text TEXT NULL,
  autofilled_from_job_id INTEGER NULL REFERENCES job(id),
  confirmed INTEGER NOT NULL DEFAULT 1,
  updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);
