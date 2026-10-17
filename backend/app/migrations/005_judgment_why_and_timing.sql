-- Per-unit "why" (added to the judge's output schema to fix the
-- verdict-before-reasoning ordering bug) was never persisted -- only used
-- transiently during judging. The review UI needs it visible per judgment
-- without digging into logs.
--
-- Timing columns: the queue worker already logs per-call LLM timing
-- (app/llm/runner.py); these columns persist just enough of that so the
-- review UI can show extraction time / time-to-first-row / total judging
-- time and have it survive a page refresh, without the frontend having to
-- run its own stopwatch across SSE reconnects.

ALTER TABLE judgment ADD COLUMN why TEXT NULL;

ALTER TABLE job ADD COLUMN extraction_seconds REAL NULL;
ALTER TABLE job ADD COLUMN judging_started_at TEXT NULL;

ALTER TABLE requirement ADD COLUMN judged_at TEXT NULL;
ALTER TABLE requirement ADD COLUMN judge_seconds REAL NULL;
