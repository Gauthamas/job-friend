-- Thread discovery had no stored duration, unlike extraction
-- (job.extraction_seconds) and judging (run_timing). Stores the same way:
-- a per-run total on thread_run, plus a 'threads' row in run_timing for
-- the rolling "typically ~Xs" average the other phases already get.

ALTER TABLE thread_run ADD COLUMN seconds_total REAL NULL;
