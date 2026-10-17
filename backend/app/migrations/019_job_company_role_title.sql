-- Two optional, user-typed fields on a job: the target company and role
-- title. Shown next to the JD box; used only to seed the writing view's
-- default greeting when company is set. No extraction, no model call.

ALTER TABLE job ADD COLUMN company TEXT NULL;
ALTER TABLE job ADD COLUMN role_title TEXT NULL;
