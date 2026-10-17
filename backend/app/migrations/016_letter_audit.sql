-- Milestone: letter audit. ADD COLUMN only --
-- wiped along with the rest of the letter row on JD resubmit, same as
-- every other letter field (app/judging.py's wipe_job_requirements).
ALTER TABLE letter ADD COLUMN audit_json TEXT NULL;
ALTER TABLE letter ADD COLUMN audit_at TEXT NULL;
