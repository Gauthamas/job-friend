import sqlite3

from fastapi import APIRouter, Depends, HTTPException

from app.api_schemas import (
    ChooseThreadRequest,
    EnrichmentRequirementRef,
    PrimarySecondaryResponse,
    PrimarySecondarySlot,
    RankedThreadOut,
    ThreadUnitOut,
)
from app.config import settings
from app.deps import get_db
from app.routers.threads import _thread_statement_out
from app.routers.units import _to_unit_out
from app.thread_ranking import clear_choice, get_choice, rank_candidates, set_choice, suggest_and_persist

router = APIRouter(prefix="/api/jobs", tags=["primary-secondary"])


def _fetch_job_or_404(conn: sqlite3.Connection, job_id: int) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM job WHERE id = ?", (job_id,)).fetchone()
    if not row:
        raise HTTPException(404, "Job not found")
    return row


def _req_ref(row: sqlite3.Row) -> EnrichmentRequirementRef:
    return EnrichmentRequirementRef(id=row["id"], text=row["text"], weight=row["weight"])


def _ranked_out(conn: sqlite3.Connection, scored: dict) -> RankedThreadOut:
    t = scored["thread"]
    statements = conn.execute(
        "SELECT ts.origin, s.id AS statement_id, s.text FROM thread_statement ts "
        "JOIN statement s ON s.id = ts.statement_id WHERE ts.thread_id = ? ORDER BY ts.id",
        (t["id"],),
    ).fetchall()
    verified_by_unit = {
        row["unit_id"]: row
        for row in conn.execute("SELECT * FROM thread_unit WHERE thread_id = ?", (t["id"],)).fetchall()
    }
    units_out = []
    for unit_id in sorted(scored["unit_ids"]):
        unit_row = conn.execute("SELECT * FROM unit WHERE id = ?", (unit_id,)).fetchone()
        verified = verified_by_unit.get(unit_id)
        units_out.append(ThreadUnitOut(
            unit=_to_unit_out(unit_row),
            model_verdict=verified["model_verdict"] if verified else None,
            quote=verified["quote"] if verified else None,
            user_verdict=verified["user_verdict"] if verified else None,
        ))
    return RankedThreadOut(
        id=t["id"], idea=t["idea"], edited_idea=t["edited_idea"], source=t["source"], stale=bool(t["stale"]),
        statements=[_thread_statement_out(conn, s) for s in statements],
        units=units_out,
        covered_requirements=[_req_ref(r) for r in scored["covered"]],
        uncovered_requirements=[_req_ref(r) for r in scored["uncovered"]],
        support_count=scored["support_count"],
        exempt_from_min_support=(t["source"] == "user" and scored["support_count"] < settings.min_support),
    )


def _score_for_thread(conn: sqlite3.Connection, job_id: int, thread_row: sqlite3.Row) -> dict:
    from app.thread_ranking import covered_and_uncovered, thread_unit_ids
    unit_ids = thread_unit_ids(conn, thread_row["id"])
    covered, uncovered = covered_and_uncovered(conn, job_id, unit_ids)
    support_count = conn.execute(
        "SELECT COUNT(*) AS n FROM thread_statement WHERE thread_id = ?", (thread_row["id"],)
    ).fetchone()["n"]
    return {"thread": thread_row, "unit_ids": unit_ids, "covered": covered, "uncovered": uncovered, "support_count": support_count}


def _slot(conn: sqlite3.Connection, job_id: int, role: str) -> PrimarySecondarySlot:
    choice = get_choice(conn, job_id, role)
    if not choice:
        return PrimarySecondarySlot(thread=None, choice_stale=False)
    thread_row = conn.execute("SELECT * FROM thread WHERE id = ?", (choice["thread_id"],)).fetchone()
    if not thread_row:
        return PrimarySecondarySlot(thread=None, choice_stale=True)
    stale = bool(thread_row["deleted"]) or bool(thread_row["stale"])
    scored = _score_for_thread(conn, job_id, thread_row)
    return PrimarySecondarySlot(thread=_ranked_out(conn, scored), choice_stale=stale)


def _build_response(conn: sqlite3.Connection, job_id: int) -> PrimarySecondaryResponse:
    primary = _slot(conn, job_id, "primary")
    secondary = _slot(conn, job_id, "secondary")

    ranked = rank_candidates(conn, job_id)
    chosen_ids = {s.thread.id for s in (primary, secondary) if s.thread}
    other = [_ranked_out(conn, s) for s in ranked if s["thread"]["id"] not in chosen_ids]

    empty_reason = None
    if not ranked and not primary.thread:
        any_thread = conn.execute(
            "SELECT 1 FROM thread t JOIN thread_run r ON r.id = t.run_id WHERE r.job_id = ? AND t.deleted = 0",
            (job_id,),
        ).fetchone()
        empty_reason = (
            "No threads were found for this job yet." if not any_thread
            else f"No thread has at least {settings.min_support} supporting statements."
        )

    return PrimarySecondaryResponse(primary=primary, secondary=secondary, other_candidates=other, empty_reason=empty_reason)


@router.get("/{job_id}/primary-secondary", response_model=PrimarySecondaryResponse)
def get_primary_secondary(job_id: int, conn: sqlite3.Connection = Depends(get_db)):
    _fetch_job_or_404(conn, job_id)
    has_any_choice = get_choice(conn, job_id, "primary") is not None or get_choice(conn, job_id, "secondary") is not None
    if not has_any_choice:
        # First visit only: auto-suggest, same as clicking "Suggest again"
        # once -- never recomputed again after this (§8 point 6). Every
        # other endpoint below just performed an explicit user action and
        # must not re-trigger this (e.g. clearing secondary down to no
        # choice at all must not look like "never chosen yet").
        suggest_and_persist(conn, job_id)
    return _build_response(conn, job_id)


@router.post("/{job_id}/primary-secondary/suggest", response_model=PrimarySecondaryResponse)
def suggest_again(job_id: int, conn: sqlite3.Connection = Depends(get_db)):
    _fetch_job_or_404(conn, job_id)
    suggest_and_persist(conn, job_id)
    return _build_response(conn, job_id)


@router.post("/{job_id}/primary-secondary/choose", response_model=PrimarySecondaryResponse)
def choose_thread(job_id: int, body: ChooseThreadRequest, conn: sqlite3.Connection = Depends(get_db)):
    """Free pick, nothing blocked (§8 point 8) -- any non-deleted thread
    can become primary or secondary."""
    _fetch_job_or_404(conn, job_id)
    thread_row = conn.execute("SELECT * FROM thread WHERE id = ? AND deleted = 0", (body.thread_id,)).fetchone()
    if not thread_row:
        raise HTTPException(404, "Thread not found")
    set_choice(conn, job_id, body.role, body.thread_id)
    conn.commit()
    return _build_response(conn, job_id)


@router.post("/{job_id}/primary-secondary/swap", response_model=PrimarySecondaryResponse)
def swap_primary_secondary(job_id: int, conn: sqlite3.Connection = Depends(get_db)):
    _fetch_job_or_404(conn, job_id)
    primary = get_choice(conn, job_id, "primary")
    secondary = get_choice(conn, job_id, "secondary")
    clear_choice(conn, job_id, "primary")
    clear_choice(conn, job_id, "secondary")
    if secondary:
        set_choice(conn, job_id, "primary", secondary["thread_id"])
    if primary:
        set_choice(conn, job_id, "secondary", primary["thread_id"])
    conn.commit()
    return _build_response(conn, job_id)


@router.delete("/{job_id}/primary-secondary/secondary", response_model=PrimarySecondaryResponse)
def clear_secondary(job_id: int, conn: sqlite3.Connection = Depends(get_db)):
    _fetch_job_or_404(conn, job_id)
    clear_choice(conn, job_id, "secondary")
    conn.commit()
    return _build_response(conn, job_id)
