-- History of extraction/judging call timing, for the review UI's "typically
-- ~Xs" estimates (not derivable from requirement/job rows alone, since
-- those only ever hold the most recent run, not a history).

CREATE TABLE run_timing (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  phase TEXT NOT NULL CHECK(phase IN ('extraction', 'judging')),
  mode TEXT CHECK(mode IN ('single', 'batch')),   -- NULL for extraction (always one call)
  model TEXT NOT NULL,
  thinking INTEGER NOT NULL,                       -- 0/1
  prompt_version TEXT NOT NULL,
  batch_size INTEGER,                              -- NULL unless mode = 'batch'
  items INTEGER NOT NULL,                          -- requirements extracted, or judged in this run
  seconds_to_first_result REAL,                    -- NULL for extraction (one call, no "first" sub-unit)
  seconds_total REAL NOT NULL,
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
