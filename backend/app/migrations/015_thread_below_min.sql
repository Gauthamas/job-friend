-- Milestone 7 part B: threads under min_support are kept, flagged, instead
-- of dropped. Existing rows default to 0 (unaffected -- they were already
-- the only kind of thread that got persisted before this change).
ALTER TABLE thread ADD COLUMN below_min INTEGER NOT NULL DEFAULT 0;

-- Part C point 11: per-run statement counts, for a benchmark to read later.
ALTER TABLE thread_run ADD COLUMN proposed_count INTEGER NULL;
ALTER TABLE thread_run ADD COLUMN moved_count INTEGER NULL;
ALTER TABLE thread_run ADD COLUMN removed_count INTEGER NULL;
