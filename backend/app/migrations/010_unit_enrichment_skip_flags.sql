-- Milestone 2: enrichment screen. A unit's three
-- enrichment fields (context/contribution/outcome, already existing columns)
-- are each either filled in or explicitly marked "nothing to add" -- a flag,
-- not text, so a unit can be complete without fabricating an answer.
--
-- Plain ADD COLUMN only, per the standing rule (see 009's comment): no table
-- rebuild, no risk of cascading child-row deletes inside db.py's one-
-- transaction migrate().

ALTER TABLE unit ADD COLUMN context_skipped INTEGER NOT NULL DEFAULT 0;
ALTER TABLE unit ADD COLUMN contribution_skipped INTEGER NOT NULL DEFAULT 0;
ALTER TABLE unit ADD COLUMN outcome_skipped INTEGER NOT NULL DEFAULT 0;
