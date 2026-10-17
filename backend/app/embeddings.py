import json
import logging
import sqlite3

from app.config import settings
from app.llm.embedding_client import EmbeddingClient
from app.vectors import to_blob

logger = logging.getLogger("job_friend.embeddings")

DOCUMENT_PREFIX = "search_document: "
QUERY_PREFIX = "search_query: "


def skills_text_from_json(skills_json: str | None) -> str | None:
    """skills_json holds a JSON array of tags (e.g. '["Python", "Kubernetes"]');
    this is what actually gets embedded for the "skills" field — the tags
    joined into one string. Returns None for empty/missing/malformed input."""
    if not skills_json:
        return None
    try:
        tags = json.loads(skills_json)
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(tags, list) or not tags:
        return None
    return ", ".join(str(tag) for tag in tags)


def _fields_to_embed(unit_row: sqlite3.Row) -> dict[str, str]:
    """text is always embedded; the enrichment fields (incl. skills, joined
    from skills_json) only when non-empty."""
    fields = {"text": unit_row["text"]}
    for field in ("context", "contribution", "outcome"):
        value = unit_row[field]
        if value:
            fields[field] = value
    skills = skills_text_from_json(unit_row["skills_json"])
    if skills:
        fields["skills"] = skills
    return fields


def embed_units(conn: sqlite3.Connection, unit_ids: list[int], embedding_client: EmbeddingClient) -> None:
    """Embed every applicable field of the given units under the currently
    configured model. Called right after a fresh commit. Never raises — a
    transient embedding failure shouldn't undo an already-saved commit;
    embed_missing_units() below is the backstop that catches it up later."""
    entries: list[tuple[int, str, str]] = []
    for unit_id in unit_ids:
        row = conn.execute("SELECT * FROM unit WHERE id = ?", (unit_id,)).fetchone()
        if row is None:
            continue
        entries.extend((unit_id, field, text) for field, text in _fields_to_embed(row).items())
    _write_vectors(conn, entries, embedding_client)


def embed_missing_units(conn: sqlite3.Connection, inventory_id: int, embedding_client: EmbeddingClient) -> None:
    """Ensure every non-deleted unit in this inventory has a vector for
    every applicable field under the currently configured model. Call this
    before any search or shortlist, so a save-time embedding failure (or a
    changed embed_model since the unit was last embedded) doesn't silently
    degrade results — it's caught up on demand instead."""
    model = settings.embed_model
    unit_ids = [
        row["id"]
        for row in conn.execute(
            "SELECT u.id FROM unit u JOIN role r ON u.role_id = r.id "
            "WHERE r.inventory_id = ? AND u.deleted = 0",
            (inventory_id,),
        )
    ]

    entries: list[tuple[int, str, str]] = []
    for unit_id in unit_ids:
        row = conn.execute("SELECT * FROM unit WHERE id = ?", (unit_id,)).fetchone()
        if row is None:
            continue
        for field, text in _fields_to_embed(row).items():
            already_embedded = conn.execute(
                "SELECT 1 FROM unit_embedding WHERE unit_id = ? AND field = ? AND model = ?",
                (unit_id, field, model),
            ).fetchone()
            if not already_embedded:
                entries.append((unit_id, field, text))
    _write_vectors(conn, entries, embedding_client)


def embed_unit_fields(
    conn: sqlite3.Connection, unit_id: int, fields: dict[str, str | None], embedding_client: EmbeddingClient
) -> None:
    """Re-embed exactly the given fields of one unit — used after an edit,
    split, or merge that changed specific field values (per §5: "re-embed a
    unit's fields whenever they change"). A field whose new value is empty
    or None (treated the same) has its existing vector deleted instead of
    left stale — otherwise a cleared field keeps matching searches against
    text that's no longer there."""
    model = settings.embed_model
    to_embed: list[tuple[int, str, str]] = []
    for field, text in fields.items():
        if text:
            to_embed.append((unit_id, field, text))
        else:
            conn.execute(
                "DELETE FROM unit_embedding WHERE unit_id = ? AND field = ? AND model = ?",
                (unit_id, field, model),
            )
    conn.commit()
    _write_vectors(conn, to_embed, embedding_client)


def _write_vectors(
    conn: sqlite3.Connection,
    entries: list[tuple[int, str, str]],
    embedding_client: EmbeddingClient,
) -> None:
    """entries: (unit_id, field, raw_text). Embeds and upserts. Never
    raises — logs a clear warning and leaves the affected vectors stale
    instead, so a caller (commit, a PATCH) can still complete successfully."""
    if not entries:
        return

    model = settings.embed_model
    try:
        vectors = embedding_client.embed([DOCUMENT_PREFIX + text for _, _, text in entries])
    except Exception:
        logger.warning(
            "EMBEDDING FAILED: could not embed %d field(s) with model=%s; "
            "affected units will be missing/stale in similarity search until re-embedded",
            len(entries), model, exc_info=True,
        )
        return

    for (unit_id, field, _), vector in zip(entries, vectors):
        conn.execute(
            "INSERT INTO unit_embedding (unit_id, field, model, vector) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(unit_id, field, model) DO UPDATE SET vector = excluded.vector",
            (unit_id, field, model, to_blob(vector)),
        )
    conn.commit()
