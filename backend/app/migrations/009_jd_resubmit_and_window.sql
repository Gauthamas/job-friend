-- v2 draft 3: the JD screen and the single
-- fixed 20-minute judging window replace the per-job auto/manual choice.
--
-- Plain ADD COLUMN only -- no table rebuild. DROP TABLE as part of a
-- recreate-table migration can cascade-delete child rows when the whole
-- migration runs inside one transaction (db.py's migrate() does exactly
-- that), which is too risky for a routine column change. judging_mode is
-- dropped via ALTER TABLE ... DROP COLUMN instead (supported since SQLite
-- 3.35; this environment runs 3.50).

ALTER TABLE job ADD COLUMN jd_submitted_text TEXT NULL;
ALTER TABLE job ADD COLUMN jd_submitted_at TEXT NULL;
ALTER TABLE job ADD COLUMN extraction_error TEXT NULL;

ALTER TABLE job DROP COLUMN judging_mode;
