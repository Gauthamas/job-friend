-- Units are never hard-deleted once saved: a delete sets deleted=1, and a
-- merge sets deleted=1 + merged_into on the losing unit while the surviving
-- unit keeps its own id with the combined text. This keeps old judgment
-- rows resolvable (unit_id still points at a real row) and their frozen
-- unit_snapshot untouched, per "past maps survive later edits."
--
-- Simple ADD COLUMN suffices here (unlike 002's AUTOINCREMENT change) since
-- both columns are nullable/defaulted, not part of the primary key.

ALTER TABLE unit ADD COLUMN deleted INTEGER NOT NULL DEFAULT 0;
ALTER TABLE unit ADD COLUMN merged_into INTEGER REFERENCES unit(id);
