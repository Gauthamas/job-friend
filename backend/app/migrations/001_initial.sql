CREATE TABLE profile (
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE inventory (
  id INTEGER PRIMARY KEY,
  profile_id INTEGER NOT NULL REFERENCES profile(id),
  name TEXT NOT NULL,
  source_file TEXT,
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE role (
  id INTEGER PRIMARY KEY,
  inventory_id INTEGER NOT NULL REFERENCES inventory(id),
  company TEXT NOT NULL,
  title TEXT NOT NULL,
  start_date TEXT,
  end_date TEXT,
  sort_order INTEGER NOT NULL
);

CREATE TABLE unit (
  id INTEGER PRIMARY KEY,
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

CREATE TABLE unit_embedding (
  id INTEGER PRIMARY KEY,
  unit_id INTEGER NOT NULL REFERENCES unit(id),
  field TEXT NOT NULL CHECK(field IN ('text','context','contribution','outcome')),
  model TEXT NOT NULL,
  vector BLOB NOT NULL,
  UNIQUE(unit_id, field, model)
);

CREATE TABLE flow (
  id INTEGER PRIMARY KEY,
  profile_id INTEGER NOT NULL REFERENCES profile(id),
  name TEXT NOT NULL,
  inventory_id INTEGER NOT NULL REFERENCES inventory(id),
  style_profile_id INTEGER,
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE job (
  id INTEGER PRIMARY KEY,
  flow_id INTEGER NOT NULL REFERENCES flow(id),
  title TEXT NOT NULL,
  jd_text TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE requirement (
  id INTEGER PRIMARY KEY,
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

CREATE TABLE judgment (
  id INTEGER PRIMARY KEY,
  requirement_id INTEGER NOT NULL REFERENCES requirement(id),
  unit_id INTEGER NOT NULL REFERENCES unit(id),
  score REAL,
  model_verdict TEXT CHECK(model_verdict IN ('match','weak','none')),
  user_verdict TEXT CHECK(user_verdict IN ('match','weak','none')),
  added_by_user INTEGER NOT NULL DEFAULT 0,
  unit_snapshot TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX idx_role_inventory ON role(inventory_id);
CREATE INDEX idx_unit_role ON unit(role_id);
CREATE INDEX idx_unit_embedding_unit ON unit_embedding(unit_id);
CREATE INDEX idx_requirement_job ON requirement(job_id);
CREATE INDEX idx_judgment_requirement ON judgment(requirement_id);
CREATE INDEX idx_judgment_unit ON judgment(unit_id);
