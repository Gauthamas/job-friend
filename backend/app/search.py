import sqlite3
from dataclasses import dataclass

from app.embeddings import embed_missing_units
from app.llm.embedding_client import EmbeddingClient
from app.scoring import score_units_by_similarity


@dataclass
class UnitSearchResult:
    unit_id: int
    role_id: int
    company: str
    title: str
    text: str
    context: str | None
    contribution: str | None
    outcome: str | None
    score: float
    matched_substring: bool


def search_units(
    conn: sqlite3.Connection,
    inventory_id: int,
    query: str,
    embedding_client: EmbeddingClient,
    limit: int = 10,
) -> list[UnitSearchResult]:
    # Backstop: a unit could be missing a vector because embedding failed at
    # save time, or because embed_model changed since it was last embedded.
    # Catch it up before scoring so search coverage is always complete.
    embed_missing_units(conn, inventory_id, embedding_client)

    units = conn.execute(
        "SELECT u.id, u.role_id, u.text, u.context, u.contribution, u.outcome, r.company, r.title "
        "FROM unit u JOIN role r ON u.role_id = r.id "
        "WHERE r.inventory_id = ? AND u.deleted = 0 "
        "AND u.discarded_at IS NULL AND r.discarded_at IS NULL",
        (inventory_id,),
    ).fetchall()
    if not units:
        return []

    query_lower = query.lower()
    substring_matches = {
        row["id"] for row in units if query_lower and query_lower in row["text"].lower()
    }

    scores = score_units_by_similarity(conn, inventory_id, query, embedding_client)

    ranked = sorted(
        units,
        key=lambda row: (row["id"] not in substring_matches, -scores[row["id"]]),
    )

    return [
        UnitSearchResult(
            unit_id=row["id"], role_id=row["role_id"], company=row["company"], title=row["title"],
            text=row["text"], context=row["context"], contribution=row["contribution"], outcome=row["outcome"],
            score=scores[row["id"]], matched_substring=row["id"] in substring_matches,
        )
        for row in ranked[:limit]
    ]
