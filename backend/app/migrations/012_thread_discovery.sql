-- Milestone 4: thread discovery. New tables
-- only -- nothing existing changes.
--
-- thread_run.error extends the v2 spec's original definition: "An
-- exception in any call is caught, recorded on the run with its type and
-- message, and the run ends cleanly" needs somewhere durable to live.

CREATE TABLE thread_run (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  job_id INTEGER NOT NULL REFERENCES job(id),
  params_json TEXT NOT NULL,
  statements_snapshot_json TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  error TEXT NULL
);

CREATE TABLE thread (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id INTEGER NOT NULL REFERENCES thread_run(id),
  idea TEXT NOT NULL,
  edited_idea TEXT NULL,
  source TEXT NOT NULL CHECK(source IN ('model', 'user')),
  stale INTEGER NOT NULL DEFAULT 0,
  deleted INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE thread_statement (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  thread_id INTEGER NOT NULL REFERENCES thread(id),
  statement_id INTEGER NOT NULL REFERENCES statement(id),
  origin TEXT NOT NULL CHECK(origin IN ('proposed', 'assigned', 'user')),
  UNIQUE(thread_id, statement_id)
);

CREATE TABLE thread_unit (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  thread_id INTEGER NOT NULL REFERENCES thread(id),
  unit_id INTEGER NOT NULL REFERENCES unit(id),
  model_verdict TEXT NULL,
  quote TEXT NULL,
  user_verdict TEXT NULL,
  UNIQUE(thread_id, unit_id)
);

CREATE TABLE job_thread (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  job_id INTEGER NOT NULL REFERENCES job(id),
  thread_id INTEGER NOT NULL REFERENCES thread(id),
  role TEXT NOT NULL CHECK(role IN ('primary', 'secondary'))
);
