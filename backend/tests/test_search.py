from app.embeddings import embed_units
from app.search import search_units


def setup_inventory(db):
    db.execute("INSERT INTO profile (name) VALUES ('p')")
    db.execute("INSERT INTO inventory (profile_id, name) VALUES (1, 'inv')")
    db.execute("INSERT INTO role (inventory_id, company, title, sort_order) VALUES (1, 'Acme', 'Eng', 0)")
    db.commit()


def insert_unit(db, unit_id_hint, text, context=None):
    db.execute(
        "INSERT INTO unit (role_id, text, source, sort_order, context) VALUES (1, ?, 'manual', ?, ?)",
        (text, unit_id_hint, context),
    )
    db.commit()
    return db.execute("SELECT id FROM unit ORDER BY id DESC LIMIT 1").fetchone()["id"]


def test_substring_match_is_found(db, mock_embedder):
    setup_inventory(db)
    unit_id = insert_unit(db, 0, "Led a crash-rate reduction project")
    embed_units(db, [unit_id], mock_embedder)

    results = search_units(db, inventory_id=1, query="crash-rate", embedding_client=mock_embedder)

    assert any(r.unit_id == unit_id and r.matched_substring for r in results)


def test_embedding_match_ranks_by_similarity(db, mock_embedder):
    setup_inventory(db)
    close_id = insert_unit(db, 0, "close match unit")
    far_id = insert_unit(db, 1, "far match unit")

    mock_embedder.set_vector("search_document: close match unit", [1, 0, 0])
    mock_embedder.set_vector("search_document: far match unit", [0, 1, 0])
    mock_embedder.set_vector("search_query: something", [0.9, 0.1, 0])

    embed_units(db, [close_id, far_id], mock_embedder)

    results = search_units(db, inventory_id=1, query="something", embedding_client=mock_embedder)

    result_ids = [r.unit_id for r in results]
    assert result_ids.index(close_id) < result_ids.index(far_id)


def test_max_over_fields_scoring(db, mock_embedder):
    setup_inventory(db)
    unit_id = insert_unit(db, 0, "irrelevant text", context="highly relevant context")

    mock_embedder.set_vector("search_document: irrelevant text", [0, 1, 0])
    mock_embedder.set_vector("search_document: highly relevant context", [1, 0, 0])
    mock_embedder.set_vector("search_query: query", [1, 0, 0])

    embed_units(db, [unit_id], mock_embedder)
    results = search_units(db, inventory_id=1, query="query", embedding_client=mock_embedder)

    result = next(r for r in results if r.unit_id == unit_id)
    assert result.score > 0.9  # took the context field's score, not the text field's


def test_unit_matching_both_substring_and_embedding_appears_once(db, mock_embedder):
    setup_inventory(db)
    unit_id = insert_unit(db, 0, "distinctive keyword phrase")
    embed_units(db, [unit_id], mock_embedder)

    results = search_units(db, inventory_id=1, query="distinctive", embedding_client=mock_embedder)

    matches = [r for r in results if r.unit_id == unit_id]
    assert len(matches) == 1


def test_search_embeds_units_missing_a_vector_before_scoring(db, mock_embedder):
    setup_inventory(db)
    unit_id = insert_unit(db, 0, "never embedded yet")
    # Deliberately not calling embed_units — simulates a save-time failure.

    results = search_units(db, inventory_id=1, query="never embedded yet", embedding_client=mock_embedder)

    assert any(r.unit_id == unit_id for r in results)
    count = db.execute("SELECT COUNT(*) AS c FROM unit_embedding WHERE unit_id = ?", (unit_id,)).fetchone()["c"]
    assert count == 1


def test_soft_deleted_units_are_excluded(db, mock_embedder):
    setup_inventory(db)
    unit_id = insert_unit(db, 0, "deleted unit text")
    embed_units(db, [unit_id], mock_embedder)
    db.execute("UPDATE unit SET deleted = 1 WHERE id = ?", (unit_id,))
    db.commit()

    results = search_units(db, inventory_id=1, query="deleted unit", embedding_client=mock_embedder)

    assert all(r.unit_id != unit_id for r in results)
