import random
import sqlite3

from fastapi import APIRouter, Depends, HTTPException

from app.api_schemas import (
    AutofillResponse,
    BuildPairsResponse,
    PairOut,
    PairsListResponse,
    RemovedPairOut,
    StatementOut,
)
from app.deps import get_db
from app.judging import ensure_job_not_judging
from app.pairing import build_and_save_pairs
from app.routers.units import _to_unit_out
from app.statements import autofill_statements, confirm_all, reset_to_fresh

router = APIRouter(prefix="/api/jobs", tags=["pairs"])


def _fetch_job_or_404(conn: sqlite3.Connection, job_id: int) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM job WHERE id = ?", (job_id,)).fetchone()
    if not row:
        raise HTTPException(404, "Job not found")
    return row


def _statement_out(row: sqlite3.Row) -> StatementOut:
    return StatementOut(
        id=row["statement_id"], status=row["status"], text=row["text"],
        autofilled_from_job_id=row["autofilled_from_job_id"],
        autofilled_from_job_title=row["autofilled_from_job_title"],
        autofilled_from_date=row["autofilled_from_date"],
        confirmed=bool(row["confirmed"]),
    )


def _fetch_pairs_with_statements(conn: sqlite3.Connection, job_id: int) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT p.id AS pair_id, p.unit_a_id, p.unit_b_id, "
        "s.id AS statement_id, s.status, s.text, s.confirmed, s.autofilled_from_job_id, "
        "src.title AS autofilled_from_job_title, src.created_at AS autofilled_from_date "
        "FROM pair p "
        "JOIN statement s ON s.pair_id = p.id "
        "LEFT JOIN job src ON src.id = s.autofilled_from_job_id "
        "WHERE p.job_id = ? ORDER BY p.id",
        (job_id,),
    ).fetchall()


@router.post("/{job_id}/pairs/build", response_model=BuildPairsResponse)
def build_pairs(job_id: int, conn: sqlite3.Connection = Depends(get_db)):
    """§6: built when the user continues from the enrichment screen.
    Idempotent -- pairs still in the set keep their statements; pairs no
    longer in the set are removed (the caller surfaces a warning for any
    that had a written statement)."""
    _fetch_job_or_404(conn, job_id)
    ensure_job_not_judging(conn, job_id)

    removed = build_and_save_pairs(conn, job_id)
    pair_count = conn.execute("SELECT COUNT(*) AS n FROM pair WHERE job_id = ?", (job_id,)).fetchone()["n"]
    return BuildPairsResponse(
        pair_count=pair_count,
        removed=[RemovedPairOut(unit_a_id=r.unit_a_id, unit_b_id=r.unit_b_id, had_written_statement=r.had_written_statement) for r in removed],
    )


@router.get("/{job_id}/pairs", response_model=PairsListResponse)
def list_pairs(job_id: int, conn: sqlite3.Connection = Depends(get_db)):
    """§6: "pairs are shown in a stable shuffled order without scores" --
    shuffled with a seed derived from job_id, so the same job always
    produces the same order across requests."""
    _fetch_job_or_404(conn, job_id)

    rows = _fetch_pairs_with_statements(conn, job_id)
    unit_ids = {rid for row in rows for rid in (row["unit_a_id"], row["unit_b_id"])}
    units_by_id = {
        row["id"]: _to_unit_out(row)
        for row in conn.execute(
            f"SELECT * FROM unit WHERE id IN ({','.join('?' * len(unit_ids))})", tuple(unit_ids)
        ).fetchall()
    } if unit_ids else {}

    pairs = [
        PairOut(
            id=row["pair_id"], unit_a=units_by_id[row["unit_a_id"]], unit_b=units_by_id[row["unit_b_id"]],
            statement=_statement_out(row),
        )
        for row in rows
    ]
    random.Random(job_id).shuffle(pairs)

    all_ready = all(
        p.statement.status != "unanswered" and (p.statement.confirmed or p.statement.autofilled_from_job_id is None)
        for p in pairs
    )
    return PairsListResponse(pairs=pairs, all_ready=all_ready)


@router.post("/{job_id}/pairs/autofill", response_model=AutofillResponse)
def autofill(job_id: int, conn: sqlite3.Connection = Depends(get_db)):
    _fetch_job_or_404(conn, job_id)
    count = autofill_statements(conn, job_id)
    return AutofillResponse(autofilled_count=count)


@router.post("/{job_id}/pairs/fresh")
def start_fresh(job_id: int, conn: sqlite3.Connection = Depends(get_db)):
    _fetch_job_or_404(conn, job_id)
    reset_to_fresh(conn, job_id)
    return {"ok": True}


@router.post("/{job_id}/statements/confirm-all")
def confirm_all_statements(job_id: int, conn: sqlite3.Connection = Depends(get_db)):
    _fetch_job_or_404(conn, job_id)
    confirm_all(conn, job_id)
    return {"ok": True}
