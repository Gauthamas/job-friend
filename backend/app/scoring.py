import sqlite3

from app.embeddings import QUERY_PREFIX
from app.llm.embedding_client import EmbeddingClient
from app.vectors import cosine_similarity, from_blob


def score_units_by_similarity(
    conn: sqlite3.Connection,
    inventory_id: int,
    query_text: str,
    embedding_client: EmbeddingClient,
) -> dict[int, float]:
    """Embeds query_text once and scores every non-deleted unit in the
    inventory by the MAX cosine similarity across that unit's embedded
    fields (§5 — not the average). Shared by unit search and judge
    shortlisting so both use the exact same scoring rule.

    Returns {unit_id: score}, 0.0 for any unit with no embedded fields at
    all. Caller is responsible for calling embed_missing_units() first if
    it wants guaranteed coverage."""
    unit_ids = [
        row["id"]
        for row in conn.execute(
            "SELECT u.id FROM unit u JOIN role r ON u.role_id = r.id "
            "WHERE r.inventory_id = ? AND u.deleted = 0",
            (inventory_id,),
        )
    ]
    scores = {unit_id: 0.0 for unit_id in unit_ids}
    if not unit_ids or not query_text.strip():
        return scores

    [query_vector] = embedding_client.embed([QUERY_PREFIX + query_text])
    embedding_rows = conn.execute(
        "SELECT ue.unit_id, ue.vector FROM unit_embedding ue "
        "JOIN unit u ON ue.unit_id = u.id JOIN role r ON u.role_id = r.id "
        "WHERE r.inventory_id = ? AND u.deleted = 0",
        (inventory_id,),
    ).fetchall()
    for row in embedding_rows:
        similarity = cosine_similarity(query_vector, from_blob(row["vector"]))
        if similarity > scores[row["unit_id"]]:
            scores[row["unit_id"]] = similarity

    return scores
