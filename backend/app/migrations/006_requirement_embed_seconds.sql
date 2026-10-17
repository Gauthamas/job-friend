-- judge_seconds (005) only measures the judge LLM call. This adds a
-- separate column for the shortlist/embedding step's own wall time, so the
-- two can be told apart per requirement (embedding vs. the LLM call).

ALTER TABLE requirement ADD COLUMN embed_seconds REAL NULL;
