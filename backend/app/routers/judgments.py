import sqlite3

from fastapi import APIRouter, Depends, HTTPException

from app.api_schemas import JudgmentOut, JudgmentPatchRequest, JudgmentPatchResponse
from app.deps import get_db
from app.judging import ensure_job_not_judging, mark_done_if_pending
from app.verdicts import requirement_verdict as compute_requirement_verdict

router = APIRouter(prefix="/api/judgments", tags=["judgments"])


@router.patch("/{judgment_id}", response_model=JudgmentPatchResponse)
def patch_judgment(
    judgment_id: int,
    body: JudgmentPatchRequest,
    conn: sqlite3.Connection = Depends(get_db),
):
    row = conn.execute("SELECT * FROM judgment WHERE id = ?", (judgment_id,)).fetchone()
    if not row:
        raise HTTPException(404, "Judgment not found")

    job_id = conn.execute(
        "SELECT job_id FROM requirement WHERE id = ?", (row["requirement_id"],)
    ).fetchone()["job_id"]
    ensure_job_not_judging(conn, job_id)

    if "user_verdict" in body.model_fields_set:
        # Instant, never touches the model (§3) -- blocked only while this
        # requirement's own job is mid-window (checked above).
        conn.execute("UPDATE judgment SET user_verdict = ? WHERE id = ?", (body.user_verdict, judgment_id))
        conn.commit()
        if body.user_verdict is not None:
            # Setting a real verdict by hand is what completes a manual-
            # mode requirement -- there's no separate "Done" action.
            mark_done_if_pending(conn, row["requirement_id"])

    row = conn.execute("SELECT * FROM judgment WHERE id = ?", (judgment_id,)).fetchone()
    judgment_out = JudgmentOut(
        id=row["id"], requirement_id=row["requirement_id"], unit_id=row["unit_id"], score=row["score"],
        model_verdict=row["model_verdict"], user_verdict=row["user_verdict"],
        added_by_user=bool(row["added_by_user"]), created_at=row["created_at"], why=row["why"],
    )

    # The frontend must never derive match/weak/gap itself -- hand back the
    # requirement's updated verdict from the one shared function, computed
    # from the requirement's current status and all its judgment rows.
    requirement_row = conn.execute(
        "SELECT status FROM requirement WHERE id = ?", (row["requirement_id"],)
    ).fetchone()
    judgment_rows = conn.execute(
        "SELECT * FROM judgment WHERE requirement_id = ?", (row["requirement_id"],)
    ).fetchall()
    verdict = compute_requirement_verdict(requirement_row["status"], judgment_rows)

    return JudgmentPatchResponse(
        judgment=judgment_out, requirement_verdict=verdict, requirement_status=requirement_row["status"],
    )
