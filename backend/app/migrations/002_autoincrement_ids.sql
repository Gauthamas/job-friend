-- Every table used plain "INTEGER PRIMARY KEY", which lets SQLite reuse the
-- id of a deleted row (specifically: whenever the highest-numbered row in a
-- table is removed, the next insert can reclaim that id). That's unsafe
-- anywhere a row can be deleted while other rows still hold its id by
-- foreign key — unit and requirement both plan to support that (soft
-- delete). AUTOINCREMENT makes SQLite track the highest id a table has EVER
-- used (via sqlite_sequence) and never reissue it, even after a delete.
--
-- SQLite has no ALTER COLUMN, so each table is recreated with the same
-- shape plus AUTOINCREMENT, existing rows are copied over verbatim (ids
-- unchanged), and the old table is dropped.

PRAGMA foreign_keys = OFF;

CREATE TABLE profile_new (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
INSERT INTO profile_new SELECT * FROM profile;
DROP TABLE profile;
ALTER TABLE profile_new RENAME TO profile;

CREATE TABLE inventory_new (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  profile_id INTEGER NOT NULL REFERENCES profile(id),
  name TEXT NOT NULL,
  source_file TEXT,
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
INSERT INTO inventory_new SELECT * FROM inventory;
DROP TABLE inventory;
ALTER TABLE inventory_new RENAME TO inventory;

CREATE TABLE role_new (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  inventory_id INTEGER NOT NULL REFERENCES inventory(id),
  company TEXT NOT NULL,
  title TEXT NOT NULL,
  start_date TEXT,
  end_date TEXT,
  sort_order INTEGER NOT NULL
);
INSERT INTO role_new SELECT * FROM role;
DROP TABLE role;
ALTER TABLE role_new RENAME TO role;

CREATE TABLE unit_new (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  role_id INTEGER NOT NULL REFERENCES role(id),
  text TEXT NOT NULL,
  source TEXT NOT NULL CHECK(source IN ('parsed','manual','later_version')),
  sort_order INTEGER NOT NULL,
  context TEXT,
  contribution TEXT,
  outcome TEXT,
  skills_json TEXT,
  updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);
INSERT INTO unit_new SELECT * FROM unit;
DROP TABLE unit;
ALTER TABLE unit_new RENAME TO unit;

CREATE TABLE unit_embedding_new (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  unit_id INTEGER NOT NULL REFERENCES unit(id),
  field TEXT NOT NULL CHECK(field IN ('text','context','contribution','outcome')),
  model TEXT NOT NULL,
  vector BLOB NOT NULL,
  UNIQUE(unit_id, field, model)
);
INSERT INTO unit_embedding_new SELECT * FROM unit_embedding;
DROP TABLE unit_embedding;
ALTER TABLE unit_embedding_new RENAME TO unit_embedding;

CREATE TABLE flow_new (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  profile_id INTEGER NOT NULL REFERENCES profile(id),
  name TEXT NOT NULL,
  inventory_id INTEGER NOT NULL REFERENCES inventory(id),
  style_profile_id INTEGER,
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
INSERT INTO flow_new SELECT * FROM flow;
DROP TABLE flow;
ALTER TABLE flow_new RENAME TO flow;

CREATE TABLE job_new (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  flow_id INTEGER NOT NULL REFERENCES flow(id),
  title TEXT NOT NULL,
  jd_text TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
INSERT INTO job_new SELECT * FROM job;
DROP TABLE job;
ALTER TABLE job_new RENAME TO job;

CREATE TABLE requirement_new (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  job_id INTEGER NOT NULL REFERENCES job(id),
  text TEXT NOT NULL,
  weight TEXT NOT NULL CHECK(weight IN ('high','medium','low')),
  source TEXT NOT NULL CHECK(source IN ('extracted','user')),
  status TEXT NOT NULL CHECK(status IN ('queued','judging','done','error')),
  version INTEGER NOT NULL DEFAULT 1,
  reason TEXT,
  sort_order INTEGER NOT NULL,
  deleted INTEGER NOT NULL DEFAULT 0
);
INSERT INTO requirement_new SELECT * FROM requirement;
DROP TABLE requirement;
ALTER TABLE requirement_new RENAME TO requirement;

CREATE TABLE judgment_new (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  requirement_id INTEGER NOT NULL REFERENCES requirement(id),
  unit_id INTEGER NOT NULL REFERENCES unit(id),
  score REAL,
  model_verdict TEXT CHECK(model_verdict IN ('match','weak','none')),
  user_verdict TEXT CHECK(user_verdict IN ('match','weak','none')),
  added_by_user INTEGER NOT NULL DEFAULT 0,
  unit_snapshot TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
INSERT INTO judgment_new SELECT * FROM judgment;
DROP TABLE judgment;
ALTER TABLE judgment_new RENAME TO judgment;

-- Recreated: dropping a table drops its indexes.
CREATE INDEX idx_role_inventory ON role(inventory_id);
CREATE INDEX idx_unit_role ON unit(role_id);
CREATE INDEX idx_unit_embedding_unit ON unit_embedding(unit_id);
CREATE INDEX idx_requirement_job ON requirement(job_id);
CREATE INDEX idx_judgment_requirement ON judgment(requirement_id);
CREATE INDEX idx_judgment_unit ON judgment(unit_id);

PRAGMA foreign_keys = ON;
