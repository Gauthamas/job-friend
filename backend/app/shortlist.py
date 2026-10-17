import json
import sqlite3
from dataclasses import dataclass

from app.embeddings import embed_missing_units
from app.llm.embedding_client import EmbeddingClient
from app.scoring import score_units_by_similarity


@dataclass
class Candidate:
    unit_id: int
    text: str
    context: str | None
    contribution: str | None
    outcome: str | None
    skills: list[str]
    score: float


def shortlist_units(
    conn: sqlite3.Connection,
    inventory_id: int,
    requirement_text: str,
    embedding_client: EmbeddingClient,
    top_k: int,
) -> list[Candidate]:
    """Top-k units by max-cosine-similarity-across-fields (§5), with full
    enrichment (context/contribution/outcome/skills) attached — this is
    what the judge actually sees, not just id+text."""
    embed_missing_units(conn, inventory_id, embedding_client)
    scores = score_units_by_similarity(conn, inventory_id, requirement_text, embedding_client)
    if not scores:
        return []

    units = conn.execute(
        "SELECT u.id, u.text, u.context, u.contribution, u.outcome, u.skills_json "
        "FROM unit u JOIN role r ON u.role_id = r.id "
        "WHERE r.inventory_id = ? AND u.deleted = 0 "
        "AND u.discarded_at IS NULL AND r.discarded_at IS NULL",
        (inventory_id,),
    ).fetchall()

    ranked = sorted(units, key=lambda row: -scores[row["id"]])[:top_k]

    return [
        Candidate(
            unit_id=row["id"],
            text=row["text"],
            context=row["context"],
            contribution=row["contribution"],
            outcome=row["outcome"],
            skills=_parse_skills(row["skills_json"]),
            score=scores[row["id"]],
        )
        for row in ranked
    ]


def _parse_skills(skills_json: str | None) -> list[str]:
    if not skills_json:
        return []
    try:
        tags = json.loads(skills_json)
    except (json.JSONDecodeError, TypeError):
        return []
    return [str(t) for t in tags] if isinstance(tags, list) else []
