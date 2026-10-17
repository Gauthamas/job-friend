import asyncio
import json
import sqlite3
import time
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from fastapi.responses import StreamingResponse

from app.api_schemas import (
    EnrichmentRequirementRef,
    EnrichmentResponse,
    EnrichmentUnitOut,
    EnrichQuestions,
    JobFullMapResponse,
    JobOut,
    JobPatchRequest,
    JobProgressResponse,
    JudgmentOut,
    RequirementCreateRequest,
    RequirementOut,
    RequirementWithJudgments,
    SubmitJdRequest,
)
from app.config import settings
from app.db import connect
from app.deps import get_db, get_db_path, get_embedding_client, get_llm_client
from app.judging import (
    ensure_job_not_judging,
    ensure_model_not_busy,
    finish_window,
    has_judging_started,
    run_judging_window,
    shortlist_and_create_judgments,
    unjudged_requirement_count,
    wipe_job_requirements,
)
from app.llm.base import LLMClient
from app.llm.embedding_client import EmbeddingClient
from app.llm.runner import run_task
from app.llm.tasks import NO_THINK, REQUIREMENT_EXTRACT
from app.routers.units import _to_unit_out
from app.run_timing import record_run_timing
from app.verdicts import requirement_verdict as compute_requirement_verdict

router = APIRouter(prefix="/api/jobs", tags=["jobs"])

POLL_INTERVAL_SECONDS = 0.3
MAX_STREAM_SECONDS = 1500  # safety valve; covers the full 20-minute window plus slack


def _judgment_out(j: sqlite3.Row) -> JudgmentOut:
    return JudgmentOut(
        id=j["id"], requirement_id=j["requirement_id"], unit_id=j["unit_id"], score=j["score"],
        model_verdict=j["model_verdict"], user_verdict=j["user_verdict"],
        added_by_user=bool(j["added_by_user"]), created_at=j["created_at"], why=j["why"],
    )


def _requirement_out(row: sqlite3.Row) -> RequirementOut:
    return RequirementOut(
        id=row["id"], job_id=row["job_id"], text=row["text"], weight=row["weight"],
        source=row["source"], status=row["status"], reason=row["reason"], last_error=row["last_error"],
        sort_order=row["sort_order"], judged_at=row["judged_at"], embed_seconds=row["embed_seconds"],
        judge_seconds=row["judge_seconds"],
    )


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


def _fetch_requirements_with_judgments(conn: sqlite3.Connection, job_id: int) -> list[RequirementWithJudgments]:
    requirement_rows = conn.execute(
        "SELECT * FROM requirement WHERE job_id = ? AND deleted = 0 ORDER BY sort_order", (job_id,)
    ).fetchall()

    results = []
    for req_row in requirement_rows:
        judgment_rows = conn.execute(
            "SELECT * FROM judgment WHERE requirement_id = ? ORDER BY id", (req_row["id"],)
        ).fetchall()
        judgments = [_judgment_out(j) for j in judgment_rows]
        verdict = compute_requirement_verdict(req_row["status"], judgment_rows)
        results.append(RequirementWithJudgments(
            requirement=_requirement_out(req_row), judgments=judgments, verdict=verdict,
        ))
    return results


def _fetch_job_or_404(conn: sqlite3.Connection, job_id: int) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM job WHERE id = ?", (job_id,)).fetchone()
    if not row:
        raise HTTPException(404, "Job not found")
    return row


@router.patch("/{job_id}", response_model=JobOut)
def patch_job(job_id: int, body: JobPatchRequest, conn: sqlite3.Connection = Depends(get_db)):
    """§3.1: "The heading is saved on its own, with no warning and no
    rerun." -- never blocked by an open window, since none of these
    fields need the model. company/role_title are plain user-typed text,
    no extraction, shown next to the JD box; company (if set) seeds the
    writing view's default greeting the first time its letter is created
    (see get_or_create_letter) -- never touches an already-created one."""
    _fetch_job_or_404(conn, job_id)
    provided = body.model_fields_set

    updates: dict = {}
    if "title" in provided:
        if not body.title:
            raise HTTPException(400, "title cannot be empty")
        updates["title"] = body.title
    if "company" in provided:
        updates["company"] = body.company
    if "role_title" in provided:
        updates["role_title"] = body.role_title

    if updates:
        set_clause = ", ".join(f"{field} = ?" for field in updates)
        conn.execute(f"UPDATE job SET {set_clause} WHERE id = ?", (*updates.values(), job_id))
        conn.commit()

    return _job_out(_fetch_job_or_404(conn, job_id))


@router.post("/{job_id}/discard", response_model=JobOut)
def discard_job(job_id: int, conn: sqlite3.Connection = Depends(get_db)):
    """Reversible: sets job.discarded_at, same edit-block guard as every
    other action on this job. Nothing is deleted -- requirements,
    judgments, threads and the letter all stay exactly as they are, just
    hidden (the Flows list filters on this) until restored."""
    _fetch_job_or_404(conn, job_id)
    ensure_job_not_judging(conn, job_id)
    conn.execute("UPDATE job SET discarded_at = datetime('now') WHERE id = ?", (job_id,))
    conn.commit()
    return _job_out(_fetch_job_or_404(conn, job_id))


@router.post("/{job_id}/restore", response_model=JobOut)
def restore_job(job_id: int, conn: sqlite3.Connection = Depends(get_db)):
    _fetch_job_or_404(conn, job_id)
    ensure_job_not_judging(conn, job_id)
    conn.execute("UPDATE job SET discarded_at = NULL WHERE id = ?", (job_id,))
    conn.commit()
    return _job_out(_fetch_job_or_404(conn, job_id))


def _run_extraction(
    conn: sqlite3.Connection, job_id: int, jd_text: str,
    llm_client: LLMClient, embedding_client: EmbeddingClient,
) -> None:
    """Shared by submit-jd (first submit or resubmit) and retry-extraction.
    Extraction + shortlisting only -- judging no longer starts
    automatically afterward (a review step comes first: the user can
    edit/add/delete requirements, then starts judging explicitly via
    POST .../start-judging, which runs the exact same run_judging_window
    this used to kick off directly)."""
    conn.execute(
        "UPDATE job SET jd_text = ?, jd_submitted_text = ?, jd_submitted_at = datetime('now'), "
        "extraction_error = NULL WHERE id = ?",
        (jd_text, jd_text, job_id),
    )
    conn.commit()

    outcome = run_task(llm_client, REQUIREMENT_EXTRACT, jd_text)
    if outcome.status == "error" or not outcome.data.requirements:
        message = outcome.error or "Extraction returned no requirements."
        conn.execute("UPDATE job SET extraction_error = ? WHERE id = ?", (message, job_id))
        conn.commit()
        return

    extraction_seconds = sum(m.seconds for m in outcome.metrics)
    record_run_timing(
        conn, phase="extraction", model=settings.llm_model,
        thinking=not REQUIREMENT_EXTRACT.system_prompt.strip().startswith(NO_THINK),
        prompt_version=REQUIREMENT_EXTRACT.prompt_version,
        items=len(outcome.data.requirements), seconds_total=extraction_seconds,
    )

    for i, req in enumerate(outcome.data.requirements):
        req_cursor = conn.execute(
            "INSERT INTO requirement (job_id, text, weight, source, status, sort_order) "
            "VALUES (?, ?, ?, 'extracted', 'pending', ?)",
            (job_id, req.text, req.weight, i),
        )
        shortlist_and_create_judgments(
            conn, req_cursor.lastrowid, job_id, req.text, embedding_client, settings.top_k,
        )
    conn.execute("UPDATE job SET extraction_seconds = ? WHERE id = ?", (extraction_seconds, job_id))
    conn.commit()


@router.post("/{job_id}/submit-jd", response_model=JobFullMapResponse)
def submit_jd(
    job_id: int,
    body: SubmitJdRequest,
    conn: sqlite3.Connection = Depends(get_db),
    llm_client: LLMClient = Depends(get_llm_client),
    embedding_client: EmbeddingClient = Depends(get_embedding_client),
):
    """§3.1: first submit, or a resubmit of changed JD text (wipes this
    job's requirements/judgments first; units and enrichment untouched).
    Judging itself does not start here -- see start_judging below."""
    job_row = _fetch_job_or_404(conn, job_id)
    ensure_model_not_busy(conn)

    if job_row["jd_submitted_text"] == body.jd_text:
        raise HTTPException(400, "This JD text has already been submitted.")

    if job_row["jd_submitted_text"] is not None:
        wipe_job_requirements(conn, job_id)

    _run_extraction(conn, job_id, body.jd_text, llm_client, embedding_client)

    job_row = _fetch_job_or_404(conn, job_id)
    return JobFullMapResponse(job=_job_out(job_row), requirements=_fetch_requirements_with_judgments(conn, job_id))


@router.post("/{job_id}/retry-extraction", response_model=JobFullMapResponse)
def retry_extraction(
    job_id: int,
    conn: sqlite3.Connection = Depends(get_db),
    llm_client: LLMClient = Depends(get_llm_client),
    embedding_client: EmbeddingClient = Depends(get_embedding_client),
):
    """Re-runs extraction on the same jd_submitted_text after a failure --
    does not re-wipe anything (there's nothing to wipe: a failed extraction
    never created requirements)."""
    job_row = _fetch_job_or_404(conn, job_id)
    ensure_model_not_busy(conn)
    if job_row["jd_submitted_text"] is None:
        raise HTTPException(400, "No JD has been submitted yet.")

    _run_extraction(conn, job_id, job_row["jd_submitted_text"], llm_client, embedding_client)

    job_row = _fetch_job_or_404(conn, job_id)
    return JobFullMapResponse(job=_job_out(job_row), requirements=_fetch_requirements_with_judgments(conn, job_id))


@router.post("/{job_id}/start-judging", response_model=JobOut)
def start_judging(
    job_id: int,
    background_tasks: BackgroundTasks,
    conn: sqlite3.Connection = Depends(get_db),
    db_path: str = Depends(get_db_path),
    llm_client: LLMClient = Depends(get_llm_client),
):
    """The review step's explicit continuation: judging used to start the
    instant extraction finished; now it starts only here, on the same
    requirements the user has had a chance to edit/add/delete first.
    Schedules the exact same run_judging_window as a detached background
    task, same as the old automatic trigger did -- judging_started_at/
    judging_deadline are set inside it, not here, unchanged."""
    job_row = _fetch_job_or_404(conn, job_id)
    ensure_model_not_busy(conn)
    if job_row["jd_submitted_text"] is None:
        raise HTTPException(400, "No JD has been submitted yet.")
    if has_judging_started(conn, job_id):
        raise HTTPException(409, "Judging has already started for this job.")

    background_tasks.add_task(
        run_judging_window, db_path=db_path, job_id=job_id, llm_client=llm_client, model=settings.llm_model,
    )

    return _job_out(_fetch_job_or_404(conn, job_id))


@router.post("/{job_id}/resume-judging", response_model=JobOut)
def resume_judging(
    job_id: int,
    background_tasks: BackgroundTasks,
    conn: sqlite3.Connection = Depends(get_db),
    db_path: str = Depends(get_db_path),
    llm_client: LLMClient = Depends(get_llm_client),
):
    """Bug B's companion: a window can close (naturally, or because its
    background task died -- see close_open_judging_windows) with
    requirements still pending; this opens a brand-new window (edits
    blocked again while it runs) and calls the exact same
    run_judging_window, unchanged -- it already only ever processes
    status='pending' requirements, so nothing here special-cases "resume"
    vs. the first run. Same global one-window-at-a-time rule as every
    other model-touching action."""
    _fetch_job_or_404(conn, job_id)
    ensure_model_not_busy(conn)
    pending_count = conn.execute(
        "SELECT COUNT(*) AS c FROM requirement WHERE job_id = ? AND deleted = 0 AND status = 'pending'", (job_id,)
    ).fetchone()["c"]
    if pending_count == 0:
        raise HTTPException(400, "Nothing left to judge.")

    background_tasks.add_task(
        run_judging_window, db_path=db_path, job_id=job_id, llm_client=llm_client, model=settings.llm_model,
    )

    return _job_out(_fetch_job_or_404(conn, job_id))


@router.post("/{job_id}/finish", response_model=JobOut)
def finish(job_id: int, conn: sqlite3.Connection = Depends(get_db)):
    """§3: the "Finish and complete manually" button, and "Go back" on the
    leave-while-judging warning -- both cancel exactly this way."""
    _fetch_job_or_404(conn, job_id)
    finish_window(conn, job_id)
    return _job_out(_fetch_job_or_404(conn, job_id))


@router.post("/{job_id}/proceed")
def proceed(job_id: int, conn: sqlite3.Connection = Depends(get_db)):
    """§3 Proceed gate: blocked while this job's judging window is open
    (409), or while any non-discarded requirement has no recorded verdict
    at all (ok=False, unjudged_count>0) -- no silent skipping. A gap
    (effective verdict 'none'/no match anywhere) is still a normal,
    expected outcome once every requirement HAS been judged; no_matches
    only ever warns, never blocks."""
    _fetch_job_or_404(conn, job_id)
    ensure_job_not_judging(conn, job_id)

    unjudged_count = unjudged_requirement_count(conn, job_id)
    requirements = _fetch_requirements_with_judgments(conn, job_id)
    has_match_or_weak = any(r.verdict in ("match", "weak") for r in requirements)
    return {"ok": unjudged_count == 0, "no_matches": not has_match_or_weak, "unjudged_count": unjudged_count}


def _unit_is_complete(row: sqlite3.Row) -> bool:
    return all(
        bool(row[field]) or bool(row[f"{field}_skipped"])
        for field in ("context", "contribution", "outcome")
    )


@router.get("/{job_id}/enrichment", response_model=EnrichmentResponse)
def get_enrichment(job_id: int, conn: sqlite3.Connection = Depends(get_db)):
    """§5: every unit with an effective match verdict on at least one of
    this job's requirements, with its enrichment fields and which
    requirement(s) it matched. No LLM calls on this screen."""
    _fetch_job_or_404(conn, job_id)

    unit_rows = conn.execute(
        "SELECT DISTINCT u.* FROM unit u "
        "JOIN judgment j ON j.unit_id = u.id "
        "JOIN requirement r ON r.id = j.requirement_id "
        "WHERE r.job_id = ? AND r.deleted = 0 AND u.deleted = 0 "
        "AND COALESCE(j.user_verdict, j.model_verdict) = 'match' "
        "ORDER BY u.id",
        (job_id,),
    ).fetchall()

    units_out: list[EnrichmentUnitOut] = []
    enriched_count = 0
    for unit_row in unit_rows:
        requirement_rows = conn.execute(
            "SELECT DISTINCT r.id, r.text, r.weight FROM requirement r "
            "JOIN judgment j ON j.requirement_id = r.id "
            "WHERE r.job_id = ? AND r.deleted = 0 AND j.unit_id = ? "
            "AND COALESCE(j.user_verdict, j.model_verdict) = 'match' "
            "ORDER BY r.sort_order",
            (job_id, unit_row["id"]),
        ).fetchall()
        complete = _unit_is_complete(unit_row)
        if complete:
            enriched_count += 1
        units_out.append(EnrichmentUnitOut(
            unit=_to_unit_out(unit_row),
            matched_requirements=[
                EnrichmentRequirementRef(id=r["id"], text=r["text"], weight=r["weight"]) for r in requirement_rows
            ],
            complete=complete,
        ))

    return EnrichmentResponse(
        units=units_out,
        enriched_count=enriched_count,
        total_count=len(units_out),
        questions=EnrichQuestions(
            context=settings.enrich_question_context,
            contribution=settings.enrich_question_contribution,
            outcome=settings.enrich_question_outcome,
        ),
    )


@router.post("/{job_id}/requirements", response_model=RequirementOut, status_code=201)
def add_requirement(
    job_id: int,
    body: RequirementCreateRequest,
    conn: sqlite3.Connection = Depends(get_db),
    embedding_client: EmbeddingClient = Depends(get_embedding_client),
):
    _fetch_job_or_404(conn, job_id)
    ensure_job_not_judging(conn, job_id)
    ensure_model_not_busy(conn)

    max_sort_order = conn.execute(
        "SELECT MAX(sort_order) AS m FROM requirement WHERE job_id = ?", (job_id,)
    ).fetchone()["m"]
    sort_order = (max_sort_order + 1) if max_sort_order is not None else 0

    cursor = conn.execute(
        "INSERT INTO requirement (job_id, text, weight, source, status, sort_order) "
        "VALUES (?, ?, ?, 'user', 'pending', ?)",
        (job_id, body.text, body.weight, sort_order),
    )
    requirement_id = cursor.lastrowid
    conn.commit()

    shortlist_and_create_judgments(conn, requirement_id, job_id, body.text, embedding_client, settings.top_k)

    row = conn.execute("SELECT * FROM requirement WHERE id = ?", (requirement_id,)).fetchone()
    return _requirement_out(row)


@router.get("/{job_id}", response_model=JobFullMapResponse)
def get_job(job_id: int, conn: sqlite3.Connection = Depends(get_db)):
    job_row = _fetch_job_or_404(conn, job_id)
    return JobFullMapResponse(job=_job_out(job_row), requirements=_fetch_requirements_with_judgments(conn, job_id))


@router.get("/{job_id}/progress", response_model=JobProgressResponse)
def get_job_progress(job_id: int, conn: sqlite3.Connection = Depends(get_db)):
    """The furthest screen this job has reached, so re-opening it (from
    the Flows screen) can jump straight there instead of always landing on
    the JD/requirements view. Inferred from what each later screen's own
    "Continue" action actually persists -- never a separate tracked flag,
    so it can't drift out of sync with what's really been done."""
    _fetch_job_or_404(conn, job_id)

    letter = conn.execute("SELECT * FROM letter WHERE job_id = ?", (job_id,)).fetchone()
    if letter and (
        letter["finished"]
        or (letter["assembled_text"] and letter["assembled_text"].strip())
        or (letter["sections_json"] not in (None, "{}"))
    ):
        return JobProgressResponse(route="write")
    if conn.execute("SELECT 1 FROM job_thread WHERE job_id = ?", (job_id,)).fetchone():
        return JobProgressResponse(route="primary_secondary")
    if conn.execute("SELECT 1 FROM thread_run WHERE job_id = ?", (job_id,)).fetchone():
        return JobProgressResponse(route="threads")
    if conn.execute("SELECT 1 FROM pair WHERE job_id = ?", (job_id,)).fetchone():
        return JobProgressResponse(route="statements")
    return JobProgressResponse(route="job")


def _sse(event: str, **payload) -> str:
    return f"data: {json.dumps({'event': event, **payload})}\n\n"


def _is_window_running(job_row: sqlite3.Row, now_row: sqlite3.Row) -> bool:
    """§3: "Running" is derived from now < judging_deadline only -- nothing
    else, so a restart or crash can never leave this stuck. A NULL deadline
    (no window ever started for this job) is never "running"."""
    if job_row["judging_deadline"] is None:
        return False
    return now_row["now"] < job_row["judging_deadline"]


@router.get("/{job_id}/events")
def job_events(job_id: int, db_path: str = Depends(get_db_path)):
    conn = connect(db_path)
    job_row = conn.execute("SELECT id FROM job WHERE id = ?", (job_id,)).fetchone()
    conn.close()
    if not job_row:
        raise HTTPException(404, "Job not found")

    async def event_stream():
        # Polling bridge, not a real push pub/sub: the judging window runs
        # as a detached background task and just writes to SQLite, so this
        # generator periodically re-reads state and diffs it against what
        # it last sent. requirement_judged fires per requirement that newly
        # became 'done' (works for both a batch write and a manual
        # Done/No-match action); judging_finished fires exactly once, when
        # this job's window ends; job_updated fires whenever the job row
        # itself changes (crucially judging_started_at/judging_deadline,
        # set by the background task well after submit-jd's own response
        # already went out with them NULL -- without this, the client's
        # copy of judging_deadline would stay frozen at that stale snapshot
        # and the blocking dialog could never detect the window opening).
        last_status: dict[int, str] = {}
        last_job_snapshot: Optional[tuple] = None
        finished_emitted = False
        started = time.monotonic()

        while True:
            stream_conn = connect(db_path)
            try:
                job_row = stream_conn.execute("SELECT * FROM job WHERE id = ?", (job_id,)).fetchone()
                now_row = stream_conn.execute("SELECT datetime('now') AS now").fetchone()
                requirements = _fetch_requirements_with_judgments(stream_conn, job_id)
            finally:
                stream_conn.close()

            job_snapshot = tuple(job_row)
            if job_snapshot != last_job_snapshot:
                yield _sse("job_updated", job=_job_out(job_row).model_dump())
                last_job_snapshot = job_snapshot

            for item in requirements:
                req = item.requirement
                if last_status.get(req.id) != "done" and req.status == "done":
                    yield _sse(
                        "requirement_judged", requirement_id=req.id,
                        judgments=[j.model_dump() for j in item.judgments],
                        reason=req.reason, verdict=item.verdict,
                    )
                last_status[req.id] = req.status

            if not finished_emitted and not _is_window_running(job_row, now_row) and job_row["judging_deadline"] is not None:
                yield _sse("judging_finished", job_id=job_id)
                finished_emitted = True
                break

            all_done = bool(requirements) and all(item.requirement.status == "done" for item in requirements)
            if all_done and job_row["judging_deadline"] is None:
                break  # nothing ever ran a window and everything's already done by hand
            if (time.monotonic() - started) > MAX_STREAM_SECONDS:
                break

            await asyncio.sleep(POLL_INTERVAL_SECONDS)

    return StreamingResponse(event_stream(), media_type="text/event-stream")
