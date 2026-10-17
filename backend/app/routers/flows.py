import sqlite3

from fastapi import APIRouter, Depends, HTTPException, Query

from app.api_schemas import (
    FlowCreateRequest,
    FlowListResponse,
    FlowOut,
    JobCreateRequest,
    JobCreateResponse,
    JobListResponse,
    JobOut,
)
from app.deps import get_db
from app.judging import ensure_model_not_busy
from app.profiles import get_or_create_default_profile

router = APIRouter(prefix="/api/flows", tags=["flows"])


def _flow_out(row: sqlite3.Row) -> FlowOut:
    return FlowOut(
        id=row["id"], name=row["name"], inventory_id=row["inventory_id"],
        profile_id=row["profile_id"], created_at=row["created_at"],
        latest_job_id=row["latest_job_id"] if "latest_job_id" in row.keys() else None,
        latest_job_discarded_at=row["latest_job_discarded_at"] if "latest_job_discarded_at" in row.keys() else None,
    )


_FLOW_WITH_LATEST_JOB = (
    "SELECT f.*, "
    "  (SELECT j.id FROM job j WHERE j.flow_id = f.id ORDER BY j.id DESC LIMIT 1) AS latest_job_id, "
    "  (SELECT j.discarded_at FROM job j WHERE j.flow_id = f.id ORDER BY j.id DESC LIMIT 1) AS latest_job_discarded_at "
    "FROM flow f"
)


@router.post("", response_model=FlowOut)
def create_flow(body: FlowCreateRequest, conn: sqlite3.Connection = Depends(get_db)):
    inventory = conn.execute("SELECT id FROM inventory WHERE id = ?", (body.inventory_id,)).fetchone()
    if not inventory:
        raise HTTPException(404, "Inventory not found")

    profile_id = body.profile_id or get_or_create_default_profile(conn)
    cursor = conn.execute(
        "INSERT INTO flow (profile_id, name, inventory_id) VALUES (?, ?, ?)",
        (profile_id, body.name, body.inventory_id),
    )
    conn.commit()

    row = conn.execute("SELECT * FROM flow WHERE id = ?", (cursor.lastrowid,)).fetchone()
    return _flow_out(row)


@router.get("", response_model=FlowListResponse)
def list_flows(include_discarded: bool = Query(False), conn: sqlite3.Connection = Depends(get_db)):
    """A flow with no jobs yet always shows. Otherwise hidden by default
    once its latest job (the one a click already opens) is discarded --
    the Flows screen's own Discard/Restore button acts on that same job."""
    rows = conn.execute(f"{_FLOW_WITH_LATEST_JOB} ORDER BY f.id DESC").fetchall()
    if not include_discarded:
        rows = [r for r in rows if r["latest_job_discarded_at"] is None]
    return FlowListResponse(flows=[_flow_out(row) for row in rows])


@router.get("/{flow_id}", response_model=FlowOut)
def get_flow(flow_id: int, conn: sqlite3.Connection = Depends(get_db)):
    row = conn.execute(f"{_FLOW_WITH_LATEST_JOB} WHERE f.id = ?", (flow_id,)).fetchone()
    if not row:
        raise HTTPException(404, "Flow not found")
    return _flow_out(row)


def _job_out(row: sqlite3.Row) -> JobOut:
    return JobOut(
        id=row["id"], flow_id=row["flow_id"], title=row["title"],
        jd_text=row["jd_text"], jd_submitted_text=row["jd_submitted_text"],
        jd_submitted_at=row["jd_submitted_at"], extraction_error=row["extraction_error"],
        created_at=row["created_at"], extraction_seconds=row["extraction_seconds"],
        judging_started_at=row["judging_started_at"], judging_deadline=row["judging_deadline"],
        finished_at=row["finished_at"], company=row["company"], role_title=row["role_title"],
        discarded_at=row["discarded_at"],
    )


@router.get("/{flow_id}/jobs", response_model=JobListResponse)
def list_flow_jobs(flow_id: int, conn: sqlite3.Connection = Depends(get_db)):
    """So the Flows screen can re-open an existing job instead of always
    sending the user to create a new one."""
    flow = conn.execute("SELECT id FROM flow WHERE id = ?", (flow_id,)).fetchone()
    if not flow:
        raise HTTPException(404, "Flow not found")
    rows = conn.execute("SELECT * FROM job WHERE flow_id = ? ORDER BY id DESC", (flow_id,)).fetchall()
    return JobListResponse(jobs=[_job_out(row) for row in rows])


@router.post("/{flow_id}/jobs", response_model=JobCreateResponse)
def create_job(
    flow_id: int,
    body: JobCreateRequest,
    conn: sqlite3.Connection = Depends(get_db),
):
    """Lightweight: just a title, no JD text yet. The JD screen (§3.1)
    handles extraction via POST /api/jobs/{id}/submit-jd. Blocked while any
    window is open elsewhere, same as every other model-touching action
    (this one doesn't call the model itself, but §3 rule 5 lists "creating
    a job" explicitly among the blocked actions)."""
    flow = conn.execute("SELECT id FROM flow WHERE id = ?", (flow_id,)).fetchone()
    if not flow:
        raise HTTPException(404, "Flow not found")
    ensure_model_not_busy(conn)

    cursor = conn.execute(
        "INSERT INTO job (flow_id, title, jd_text) VALUES (?, ?, '')",
        (flow_id, body.title),
    )
    conn.commit()

    job_row = conn.execute("SELECT * FROM job WHERE id = ?", (cursor.lastrowid,)).fetchone()
    return JobCreateResponse(job=_job_out(job_row))
