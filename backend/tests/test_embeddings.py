import json

import numpy as np
import pytest

from app.config import settings
from app.embeddings import embed_missing_units, embed_unit_fields, embed_units, skills_text_from_json
from app.vectors import from_blob


def insert_unit(db, text="bullet text", context=None, contribution=None, outcome=None, skills_json=None):
    db.execute("INSERT INTO profile (name) VALUES ('p')")
    db.execute("INSERT INTO inventory (profile_id, name) VALUES (1, 'inv')")
    db.execute("INSERT INTO role (inventory_id, company, title, sort_order) VALUES (1, 'c', 't', 0)")
    db.execute(
        "INSERT INTO unit (role_id, text, source, sort_order, context, contribution, outcome, skills_json) "
        "VALUES (1, ?, 'manual', 0, ?, ?, ?, ?)",
        (text, context, contribution, outcome, skills_json),
    )
    db.commit()
    return db.execute("SELECT id FROM unit").fetchone()["id"]


def test_embeds_text_field_always(db, mock_embedder):
    unit_id = insert_unit(db)
    embed_units(db, [unit_id], mock_embedder)

    rows = db.execute("SELECT field, model FROM unit_embedding WHERE unit_id = ?", (unit_id,)).fetchall()
    assert [r["field"] for r in rows] == ["text"]
    assert rows[0]["model"] == settings.embed_model


def test_embeds_nonempty_enrichment_fields(db, mock_embedder):
    unit_id = insert_unit(db, context="ctx", contribution=None, outcome="out")
    embed_units(db, [unit_id], mock_embedder)

    fields = {r["field"] for r in db.execute("SELECT field FROM unit_embedding WHERE unit_id = ?", (unit_id,))}
    assert fields == {"text", "context", "outcome"}


def test_vectors_are_normalized(db, mock_embedder):
    unit_id = insert_unit(db)
    embed_units(db, [unit_id], mock_embedder)

    blob = db.execute(
        "SELECT vector FROM unit_embedding WHERE unit_id = ? AND field = 'text'", (unit_id,)
    ).fetchone()["vector"]
    vector = from_blob(blob)
    assert np.linalg.norm(vector) == pytest.approx(1.0, abs=1e-5)


def test_reembedding_upserts_not_duplicates(db, mock_embedder):
    unit_id = insert_unit(db)
    embed_units(db, [unit_id], mock_embedder)
    embed_units(db, [unit_id], mock_embedder)

    count = db.execute(
        "SELECT COUNT(*) AS c FROM unit_embedding WHERE unit_id = ? AND field = 'text'", (unit_id,)
    ).fetchone()["c"]
    assert count == 1


def test_document_prefix_is_applied(db, mock_embedder):
    unit_id = insert_unit(db, text="unique bullet phrase")
    mock_embedder.set_vector("search_document: unique bullet phrase", [1, 0, 0, 0])
    embed_units(db, [unit_id], mock_embedder)

    blob = db.execute(
        "SELECT vector FROM unit_embedding WHERE unit_id = ? AND field = 'text'", (unit_id,)
    ).fetchone()["vector"]
    vector = from_blob(blob)
    assert vector[0] == pytest.approx(1.0, abs=1e-5)


def test_embedding_failure_logs_warning_and_does_not_raise(db, mock_embedder, caplog):
    unit_id = insert_unit(db)

    class FailingEmbedder:
        def embed(self, texts):
            raise RuntimeError("LM Studio unreachable")

    with caplog.at_level("WARNING"):
        embed_units(db, [unit_id], FailingEmbedder())  # must not raise

    assert "EMBEDDING FAILED" in caplog.text
    count = db.execute("SELECT COUNT(*) AS c FROM unit_embedding").fetchone()["c"]
    assert count == 0


def test_embed_missing_units_skips_already_embedded(db, mock_embedder):
    unit_id = insert_unit(db)
    embed_units(db, [unit_id], mock_embedder)

    calls = []
    original_embed = mock_embedder.embed
    mock_embedder.embed = lambda texts: (calls.extend(texts), original_embed(texts))[1]

    embed_missing_units(db, inventory_id=1, embedding_client=mock_embedder)
    assert calls == []  # nothing missing, no embedding call made


def test_embed_missing_units_embeds_units_that_failed_at_save_time(db, mock_embedder):
    unit_id = insert_unit(db)
    # Simulate the save-time embed having failed: no unit_embedding rows exist.
    embed_missing_units(db, inventory_id=1, embedding_client=mock_embedder)

    rows = db.execute("SELECT field FROM unit_embedding WHERE unit_id = ?", (unit_id,)).fetchall()
    assert [r["field"] for r in rows] == ["text"]


def test_embed_missing_units_ignores_soft_deleted_units(db, mock_embedder):
    unit_id = insert_unit(db)
    db.execute("UPDATE unit SET deleted = 1 WHERE id = ?", (unit_id,))
    db.commit()

    embed_missing_units(db, inventory_id=1, embedding_client=mock_embedder)

    count = db.execute("SELECT COUNT(*) AS c FROM unit_embedding WHERE unit_id = ?", (unit_id,)).fetchone()["c"]
    assert count == 0


@pytest.mark.parametrize(
    "raw,expected",
    [
        (None, None),
        ("", None),
        ("not json", None),
        (json.dumps([]), None),
        (json.dumps("not a list"), None),
        (json.dumps(["Python"]), "Python"),
        (json.dumps(["Python", "Kubernetes"]), "Python, Kubernetes"),
    ],
)
def test_skills_text_from_json(raw, expected):
    assert skills_text_from_json(raw) == expected


def test_embeds_skills_field_when_present(db, mock_embedder):
    unit_id = insert_unit(db, skills_json=json.dumps(["Python", "SQL"]))
    embed_units(db, [unit_id], mock_embedder)

    fields = {r["field"] for r in db.execute("SELECT field FROM unit_embedding WHERE unit_id = ?", (unit_id,))}
    assert "skills" in fields


def test_skills_are_embedded_as_joined_tag_string(db, mock_embedder):
    unit_id = insert_unit(db, skills_json=json.dumps(["Python", "SQL"]))
    mock_embedder.set_vector("search_document: Python, SQL", [0, 0, 1, 0])
    embed_units(db, [unit_id], mock_embedder)

    blob = db.execute(
        "SELECT vector FROM unit_embedding WHERE unit_id = ? AND field = 'skills'", (unit_id,)
    ).fetchone()["vector"]
    vector = from_blob(blob)
    assert vector[2] == pytest.approx(1.0, abs=1e-5)


def test_no_skills_field_written_when_skills_json_empty(db, mock_embedder):
    unit_id = insert_unit(db, skills_json=None)
    embed_units(db, [unit_id], mock_embedder)

    fields = {r["field"] for r in db.execute("SELECT field FROM unit_embedding WHERE unit_id = ?", (unit_id,))}
    assert "skills" not in fields


@pytest.mark.parametrize("cleared_value", [None, ""])
@pytest.mark.parametrize("field", ["context", "contribution", "outcome", "skills"])
def test_clearing_a_field_deletes_its_vector_instead_of_leaving_it_stale(db, mock_embedder, field, cleared_value):
    unit_id = insert_unit(db)
    embed_unit_fields(db, unit_id, {field: "some value to embed"}, mock_embedder)
    assert db.execute(
        "SELECT 1 FROM unit_embedding WHERE unit_id = ? AND field = ?", (unit_id, field)
    ).fetchone() is not None

    embed_unit_fields(db, unit_id, {field: cleared_value}, mock_embedder)

    assert db.execute(
        "SELECT 1 FROM unit_embedding WHERE unit_id = ? AND field = ?", (unit_id, field)
    ).fetchone() is None


def test_cleared_field_no_longer_scores_in_search(db, mock_embedder):
    from app.search import search_units

    unit_id = insert_unit(db, text="irrelevant bullet")
    one_hot = [1.0] + [0.0] * 15  # match MockEmbeddingClient's 16-dim hash fallback
    mock_embedder.set_vector("search_document: has a sunday reference", one_hot)
    mock_embedder.set_vector("search_query: weekend", one_hot)
    embed_unit_fields(db, unit_id, {"context": "has a sunday reference"}, mock_embedder)

    before = search_units(db, inventory_id=1, query="weekend", embedding_client=mock_embedder)
    match_before = next(r for r in before if r.unit_id == unit_id)
    assert match_before.score == pytest.approx(1.0, abs=1e-5)

    db.execute("UPDATE unit SET context = NULL WHERE id = ?", (unit_id,))
    db.commit()
    embed_unit_fields(db, unit_id, {"context": None}, mock_embedder)

    after = search_units(db, inventory_id=1, query="weekend", embedding_client=mock_embedder)
    match_after = next(r for r in after if r.unit_id == unit_id)
    assert match_after.score < match_before.score
