-- Milestone 6: the writing view's
-- letter row. One per job. sections_json is keyed by section key
-- (requirement id as a string, "open", "weak", "gaps", "close"):
-- {"text": str, "pointers_edited": str|null, "skipped": bool}.

CREATE TABLE letter (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  job_id INTEGER NOT NULL UNIQUE REFERENCES job(id),
  sections_json TEXT NOT NULL DEFAULT '{}',
  assembled_text TEXT NULL,
  greeting TEXT NULL,
  signoff TEXT NULL,
  finished INTEGER NOT NULL DEFAULT 0,
  updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);
