import sqlite3

from fastapi import APIRouter, Depends, HTTPException

from app.api_schemas import StatementOut, StatementPatchRequest
from app.deps import get_db
from app.threads import mark_threads_stale_for_statement

router = APIRouter(prefix="/api/statements", tags=["statements"])


def _fetch_statement_with_source(conn: sqlite3.Connection, statement_id: int) -> sqlite3.Row:
    row = conn.execute(
        "SELECT s.id AS statement_id, s.status, s.text, s.confirmed, s.autofilled_from_job_id, "
        "src.title AS autofilled_from_job_title, src.created_at AS autofilled_from_date "
        "FROM statement s LEFT JOIN job src ON src.id = s.autofilled_from_job_id "
        "WHERE s.id = ?",
        (statement_id,),
    ).fetchone()
    if not row:
        raise HTTPException(404, "Statement not found")
    return row


def _to_out(row: sqlite3.Row) -> StatementOut:
    return StatementOut(
        id=row["statement_id"], status=row["status"], text=row["text"],
        autofilled_from_job_id=row["autofilled_from_job_id"],
        autofilled_from_job_title=row["autofilled_from_job_title"],
        autofilled_from_date=row["autofilled_from_date"],
        confirmed=bool(row["confirmed"]),
    )


@router.patch("/{statement_id}", response_model=StatementOut)
def patch_statement(statement_id: int, body: StatementPatchRequest, conn: sqlite3.Connection = Depends(get_db)):
    """§6: "What do these two have in common?" -- written as-is, no model
    call, no check on content. The autofilled-from chip is shown "until
    the user edits or confirms" a statement -- editing one here ends that,
    same as Confirm all does, so the autofill marker and the unconfirmed
    state both clear on any edit."""
    _fetch_statement_with_source(conn, statement_id)

    text = body.text if body.status == "written" else None
    conn.execute(
        "UPDATE statement SET status = ?, text = ?, confirmed = 1, autofilled_from_job_id = NULL, "
        "updated_at = datetime('now') WHERE id = ?",
        (body.status, text, statement_id),
    )
    # §7: editing a statement makes any thread built from it stale.
    mark_threads_stale_for_statement(conn, statement_id)
    conn.commit()
    return _to_out(_fetch_statement_with_source(conn, statement_id))
