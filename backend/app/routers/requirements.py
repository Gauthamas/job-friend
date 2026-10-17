import sqlite3

from fastapi import APIRouter, Depends, HTTPException

from app.api_schemas import (
    AttachUnitRequest,
    AttachUnitResponse,
    JudgmentOut,
    RequirementOut,
    RequirementPatchRequest,
    RequirementWithJudgments,
)
from app.deps import get_db
from app.judging import ensure_job_not_judging, mark_done_if_pending
from app.verdicts import requirement_verdict as compute_requirement_verdict

router = APIRouter(prefix="/api/requirements", tags=["requirements"])


def _requirement_out(row: sqlite3.Row) -> RequirementOut:
    return RequirementOut(
        id=row["id"], job_id=row["job_id"], text=row["text"], weight=row["weight"],
        source=row["source"], status=row["status"], reason=row["reason"], last_error=row["last_error"],
        sort_order=row["sort_order"], judged_at=row["judged_at"], embed_seconds=row["embed_seconds"],
        judge_seconds=row["judge_seconds"],
    )


def _judgment_out(row: sqlite3.Row) -> JudgmentOut:
    return JudgmentOut(
        id=row["id"], requirement_id=row["requirement_id"], unit_id=row["unit_id"], score=row["score"],
        model_verdict=row["model_verdict"], user_verdict=row["user_verdict"],
        added_by_user=bool(row["added_by_user"]), created_at=row["created_at"], why=row["why"],
    )


def _fetch_requirement(conn: sqlite3.Connection, requirement_id: int) -> sqlite3.Row:
    row = conn.execute(
        "SELECT * FROM requirement WHERE id = ? AND deleted = 0", (requirement_id,)
    ).fetchone()
    if not row:
        raise HTTPException(404, "Requirement not found")
    return row


@router.patch("/{requirement_id}", response_model=RequirementOut)
def patch_requirement(
    requirement_id: int,
    body: RequirementPatchRequest,
    conn: sqlite3.Connection = Depends(get_db),
):
    row = _fetch_requirement(conn, requirement_id)
    ensure_job_not_judging(conn, row["job_id"])
    provided = body.model_fields_set

    if "text" in provided and not body.text:
        raise HTTPException(400, "text cannot be empty")

    updates: dict = {}
    if "text" in provided and body.text != row["text"]:
        updates["text"] = body.text
    if "weight" in provided and body.weight != row["weight"]:
        updates["weight"] = body.weight

    # §3 rule 10: editing text or weight never touches verdicts or status.
    if updates:
        set_clause = ", ".join(f"{field} = ?" for field in updates)
        conn.execute(f"UPDATE requirement SET {set_clause} WHERE id = ?", (*updates.values(), requirement_id))
        conn.commit()

    return _requirement_out(_fetch_requirement(conn, requirement_id))


@router.delete("/{requirement_id}", status_code=204)
def delete_requirement(requirement_id: int, conn: sqlite3.Connection = Depends(get_db)):
    row = _fetch_requirement(conn, requirement_id)
    ensure_job_not_judging(conn, row["job_id"])
    conn.execute("UPDATE requirement SET deleted = 1 WHERE id = ?", (requirement_id,))
    conn.commit()


@router.post("/{requirement_id}/units", response_model=AttachUnitResponse, status_code=201)
def attach_unit(
    requirement_id: int,
    body: AttachUnitRequest,
    conn: sqlite3.Connection = Depends(get_db),
):
    requirement_row = _fetch_requirement(conn, requirement_id)
    ensure_job_not_judging(conn, requirement_row["job_id"])
    unit = conn.execute(
        "SELECT * FROM unit WHERE id = ? AND deleted = 0", (body.unit_id,)
    ).fetchone()
    if not unit:
        raise HTTPException(404, "Unit not found")

    # Manually attaching a unit never touches the model (§3) -- the user is
    # asserting a match, so user_verdict defaults to 'match' immediately;
    # model_verdict stays NULL since the model never saw this pairing.
    cursor = conn.execute(
        "INSERT INTO judgment (requirement_id, unit_id, added_by_user, user_verdict) "
        "VALUES (?, ?, 1, 'match')",
        (requirement_id, body.unit_id),
    )
    conn.commit()
    # Attaching a unit sets a verdict ('match') just like a chip click --
    # it completes a pending requirement the same way (no separate "Done").
    mark_done_if_pending(conn, requirement_id)

    row = conn.execute("SELECT * FROM judgment WHERE id = ?", (cursor.lastrowid,)).fetchone()
    judgment_out = _judgment_out(row)

    requirement_row = _fetch_requirement(conn, requirement_id)
    judgment_rows = conn.execute(
        "SELECT * FROM judgment WHERE requirement_id = ?", (requirement_id,)
    ).fetchall()
    verdict = compute_requirement_verdict(requirement_row["status"], judgment_rows)

    return AttachUnitResponse(
        judgment=judgment_out, requirement_verdict=verdict, requirement_status=requirement_row["status"],
    )


@router.post("/{requirement_id}/no-match", response_model=RequirementWithJudgments)
def mark_no_match(requirement_id: int, conn: sqlite3.Connection = Depends(get_db)):
    """Manual "No match" (§3's edit block): a plain DB write, no model
    call. Keeps every candidate judgment row -- only sets each one's
    user_verdict to 'none' ("no selection", the same value a chip-cycle
    click already produces), never touching model_verdict, why, or score.
    Re-selecting a unit is just the existing chip-cycle/attach-unit UI;
    nothing here needs undoing by a dedicated action. With every
    judgment's effective verdict now 'none', compute_requirement_verdict
    reads the requirement as a gap (§4: gaps are normal) -- but the
    candidates themselves stay listed, unselected, not deleted. A
    requirement the model never saw (marked before Start) simply has no
    judgment rows to update. Allowed exactly where every other edit is --
    blocked only while this job's own window is open, same guard as
    attach_unit above."""
    row = _fetch_requirement(conn, requirement_id)
    ensure_job_not_judging(conn, row["job_id"])

    conn.execute("UPDATE judgment SET user_verdict = 'none' WHERE requirement_id = ?", (requirement_id,))
    conn.execute(
        "UPDATE requirement SET status = 'done', reason = 'marked by user' WHERE id = ?",
        (requirement_id,),
    )
    conn.commit()

    requirement_row = _fetch_requirement(conn, requirement_id)
    judgment_rows = conn.execute(
        "SELECT * FROM judgment WHERE requirement_id = ?", (requirement_id,)
    ).fetchall()
    verdict = compute_requirement_verdict(requirement_row["status"], judgment_rows)
    return RequirementWithJudgments(
        requirement=_requirement_out(requirement_row),
        judgments=[_judgment_out(r) for r in judgment_rows],
        verdict=verdict,
    )
