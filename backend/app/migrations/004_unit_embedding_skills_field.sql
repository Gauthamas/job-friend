-- Adds "skills" to unit_embedding.field's allowed values, so a unit's
-- skills_json tags can be embedded and take part in similarity search
-- alongside text/context/contribution/outcome. CHECK constraints are part
-- of a column's definition in SQLite, so widening one means recreating the
-- table (same pattern as 002_autoincrement_ids.sql), not an ALTER.

PRAGMA foreign_keys = OFF;

CREATE TABLE unit_embedding_new (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  unit_id INTEGER NOT NULL REFERENCES unit(id),
  field TEXT NOT NULL CHECK(field IN ('text','context','contribution','outcome','skills')),
  model TEXT NOT NULL,
  vector BLOB NOT NULL,
  UNIQUE(unit_id, field, model)
);
INSERT INTO unit_embedding_new SELECT * FROM unit_embedding;
DROP TABLE unit_embedding;
ALTER TABLE unit_embedding_new RENAME TO unit_embedding;

CREATE INDEX idx_unit_embedding_unit ON unit_embedding(unit_id);

PRAGMA foreign_keys = ON;
