import sqlite3

from fastapi import APIRouter, Depends, HTTPException

from app.api_schemas import AddUnitRequest, RoleOut, UnitOut
from app.deps import get_db, get_embedding_client
from app.embeddings import embed_units
from app.judging import ensure_model_not_busy
from app.llm.embedding_client import EmbeddingClient

router = APIRouter(prefix="/api/roles", tags=["roles"])


def _fetch_role(conn: sqlite3.Connection, role_id: int) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM role WHERE id = ?", (role_id,)).fetchone()
    if not row:
        raise HTTPException(404, "Role not found")
    return row


def _role_out(row: sqlite3.Row) -> RoleOut:
    return RoleOut(
        id=row["id"], inventory_id=row["inventory_id"], company=row["company"], title=row["title"],
        start_date=row["start_date"], end_date=row["end_date"], sort_order=row["sort_order"],
        discarded_at=row["discarded_at"],
    )


@router.post("/{role_id}/units", response_model=UnitOut, status_code=201)
def add_unit(
    role_id: int,
    body: AddUnitRequest,
    conn: sqlite3.Connection = Depends(get_db),
    embedding_client: EmbeddingClient = Depends(get_embedding_client),
):
    role = conn.execute("SELECT id FROM role WHERE id = ?", (role_id,)).fetchone()
    if not role:
        raise HTTPException(404, "Role not found")
    ensure_model_not_busy(conn)

    max_sort_order = conn.execute(
        "SELECT MAX(sort_order) AS m FROM unit WHERE role_id = ?", (role_id,)
    ).fetchone()["m"]
    sort_order = (max_sort_order + 1) if max_sort_order is not None else 0

    cursor = conn.execute(
        "INSERT INTO unit (role_id, text, source, sort_order, context, contribution, outcome, skills_json) "
        "VALUES (?, ?, 'manual', ?, ?, ?, ?, ?)",
        (role_id, body.text, sort_order, body.context, body.contribution, body.outcome, body.skills_json),
    )
    unit_id = cursor.lastrowid
    conn.commit()

    embed_units(conn, [unit_id], embedding_client)

    row = conn.execute("SELECT * FROM unit WHERE id = ?", (unit_id,)).fetchone()
    return UnitOut(
        id=row["id"], role_id=row["role_id"], text=row["text"], source=row["source"],
        sort_order=row["sort_order"], context=row["context"], contribution=row["contribution"],
        outcome=row["outcome"], skills_json=row["skills_json"],
    )


@router.post("/{role_id}/discard", response_model=RoleOut)
def discard_role(role_id: int, conn: sqlite3.Connection = Depends(get_db)):
    """Reversible: hides the role and cascades to all its (non-deleted)
    units, same as the role itself, excluded from shortlisting/judging/
    pairs/search going forward. Restoring the role restores its units too
    -- nothing here is deleted."""
    _fetch_role(conn, role_id)
    conn.execute("UPDATE role SET discarded_at = datetime('now') WHERE id = ?", (role_id,))
    conn.execute(
        "UPDATE unit SET discarded_at = datetime('now') WHERE role_id = ? AND deleted = 0", (role_id,),
    )
    conn.commit()
    return _role_out(_fetch_role(conn, role_id))


@router.post("/{role_id}/restore", response_model=RoleOut)
def restore_role(role_id: int, conn: sqlite3.Connection = Depends(get_db)):
    _fetch_role(conn, role_id)
    conn.execute("UPDATE role SET discarded_at = NULL WHERE id = ?", (role_id,))
    conn.execute("UPDATE unit SET discarded_at = NULL WHERE role_id = ? AND deleted = 0", (role_id,))
    conn.commit()
    return _role_out(_fetch_role(conn, role_id))
