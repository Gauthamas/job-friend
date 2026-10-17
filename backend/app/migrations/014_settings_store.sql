-- Milestone 7 part A: key/value overrides for editable settings. Defaults
-- stay in code (app/config.py); a row here overrides its key at startup.
CREATE TABLE app_setting (
  key TEXT PRIMARY KEY,
  value_json TEXT NOT NULL,
  updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);
