import sqlite3

from fastapi import APIRouter, Depends, HTTPException

from app.api_schemas import (
    ManualThreadRequest,
    MergeThreadsRequest,
    MoveStatementRequest,
    RunThreadsBlockedReason,
    ThreadIdeaPatchRequest,
    ThreadOut,
    ThreadRunHistoryResponse,
    ThreadRunOut,
    ThreadRunSummary,
    ThreadStatementOut,
    ThreadUnitOut,
)
from app.config import settings
from app.deps import get_db, get_llm_client
from app.judging import ensure_job_not_judging, ensure_model_not_busy
from app.llm.base import LLMClient
from app.routers.units import _to_unit_out
from app.threads import run_thread_discovery

router = APIRouter(tags=["threads"])


def _fetch_job_or_404(conn: sqlite3.Connection, job_id: int) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM job WHERE id = ?", (job_id,)).fetchone()
    if not row:
        raise HTTPException(404, "Job not found")
    return row


def _blocked_reason(conn: sqlite3.Connection, job_id: int) -> str | None:
    row = conn.execute(
        "SELECT 1 FROM job WHERE id = ? AND judging_deadline > datetime('now')", (job_id,)
    ).fetchone()
    if row:
        return "A judging window is still open."
    unconfirmed = conn.execute(
        "SELECT 1 FROM statement WHERE pair_id IN (SELECT id FROM pair WHERE job_id = ?) "
        "AND autofilled_from_job_id IS NOT NULL AND confirmed = 0",
        (job_id,),
    ).fetchone()
    if unconfirmed:
        return "Confirm or edit every autofilled statement first."
    if conn.execute("SELECT 1 FROM job WHERE judging_deadline > datetime('now')").fetchone():
        return "The model is busy with another job right now."
    return None


def _thread_statement_out(conn: sqlite3.Connection, row: sqlite3.Row) -> ThreadStatementOut:
    pair = conn.execute(
        "SELECT unit_a_id, unit_b_id FROM pair WHERE id = (SELECT pair_id FROM statement WHERE id = ?)",
        (row["statement_id"],),
    ).fetchone()
    unit_a = conn.execute("SELECT * FROM unit WHERE id = ?", (pair["unit_a_id"],)).fetchone()
    unit_b = conn.execute("SELECT * FROM unit WHERE id = ?", (pair["unit_b_id"],)).fetchone()
    return ThreadStatementOut(
        statement_id=row["statement_id"], text=row["text"],
        unit_a=_to_unit_out(unit_a), unit_b=_to_unit_out(unit_b), origin=row["origin"],
    )


def _thread_out(conn: sqlite3.Connection, thread_row: sqlite3.Row) -> ThreadOut:
    statements = conn.execute(
        "SELECT ts.origin, s.id AS statement_id, s.text FROM thread_statement ts "
        "JOIN statement s ON s.id = ts.statement_id WHERE ts.thread_id = ? ORDER BY ts.id",
        (thread_row["id"],),
    ).fetchall()
    units = conn.execute(
        "SELECT tu.*, u.* FROM thread_unit tu JOIN unit u ON u.id = tu.unit_id WHERE tu.thread_id = ? ORDER BY tu.id",
        (thread_row["id"],),
    ).fetchall()
    return ThreadOut(
        id=thread_row["id"], idea=thread_row["idea"], edited_idea=thread_row["edited_idea"],
        source=thread_row["source"], stale=bool(thread_row["stale"]), below_min=bool(thread_row["below_min"]),
        statements=[_thread_statement_out(conn, s) for s in statements],
        units=[
            ThreadUnitOut(unit=_to_unit_out(u), model_verdict=u["model_verdict"], quote=u["quote"], user_verdict=u["user_verdict"])
            for u in units
        ],
    )


def _run_out(conn: sqlite3.Connection, run_row: sqlite3.Row) -> ThreadRunOut:
    threads = conn.execute(
        "SELECT * FROM thread WHERE run_id = ? AND deleted = 0 ORDER BY id", (run_row["id"],)
    ).fetchall()
    return ThreadRunOut(
        id=run_row["id"], job_id=run_row["job_id"], created_at=run_row["created_at"], error=run_row["error"],
        threads=[_thread_out(conn, t) for t in threads],
        proposed_count=run_row["proposed_count"], moved_count=run_row["moved_count"], removed_count=run_row["removed_count"],
        seconds_total=run_row["seconds_total"],
    )


@router.get("/api/jobs/{job_id}/threads/can-run", response_model=RunThreadsBlockedReason)
def can_run_threads(job_id: int, conn: sqlite3.Connection = Depends(get_db)):
    _fetch_job_or_404(conn, job_id)
    reason = _blocked_reason(conn, job_id)
    return RunThreadsBlockedReason(blocked=reason is not None, reason=reason)


@router.post("/api/jobs/{job_id}/threads/run", response_model=ThreadRunOut)
def run_threads(
    job_id: int, conn: sqlite3.Connection = Depends(get_db), llm_client: LLMClient = Depends(get_llm_client),
):
    """§7 §3 rule reuse: blocked (409) while a judging window is open
    anywhere, while any autofilled statement on this job is unconfirmed,
    or while the model is otherwise busy."""
    job_row = _fetch_job_or_404(conn, job_id)
    ensure_model_not_busy(conn)
    ensure_job_not_judging(conn, job_id)
    reason = _blocked_reason(conn, job_id)
    if reason:
        raise HTTPException(409, reason)

    run_id = run_thread_discovery(conn, job_id, llm_client, settings.llm_model)
    run_row = conn.execute("SELECT * FROM thread_run WHERE id = ?", (run_id,)).fetchone()
    return _run_out(conn, run_row)


@router.post("/api/jobs/{job_id}/threads/manual", response_model=ThreadOut, status_code=201)
def create_manual_thread(job_id: int, body: ManualThreadRequest, conn: sqlite3.Connection = Depends(get_db)):
    """§8 point 9: a user-written thread -- no model call, exempt from
    min_support. Attached to the job's latest thread_run if one exists
    (threads need a run_id), else a fresh run created to hold it."""
    _fetch_job_or_404(conn, job_id)
    if not body.statement_ids:
        raise HTTPException(400, "Pick at least one statement")
    for sid in body.statement_ids:
        row = conn.execute(
            "SELECT 1 FROM statement s JOIN pair p ON p.id = s.pair_id WHERE s.id = ? AND p.job_id = ?", (sid, job_id)
        ).fetchone()
        if not row:
            raise HTTPException(404, f"Statement {sid} not found on this job")

    run_row = conn.execute("SELECT id FROM thread_run WHERE job_id = ? ORDER BY id DESC LIMIT 1", (job_id,)).fetchone()
    if run_row:
        run_id = run_row["id"]
    else:
        cur = conn.execute(
            "INSERT INTO thread_run (job_id, params_json, statements_snapshot_json) VALUES (?, '{}', '[]')", (job_id,)
        )
        run_id = cur.lastrowid

    cur = conn.execute("INSERT INTO thread (run_id, idea, source) VALUES (?, ?, 'user')", (run_id, body.idea))
    thread_id = cur.lastrowid
    for sid in body.statement_ids:
        conn.execute(
            "INSERT INTO thread_statement (thread_id, statement_id, origin) VALUES (?, ?, 'user')", (thread_id, sid)
        )
    conn.commit()
    return _thread_out(conn, _fetch_thread_or_404(conn, thread_id))


@router.get("/api/jobs/{job_id}/threads", response_model=ThreadRunOut)
def latest_threads(job_id: int, conn: sqlite3.Connection = Depends(get_db)):
    _fetch_job_or_404(conn, job_id)
    run_row = conn.execute(
        "SELECT * FROM thread_run WHERE job_id = ? ORDER BY id DESC LIMIT 1", (job_id,)
    ).fetchone()
    if not run_row:
        raise HTTPException(404, "No thread run yet")
    return _run_out(conn, run_row)


@router.get("/api/jobs/{job_id}/threads/history", response_model=ThreadRunHistoryResponse)
def thread_history(job_id: int, conn: sqlite3.Connection = Depends(get_db)):
    _fetch_job_or_404(conn, job_id)
    rows = conn.execute(
        "SELECT id, created_at, error FROM thread_run WHERE job_id = ? ORDER BY id DESC", (job_id,)
    ).fetchall()
    return ThreadRunHistoryResponse(runs=[ThreadRunSummary(id=r["id"], created_at=r["created_at"], error=r["error"]) for r in rows])


@router.get("/api/thread-runs/{run_id}", response_model=ThreadRunOut)
def get_thread_run(run_id: int, conn: sqlite3.Connection = Depends(get_db)):
    run_row = conn.execute("SELECT * FROM thread_run WHERE id = ?", (run_id,)).fetchone()
    if not run_row:
        raise HTTPException(404, "Thread run not found")
    return _run_out(conn, run_row)


def _fetch_thread_or_404(conn: sqlite3.Connection, thread_id: int) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM thread WHERE id = ? AND deleted = 0", (thread_id,)).fetchone()
    if not row:
        raise HTTPException(404, "Thread not found")
    return row


@router.patch("/api/threads/{thread_id}", response_model=ThreadOut)
def patch_thread_idea(thread_id: int, body: ThreadIdeaPatchRequest, conn: sqlite3.Connection = Depends(get_db)):
    """Editing a thread is a user action, never a model call (§7)."""
    thread_row = _fetch_thread_or_404(conn, thread_id)
    conn.execute("UPDATE thread SET edited_idea = ? WHERE id = ?", (body.idea, thread_id))
    conn.commit()
    return _thread_out(conn, conn.execute("SELECT * FROM thread WHERE id = ?", (thread_id,)).fetchone())


@router.post("/api/threads/{thread_id}/promote", response_model=ThreadOut)
def promote_thread(thread_id: int, conn: sqlite3.Connection = Depends(get_db)):
    """§7 part B point 6: "Use anyway" -- clears below_min. The user's
    decision, no model call."""
    _fetch_thread_or_404(conn, thread_id)
    conn.execute("UPDATE thread SET below_min = 0 WHERE id = ?", (thread_id,))
    conn.commit()
    return _thread_out(conn, _fetch_thread_or_404(conn, thread_id))


@router.delete("/api/threads/{thread_id}", status_code=204)
def delete_thread(thread_id: int, conn: sqlite3.Connection = Depends(get_db)):
    _fetch_thread_or_404(conn, thread_id)
    conn.execute("UPDATE thread SET deleted = 1 WHERE id = ?", (thread_id,))
    conn.commit()


@router.post("/api/threads/{thread_id}/statements", response_model=ThreadOut, status_code=201)
def move_statement_into_thread(thread_id: int, body: MoveStatementRequest, conn: sqlite3.Connection = Depends(get_db)):
    """Moves (or adds) a statement into this thread -- if it already
    belongs to another thread in the same run, it's removed from there
    first (a statement lives in at most one thread per run)."""
    thread_row = _fetch_thread_or_404(conn, thread_id)
    statement_row = conn.execute("SELECT id FROM statement WHERE id = ?", (body.statement_id,)).fetchone()
    if not statement_row:
        raise HTTPException(404, "Statement not found")

    conn.execute(
        "DELETE FROM thread_statement WHERE statement_id = ? AND thread_id IN "
        "(SELECT id FROM thread WHERE run_id = ?)",
        (body.statement_id, thread_row["run_id"]),
    )
    conn.execute(
        "INSERT INTO thread_statement (thread_id, statement_id, origin) VALUES (?, ?, 'user')",
        (thread_id, body.statement_id),
    )
    conn.commit()
    return _thread_out(conn, _fetch_thread_or_404(conn, thread_id))


@router.delete("/api/threads/{thread_id}/statements/{statement_id}", response_model=ThreadOut)
def remove_statement_from_thread(thread_id: int, statement_id: int, conn: sqlite3.Connection = Depends(get_db)):
    _fetch_thread_or_404(conn, thread_id)
    conn.execute("DELETE FROM thread_statement WHERE thread_id = ? AND statement_id = ?", (thread_id, statement_id))
    conn.commit()
    return _thread_out(conn, _fetch_thread_or_404(conn, thread_id))


@router.post("/api/threads/{thread_id}/merge", response_model=ThreadOut)
def merge_threads(thread_id: int, body: MergeThreadsRequest, conn: sqlite3.Connection = Depends(get_db)):
    """Merges other_thread_id INTO thread_id: its statements move over
    (duplicates ignored) and it's deleted. Units are a mechanical rebuild
    from the thread's statements' pairs, not re-verified -- merging never
    calls the model."""
    target = _fetch_thread_or_404(conn, thread_id)
    other = _fetch_thread_or_404(conn, body.other_thread_id)
    if target["id"] == other["id"]:
        raise HTTPException(400, "Cannot merge a thread with itself")

    other_statements = conn.execute(
        "SELECT statement_id, origin FROM thread_statement WHERE thread_id = ?", (other["id"],)
    ).fetchall()
    for row in other_statements:
        existing = conn.execute(
            "SELECT 1 FROM thread_statement WHERE thread_id = ? AND statement_id = ?",
            (thread_id, row["statement_id"]),
        ).fetchone()
        if not existing:
            conn.execute(
                "INSERT INTO thread_statement (thread_id, statement_id, origin) VALUES (?, ?, ?)",
                (thread_id, row["statement_id"], row["origin"]),
            )
    conn.execute("UPDATE thread SET deleted = 1 WHERE id = ?", (other["id"],))

    # Rebuild thread_unit for the target from its (now merged) statements'
    # pairs -- mechanical union, no re-verification.
    conn.execute("DELETE FROM thread_unit WHERE thread_id = ?", (thread_id,))
    unit_ids: set[int] = set()
    for row in conn.execute("SELECT statement_id FROM thread_statement WHERE thread_id = ?", (thread_id,)).fetchall():
        pair = conn.execute(
            "SELECT unit_a_id, unit_b_id FROM pair WHERE id = (SELECT pair_id FROM statement WHERE id = ?)",
            (row["statement_id"],),
        ).fetchone()
        unit_ids.update((pair["unit_a_id"], pair["unit_b_id"]))
    old_units_target = {
        r["unit_id"]: r for r in conn.execute("SELECT * FROM thread_unit WHERE thread_id = ?", (thread_id,)).fetchall()
    }
    old_units_other = {
        r["unit_id"]: r for r in conn.execute("SELECT * FROM thread_unit WHERE thread_id = ?", (other["id"],)).fetchall()
    }
    for unit_id in unit_ids:
        source = old_units_target.get(unit_id) or old_units_other.get(unit_id)
        conn.execute(
            "INSERT INTO thread_unit (thread_id, unit_id, model_verdict, quote, user_verdict) VALUES (?, ?, ?, ?, ?)",
            (thread_id, unit_id, source["model_verdict"] if source else None, source["quote"] if source else None,
             source["user_verdict"] if source else None),
        )

    conn.commit()
    return _thread_out(conn, _fetch_thread_or_404(conn, thread_id))
