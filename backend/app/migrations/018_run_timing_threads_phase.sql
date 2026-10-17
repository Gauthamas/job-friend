-- Widens run_timing.phase to accept 'threads' (thread discovery now
-- records its total duration the same way extraction/judging do). CHECK
-- constraints are part of a column's definition in SQLite, so widening
-- one means recreating the table (same pattern as
-- 004_unit_embedding_skills_field.sql), not an ALTER.

PRAGMA foreign_keys = OFF;

CREATE TABLE run_timing_new (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  phase TEXT NOT NULL CHECK(phase IN ('extraction', 'judging', 'threads')),
  mode TEXT CHECK(mode IN ('single', 'batch')),
  model TEXT NOT NULL,
  thinking INTEGER NOT NULL,
  prompt_version TEXT NOT NULL,
  batch_size INTEGER,
  items INTEGER NOT NULL,
  seconds_to_first_result REAL,
  seconds_total REAL NOT NULL,
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
INSERT INTO run_timing_new SELECT * FROM run_timing;
DROP TABLE run_timing;
ALTER TABLE run_timing_new RENAME TO run_timing;

PRAGMA foreign_keys = ON;
