import sqlite3

from fastapi import APIRouter, Depends, HTTPException

from app.api_schemas import (
    MergeUnitsRequest,
    MergeUnitsResponse,
    SplitUnitRequest,
    SplitUnitResponse,
    UnitOut,
    UnitPatchRequest,
)
from app.deps import get_db, get_embedding_client
from app.embeddings import embed_unit_fields, skills_text_from_json
from app.judging import ensure_model_not_busy
from app.llm.embedding_client import EmbeddingClient

router = APIRouter(prefix="/api/units", tags=["units"])

_EDITABLE_TEXT_FIELDS = ("text", "context", "contribution", "outcome")


def _fetch_unit(conn: sqlite3.Connection, unit_id: int) -> sqlite3.Row:
    row = conn.execute(
        "SELECT * FROM unit WHERE id = ? AND deleted = 0", (unit_id,)
    ).fetchone()
    if not row:
        raise HTTPException(404, "Unit not found")
    return row


def _to_unit_out(row: sqlite3.Row) -> UnitOut:
    return UnitOut(
        id=row["id"], role_id=row["role_id"], text=row["text"], source=row["source"],
        sort_order=row["sort_order"], context=row["context"], contribution=row["contribution"],
        outcome=row["outcome"], skills_json=row["skills_json"],
        context_skipped=bool(row["context_skipped"]), contribution_skipped=bool(row["contribution_skipped"]),
        outcome_skipped=bool(row["outcome_skipped"]), discarded_at=row["discarded_at"],
    )


@router.get("/{unit_id}", response_model=UnitOut)
def get_unit(unit_id: int, conn: sqlite3.Connection = Depends(get_db)):
    return _to_unit_out(_fetch_unit(conn, unit_id))


@router.patch("/{unit_id}", response_model=UnitOut)
def patch_unit(
    unit_id: int,
    body: UnitPatchRequest,
    conn: sqlite3.Connection = Depends(get_db),
    embedding_client: EmbeddingClient = Depends(get_embedding_client),
):
    row = _fetch_unit(conn, unit_id)
    ensure_model_not_busy(conn)

    # model_fields_set (not "value is not None") distinguishes "field
    # omitted from the request" from "field explicitly set to null" — the
    # latter must go through, or a field (e.g. clearing the last skill tag)
    # could never be cleared once set.
    provided = body.model_fields_set
    if "text" in provided and not body.text:
        raise HTTPException(400, "text cannot be empty")

    updates: dict[str, str | int] = {}
    for field in ("text", "context", "contribution", "outcome", "skills_json"):
        if field not in provided:
            continue
        value = getattr(body, field)
        if value != row[field]:
            updates[field] = value

    # §5: per-field "nothing to add" flags -- plain booleans, never
    # embedded, so they're applied independently of the text fields above.
    for field in ("context_skipped", "contribution_skipped", "outcome_skipped"):
        if field not in provided:
            continue
        value = int(getattr(body, field))
        if value != row[field]:
            updates[field] = value

    if updates:
        set_clause = ", ".join(f"{field} = ?" for field in updates)
        conn.execute(
            f"UPDATE unit SET {set_clause}, updated_at = datetime('now') WHERE id = ?",
            (*updates.values(), unit_id),
        )
        conn.commit()

    # Pass through cleared fields (None/"") too, not just truthy ones —
    # embed_unit_fields deletes the stale vector for those instead of
    # silently leaving it (and the unit still scoring on old text/tags).
    changed_embeddable: dict[str, str | None] = {f: v for f, v in updates.items() if f in _EDITABLE_TEXT_FIELDS}
    if "skills_json" in updates:
        changed_embeddable["skills"] = skills_text_from_json(updates["skills_json"])
    if changed_embeddable:
        embed_unit_fields(conn, unit_id, changed_embeddable, embedding_client)

    return _to_unit_out(_fetch_unit(conn, unit_id))


@router.delete("/{unit_id}", status_code=204)
def delete_unit(unit_id: int, conn: sqlite3.Connection = Depends(get_db)):
    _fetch_unit(conn, unit_id)  # 404 if missing/already deleted
    conn.execute("UPDATE unit SET deleted = 1 WHERE id = ?", (unit_id,))
    conn.commit()


@router.post("/{unit_id}/discard", response_model=UnitOut)
def discard_unit(unit_id: int, conn: sqlite3.Connection = Depends(get_db)):
    """Reversible, unlike delete above: excluded from shortlisting/
    judging/pairs/search going forward; nothing is removed, so restoring
    brings it straight back."""
    _fetch_unit(conn, unit_id)
    conn.execute("UPDATE unit SET discarded_at = datetime('now') WHERE id = ?", (unit_id,))
    conn.commit()
    return _to_unit_out(_fetch_unit(conn, unit_id))


@router.post("/{unit_id}/restore", response_model=UnitOut)
def restore_unit(unit_id: int, conn: sqlite3.Connection = Depends(get_db)):
    _fetch_unit(conn, unit_id)
    conn.execute("UPDATE unit SET discarded_at = NULL WHERE id = ?", (unit_id,))
    conn.commit()
    return _to_unit_out(_fetch_unit(conn, unit_id))


@router.post("/{unit_id}/split", response_model=SplitUnitResponse)
def split_unit(
    unit_id: int,
    body: SplitUnitRequest,
    conn: sqlite3.Connection = Depends(get_db),
    embedding_client: EmbeddingClient = Depends(get_embedding_client),
):
    row = _fetch_unit(conn, unit_id)
    ensure_model_not_busy(conn)

    first = row["text"][: body.split_at].strip()
    second = row["text"][body.split_at :].strip()
    if not first or not second:
        raise HTTPException(400, "Split point must leave non-empty text on both sides")

    conn.execute("UPDATE unit SET text = ?, updated_at = datetime('now') WHERE id = ?", (first, unit_id))

    max_sort_order = conn.execute(
        "SELECT MAX(sort_order) AS m FROM unit WHERE role_id = ?", (row["role_id"],)
    ).fetchone()["m"] or 0
    cursor = conn.execute(
        "INSERT INTO unit (role_id, text, source, sort_order) VALUES (?, ?, ?, ?)",
        (row["role_id"], second, row["source"], max_sort_order + 1),
    )
    new_unit_id = cursor.lastrowid
    conn.commit()

    embed_unit_fields(conn, unit_id, {"text": first}, embedding_client)
    embed_unit_fields(conn, new_unit_id, {"text": second}, embedding_client)

    return SplitUnitResponse(
        original=_to_unit_out(_fetch_unit(conn, unit_id)),
        new_unit=_to_unit_out(_fetch_unit(conn, new_unit_id)),
    )


@router.post("/{unit_id}/merge", response_model=MergeUnitsResponse)
def merge_units(
    unit_id: int,
    body: MergeUnitsRequest,
    conn: sqlite3.Connection = Depends(get_db),
    embedding_client: EmbeddingClient = Depends(get_embedding_client),
):
    if unit_id == body.other_unit_id:
        raise HTTPException(400, "Cannot merge a unit with itself")

    target = _fetch_unit(conn, unit_id)  # the survivor — always the unit the user picked in the URL
    other = _fetch_unit(conn, body.other_unit_id)
    ensure_model_not_busy(conn)

    if target["role_id"] != other["role_id"]:
        raise HTTPException(400, "Units must belong to the same role to merge")

    combined_text = f"{target['text']} {other['text']}".strip()
    conn.execute(
        "UPDATE unit SET text = ?, source = 'manual', updated_at = datetime('now') WHERE id = ?",
        (combined_text, unit_id),
    )
    conn.execute(
        "UPDATE unit SET deleted = 1, merged_into = ? WHERE id = ?",
        (unit_id, body.other_unit_id),
    )
    conn.commit()

    embed_unit_fields(conn, unit_id, {"text": combined_text}, embedding_client)

    return MergeUnitsResponse(
        survivor=_to_unit_out(_fetch_unit(conn, unit_id)),
        merged_unit_id=body.other_unit_id,
    )
