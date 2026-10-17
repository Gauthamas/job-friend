-- v2 simplified judging.
--
-- requirement.status collapses to 'pending'/'done' only -- 'queued' and
-- 'judging' map to 'pending' (nothing can be mid-flight after a restart,
-- since v2 keeps no state of its own beyond the two job-level timestamps);
-- 'error' also maps to 'pending', its reason preserved in the new
-- last_error column instead of a separate status. version is dropped: v2
-- has no stale-result discarding to key off it.
--
-- judgment.unit_snapshot is dropped: v2 reads the unit's current text at
-- judging time instead of freezing a snapshot.
--
-- job gains judging_mode/judging_deadline/finished_at. judging_started_at
-- already exists (migration 005).

PRAGMA foreign_keys = OFF;

CREATE TABLE requirement_new (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  job_id INTEGER NOT NULL REFERENCES job(id),
  text TEXT NOT NULL,
  weight TEXT NOT NULL CHECK(weight IN ('high','medium','low')),
  source TEXT NOT NULL CHECK(source IN ('extracted','user')),
  status TEXT NOT NULL CHECK(status IN ('pending','done')),
  reason TEXT,
  last_error TEXT NULL,
  sort_order INTEGER NOT NULL,
  deleted INTEGER NOT NULL DEFAULT 0,
  judged_at TEXT NULL,
  judge_seconds REAL NULL,
  embed_seconds REAL NULL
);
INSERT INTO requirement_new
  (id, job_id, text, weight, source, status, reason, last_error, sort_order, deleted,
   judged_at, judge_seconds, embed_seconds)
SELECT
  id, job_id, text, weight, source,
  CASE WHEN status IN ('queued', 'judging', 'error') THEN 'pending' ELSE status END,
  reason,
  CASE WHEN status = 'error' THEN reason ELSE NULL END,
  sort_order, deleted, judged_at, judge_seconds, embed_seconds
FROM requirement;
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
  why TEXT NULL,
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
INSERT INTO judgment_new
  (id, requirement_id, unit_id, score, model_verdict, user_verdict, added_by_user, why, created_at)
SELECT id, requirement_id, unit_id, score, model_verdict, user_verdict, added_by_user, why, created_at
FROM judgment;
DROP TABLE judgment;
ALTER TABLE judgment_new RENAME TO judgment;

CREATE INDEX idx_requirement_job ON requirement(job_id);
CREATE INDEX idx_judgment_requirement ON judgment(requirement_id);
CREATE INDEX idx_judgment_unit ON judgment(unit_id);

ALTER TABLE job ADD COLUMN judging_mode TEXT NOT NULL DEFAULT 'auto' CHECK(judging_mode IN ('auto','manual'));
ALTER TABLE job ADD COLUMN judging_deadline TEXT NULL;
ALTER TABLE job ADD COLUMN finished_at TEXT NULL;

PRAGMA foreign_keys = ON;
