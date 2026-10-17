-- Reversible "discard" (distinct from unit.deleted, which has no restore
-- path and exists to keep old judgment rows resolvable). A set
-- discarded_at hides the row from shortlisting/judging/pairs/search and
-- from its list screen; clearing it (restore) brings it straight back --
-- nothing discarded is ever deleted.

ALTER TABLE role ADD COLUMN discarded_at TEXT NULL;
ALTER TABLE unit ADD COLUMN discarded_at TEXT NULL;
ALTER TABLE job ADD COLUMN discarded_at TEXT NULL;
