"""v2 draft 3 judging: one fixed 20-minute window
per job, judged in batches of `judge_batch_size` requirements per call
(thinking on, non-streaming semantics -- parsed once, no incremental
parser, no retry, no per-call timeout). Whatever doesn't get a valid
result before the window closes stays 'pending' with `last_error`, for the
user to finish by hand. Only one window can be open across all jobs.

Shortlisting happens once, when a requirement is created
(shortlist_and_create_judgments): it writes one judgment row per candidate
with model_verdict=NULL, which is what lets manual mode show chips to flip
without ever calling the model, and lets a judging window fill those same
rows in. Editing a requirement's text or weight never touches verdicts or
status (§3) -- only a JD resubmission wipes and restarts a job's
requirements.
"""

import json
import logging
import sqlite3
import threading
import time
from datetime import datetime, timedelta, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Callable, Optional

from fastapi import HTTPException
from pydantic import ValidationError

from app.config import settings
from app.db import connect
from app.judge_input import build_candidate_haystacks, build_judge_batch_message, format_unit_id
from app.llm.base import LLMClient, LlmTimeout
from app.llm.embedding_client import EmbeddingClient
from app.llm.judge_validation import validate_judge
from app.llm.schemas import JudgedUnit, JudgeResult
from app.llm.tasks import JUDGE_BATCH
from app.run_timing import record_run_timing
from app.shortlist import Candidate, _parse_skills, shortlist_units

logger = logging.getLogger("job_friend.judging")
logger.setLevel(logging.INFO)

# Every batch attempt (including exceptions, via logger.exception) lands
# here, independent of whatever the app's root/console logging is set up
# to show -- this is what let the Mishipay job's silent-crash investigation
# happen at all: there was no durable record of what the background task
# did once it stopped printing to a terminal nobody kept. Guarded so
# re-importing this module (every test file does) doesn't stack a new
# handler each time.
_LOG_DIR = Path(__file__).resolve().parent.parent / "logs"
_LOG_FILE = _LOG_DIR / "judging.log"
if not any(isinstance(h, RotatingFileHandler) and getattr(h, "baseFilename", None) == str(_LOG_FILE)
           for h in logger.handlers):
    _LOG_DIR.mkdir(exist_ok=True)
    _file_handler = RotatingFileHandler(_LOG_FILE, maxBytes=5_000_000, backupCount=3)
    _file_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.addHandler(_file_handler)

_WEIGHT_ORDER = {"high": 0, "medium": 1, "low": 2}

# Fixed, not a setting (v2 draft 3 §3/§4: "not configurable").
JUDGING_WINDOW_MINUTES = 20

_DT_FORMAT = "%Y-%m-%d %H:%M:%S"


def _utcnow() -> datetime:
    """Naive UTC, matching SQLite's own datetime('now') convention (which
    every other judging_deadline comparison in this app uses --
    is_any_window_open, is_job_window_open, the SSE poller,
    close_open_judging_windows). datetime.now() returns LOCAL time; using
    it here would store a deadline offset by the server's own timezone
    against everything that reads it back as if it were UTC."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _inventory_id_for_job(conn: sqlite3.Connection, job_id: int) -> int:
    return conn.execute(
        "SELECT f.inventory_id AS inventory_id FROM job j JOIN flow f ON j.flow_id = f.id WHERE j.id = ?",
        (job_id,),
    ).fetchone()["inventory_id"]


def shortlist_and_create_judgments(
    conn: sqlite3.Connection,
    requirement_id: int,
    job_id: int,
    requirement_text: str,
    embedding_client: EmbeddingClient,
    top_k: int,
) -> None:
    """Called once, right when a requirement is created (extraction or
    user-added). Writes a judgment row per candidate with model_verdict
    NULL ("no selection"/"pending" chip) -- shown immediately regardless
    of whether a judging window ever reaches it."""
    inventory_id = _inventory_id_for_job(conn, job_id)
    candidates = shortlist_units(conn, inventory_id, requirement_text, embedding_client, top_k)
    for c in candidates:
        conn.execute(
            "INSERT INTO judgment (requirement_id, unit_id, score, model_verdict) VALUES (?, ?, ?, NULL)",
            (requirement_id, c.unit_id, c.score),
        )
    conn.commit()


def _candidates_for_requirement(conn: sqlite3.Connection, requirement_id: int) -> list[Candidate]:
    """Re-reads the already-shortlisted units' CURRENT text/fields (no
    snapshot) from the judgment rows attached at creation time. Never
    touches added_by_user rows -- those are the user's own assertion, not
    part of what the model judges."""
    rows = conn.execute(
        "SELECT j.unit_id, j.score, u.text, u.context, u.contribution, u.outcome, u.skills_json "
        "FROM judgment j JOIN unit u ON j.unit_id = u.id "
        "WHERE j.requirement_id = ? AND j.added_by_user = 0 ORDER BY j.score DESC",
        (requirement_id,),
    ).fetchall()
    return [
        Candidate(
            unit_id=r["unit_id"], text=r["text"], context=r["context"],
            contribution=r["contribution"], outcome=r["outcome"],
            skills=_parse_skills(r["skills_json"]), score=r["score"] or 0.0,
        )
        for r in rows
    ]


# Free-text model fields (quote, shows, needs) are never rejected for
# length (see judge_validation.py) -- a verbose answer is truncated here,
# for display only, instead of costing the requirement its whole result.
_DISPLAY_TRUNCATE_WORDS = 15


def _truncate_for_display(text: str, max_words: int = _DISPLAY_TRUNCATE_WORDS) -> str:
    words = text.split()
    if len(words) <= max_words:
        return text
    return " ".join(words[:max_words]) + "\u2026"


def _fold_quote_into_why(unit: JudgedUnit) -> str:
    quote = _truncate_for_display(unit.quote)
    shows = _truncate_for_display(unit.shows)
    needs = _truncate_for_display(unit.needs)
    composed = f"Shows: {shows}. Needs: {needs}."
    return f'"{quote}" — {composed}' if quote else composed


def _write_batch_result(
    conn: sqlite3.Connection, requirement_id: int, small_id: str, candidates: list[Candidate],
    result: JudgeResult, batch_seconds: float,
) -> None:
    """One requirement's valid result from a batch, written together with
    status='done' in its own transaction (§3). Never touches a judgment
    row the user has already set a verdict on. judge_seconds records the
    whole batch call's duration (not attributable per-requirement inside
    one shared call)."""
    judged_by_id = {u.id: u for u in result.units}
    for c in candidates:
        unit = judged_by_id.get(format_unit_id(small_id, c.unit_id))
        verdict = unit.v if unit is not None else "none"
        why = _fold_quote_into_why(unit) if unit is not None else None
        conn.execute(
            "UPDATE judgment SET model_verdict = ?, why = ? "
            "WHERE requirement_id = ? AND unit_id = ? AND added_by_user = 0 AND user_verdict IS NULL",
            (verdict, why, requirement_id, c.unit_id),
        )
    conn.execute(
        "UPDATE requirement SET status = 'done', reason = ?, last_error = NULL, "
        "judge_seconds = ?, judged_at = datetime('now') WHERE id = ?",
        (result.reason, batch_seconds, requirement_id),
    )
    conn.commit()


def _mark_pending_with_error(conn: sqlite3.Connection, requirement_id: int, last_error: str) -> None:
    """Stays 'pending' (there is no error status, §3); failure text saved
    for display. Never retried -- not from here, not by a later batch."""
    conn.execute("UPDATE requirement SET last_error = ? WHERE id = ?", (last_error, requirement_id))
    conn.commit()


def _ordered_pending_requirement_ids(conn: sqlite3.Connection, job_id: int) -> list[int]:
    rows = conn.execute(
        "SELECT id, weight, sort_order FROM requirement WHERE job_id = ? AND deleted = 0 AND status = 'pending'",
        (job_id,),
    ).fetchall()
    ordered = sorted(rows, key=lambda r: (_WEIGHT_ORDER.get(r["weight"], 99), r["sort_order"]))
    return [r["id"] for r in ordered]


def _salvage_partial_batch_results(raw: str) -> list[JudgeResult]:
    """Best-effort recovery when the batch response was cut off by
    max_tokens (finish_reason "length"): keeps whatever complete, valid
    per-requirement result objects appear before the point the text became
    incomplete. Runs once, on the whole (possibly truncated) text after
    the one call already ended -- not an incremental parser."""
    marker = '"results"'
    idx = raw.find(marker)
    if idx == -1:
        return []
    bracket = raw.find("[", idx)
    if bracket == -1:
        return []

    decoder = json.JSONDecoder()
    pos = bracket + 1
    results: list[JudgeResult] = []
    while True:
        while pos < len(raw) and raw[pos] in " \t\n\r,":
            pos += 1
        if pos >= len(raw) or raw[pos] == "]":
            break
        try:
            obj, pos = decoder.raw_decode(raw, pos)
        except json.JSONDecodeError:
            break  # the object starting at `pos` is incomplete -- stop here
        try:
            results.append(JudgeResult.model_validate(obj))
        except ValidationError:
            break  # malformed where a result object was expected -- stop here
    return results


# --- Cancellation: Finish/Back (user action) and the deadline (a timer)
# both just set the same threading.Event, checked once per streamed chunk.
# Only one window can be open across all jobs (§3 rule 5), so one shared
# slot is enough -- no per-job registry needed.

_window_lock = threading.Lock()
_active_job_id: Optional[int] = None
_active_cancel_event: Optional[threading.Event] = None


def _register_active_window(job_id: int, cancel_event: threading.Event) -> None:
    global _active_job_id, _active_cancel_event
    with _window_lock:
        _active_job_id = job_id
        _active_cancel_event = cancel_event


def _clear_active_window(job_id: int) -> None:
    global _active_job_id, _active_cancel_event
    with _window_lock:
        if _active_job_id == job_id:
            _active_job_id = None
            _active_cancel_event = None


def request_cancel(job_id: int) -> None:
    """Called by the Finish/Back endpoint. If this process is the one
    running that job's window, setting the event makes the in-flight
    batch call's per-chunk check bail immediately and write nothing. The
    caller still sets judging_deadline=now in the same action regardless
    -- that's what actually closes the window for every reader, including
    across a restart or a different process."""
    with _window_lock:
        if _active_job_id == job_id and _active_cancel_event is not None:
            _active_cancel_event.set()


def _run_batch_call(llm_client: LLMClient, message: str, cancel_event: threading.Event):
    """Consumes complete_stream chunk by chunk (so Finish/Back/the
    deadline timer can interrupt it by setting cancel_event, which closes
    the underlying connection via complete_stream's own finally), but
    treats the result as a single non-streaming document: every delta is
    only accumulated, never parsed, until the stream ends. Returns
    (raw_text, metrics, seconds_to_first_content_chunk) on a clean finish,
    or (None, None, None) if cancelled or timed out before finishing --
    meaning nothing should be written. seconds_to_first_content_chunk is
    the time to the first chunk with visible .content (delta events are
    only ever yielded for those) -- distinct from
    metrics.seconds_to_first_chunk, which the client measures from the
    very first streamed chunk of any kind, including a content-less
    reasoning-only chunk under /think. None if no delta ever arrived."""
    start = time.monotonic()
    first_content_chunk_at: Optional[float] = None
    gen = llm_client.complete_stream(JUDGE_BATCH, message)
    try:
        for event in gen:
            if cancel_event.is_set():
                gen.close()
                return None, None, None
            if event[0] == "delta":
                if first_content_chunk_at is None:
                    first_content_chunk_at = time.monotonic()
                continue  # accumulation happens via the final "done" event below
            _, raw, metrics = event
            seconds_to_first_content_chunk = (
                (first_content_chunk_at - start) if first_content_chunk_at is not None else None
            )
            return raw, metrics, seconds_to_first_content_chunk
    except LlmTimeout:
        return None, None, None
    return None, None, None  # generator ended without a "done" event -- shouldn't happen


def _process_batch(
    conn: sqlite3.Connection, job_id: int, requirement_rows: list[sqlite3.Row],
    llm_client: LLMClient, cancel_event: threading.Event,
) -> int:
    """One batch call covering these requirements. Returns how many were
    written 'done'. Writes nothing at all if the call was cancelled."""
    batch_start = _utcnow()
    requirement_ids = [row["id"] for row in requirement_rows]
    small_id_to_row: dict[str, sqlite3.Row] = {}
    candidates_by_small_id: dict[str, list[Candidate]] = {}
    batch_payload: list[tuple[str, str, list[Candidate]]] = []

    for i, row in enumerate(requirement_rows, start=1):
        small_id = str(i)
        candidates = _candidates_for_requirement(conn, row["id"])
        small_id_to_row[small_id] = row
        candidates_by_small_id[small_id] = candidates
        batch_payload.append((small_id, row["text"], candidates))

    message = build_judge_batch_message(batch_payload)
    raw, metrics, seconds_to_first_content_chunk = _run_batch_call(llm_client, message, cancel_event)

    if raw is None:
        logger.info(
            "job %d: batch of requirements %s (start=%s) cancelled or timed out, writing nothing",
            job_id, requirement_ids, batch_start,
        )
        return 0

    try:
        parsed = JUDGE_BATCH.response_model.model_validate_json(raw)
        all_results = parsed.results
    except ValidationError:
        all_results = _salvage_partial_batch_results(raw)

    results_by_small_id = {r.req_id: r for r in all_results}

    written = 0
    for small_id, row in small_id_to_row.items():
        result = results_by_small_id.get(small_id)
        candidates = candidates_by_small_id[small_id]
        if result is None:
            _mark_pending_with_error(conn, row["id"], "Not included in the batch response (cut off or missing).")
            continue

        haystacks = build_candidate_haystacks(small_id, candidates)
        candidate_ids = set(haystacks.keys())
        errors = validate_judge(result, candidate_ids=candidate_ids, haystacks=haystacks)
        if errors:
            _mark_pending_with_error(conn, row["id"], "; ".join(errors))
            continue

        _write_batch_result(conn, row["id"], small_id, candidates, result, metrics.seconds if metrics else 0.0)
        written += 1

    # Throughput over the whole generation phase, from the very first
    # streamed chunk of any kind (including a content-less reasoning-only
    # chunk under /think) to the end -- not just from the first visible
    # content chunk, which would exclude however long thinking took and
    # make throughput look faster than it actually was. reasoning_tokens
    # and completion_tokens are separate pools (per CallMetrics), so both
    # are counted.
    tokens_per_second = None
    seconds_to_first_chunk = metrics.seconds_to_first_chunk if metrics else None
    if metrics and seconds_to_first_chunk is not None:
        generation_seconds = metrics.seconds - seconds_to_first_chunk
        total_tokens = metrics.completion_tokens + (metrics.reasoning_tokens or 0)
        if generation_seconds > 0:
            tokens_per_second = total_tokens / generation_seconds

    valid_results = len(all_results)
    logger.info(
        "job %d: batch of requirements %s (start=%s) -> %d written (%d valid results), finish_reason=%s, "
        "prompt_tokens=%s, completion_tokens=%s, reasoning_tokens=%s, seconds_total=%.2f, "
        "seconds_to_first_chunk=%s, seconds_to_first_content_chunk=%s, tokens_per_s=%s",
        job_id, requirement_ids, batch_start, written, valid_results,
        metrics.finish_reason if metrics else None,
        metrics.prompt_tokens if metrics else None, metrics.completion_tokens if metrics else None,
        metrics.reasoning_tokens if metrics else None,
        metrics.seconds if metrics else 0.0,
        f"{seconds_to_first_chunk:.2f}" if seconds_to_first_chunk is not None else None,
        f"{seconds_to_first_content_chunk:.2f}" if seconds_to_first_content_chunk is not None else None,
        f"{tokens_per_second:.2f}" if tokens_per_second is not None else None,
    )
    if metrics and metrics.finish_reason == "length" and valid_results == 0:
        logger.info(
            "job %d: batch hit max_tokens with ZERO valid results -- all %d requirements go back to pending "
            "with a cut-off error (completion_tokens=%s, max_tokens=%s)",
            job_id, len(requirement_rows), metrics.completion_tokens, settings.judge_max_tokens,
        )
    return written


def run_judging_window(
    db_path: str, job_id: int, llm_client: LLMClient, model: str,
    now_fn: Callable[[], datetime] = _utcnow,
) -> None:
    """The whole 20-minute window for one job: batches of judge_batch_size
    requirements, weight-then-position order, refusing to start a new
    batch with less than judge_start_min_left minutes left. Opens its own
    connection -- intended to run detached from the request that
    triggered it (see routers), via a background task.

    now_fn drives both the persisted deadline and this function's own
    "how much time is left" decisions, so a test can inject a fake,
    manually-advanceable clock to exercise the 9-minute-left and
    deadline-respecting rules without any real waiting. Defaults to the
    real wall clock -- the same one job.judging_deadline is always
    compared against by every other guard (ensure_model_not_busy,
    is_job_window_open), so production behavior is unaffected."""
    conn = connect(db_path)
    try:
        window_start = time.monotonic()
        start = now_fn()
        deadline = start + timedelta(minutes=JUDGING_WINDOW_MINUTES)
        conn.execute(
            "UPDATE job SET judging_started_at = ?, judging_deadline = ? WHERE id = ?",
            (start.strftime(_DT_FORMAT), deadline.strftime(_DT_FORMAT), job_id),
        )
        conn.commit()

        cancel_event = threading.Event()
        _register_active_window(job_id, cancel_event)
        total_written = 0
        total_attempted = 0
        try:
            pending_ids = _ordered_pending_requirement_ids(conn, job_id)
            chunk_size = settings.judge_batch_size
            chunks = [pending_ids[i : i + chunk_size] for i in range(0, len(pending_ids), chunk_size)]

            for chunk_ids in chunks:
                if cancel_event.is_set():
                    break

                remaining_s = (deadline - now_fn()).total_seconds()
                if remaining_s < settings.judge_start_min_left * 60:
                    logger.info(
                        "job %d: %.0fs left (< judge_start_min_left), stopping before this batch", job_id, remaining_s,
                    )
                    break

                rows = [
                    conn.execute(
                        "SELECT * FROM requirement WHERE id = ? AND deleted = 0 AND status = 'pending'", (rid,)
                    ).fetchone()
                    for rid in chunk_ids
                ]
                rows = [r for r in rows if r is not None]
                if not rows:
                    continue

                timer = threading.Timer(max(remaining_s, 0.0), cancel_event.set)
                timer.start()
                try:
                    total_attempted += len(rows)
                    try:
                        total_written += _process_batch(conn, job_id, rows, llm_client, cancel_event)
                    except Exception as e:
                        # A batch failing must never take the rest of the
                        # window down with it (the Mishipay bug: an
                        # unhandled exception here used to propagate out of
                        # this whole function, silently killing every later
                        # batch with no last_error recorded anywhere).
                        # Record what happened and move on to the next chunk.
                        logger.exception(
                            "job %d: batch of requirements %s raised an unexpected error",
                            job_id, [row["id"] for row in rows],
                        )
                        error_text = f"{type(e).__name__}: {e}"
                        for row in rows:
                            _mark_pending_with_error(conn, row["id"], f"Batch call raised an unexpected error: {error_text}")
                finally:
                    timer.cancel()

            if total_attempted:
                record_run_timing(
                    conn, phase="judging", mode="batch", model=model, thinking=settings.judge_batch_thinking,
                    prompt_version=JUDGE_BATCH.prompt_version, items=total_attempted,
                    batch_size=settings.judge_batch_size, seconds_total=time.monotonic() - window_start,
                )

            # Close the window the moment the loop has nothing more to try
            # this run -- every requirement done, or the judge_start_min_left
            # floor refused another batch -- rather than leaving
            # judging_deadline at the original start+20min with the
            # blocking dialog up for no reason. The only case that does NOT
            # close here is cancellation (Finish/Back already closed it via
            # finish_window, or the deadline timer already passed).
            if not cancel_event.is_set():
                conn.execute(
                    "UPDATE job SET judging_deadline = ? WHERE id = ?",
                    (now_fn().strftime(_DT_FORMAT), job_id),
                )
                conn.commit()
        except Exception:
            # Anything else that still manages to escape (not a single
            # batch's own call, which is now caught above, but something in
            # the surrounding bookkeeping) must not leave a dead window
            # looking "open" forever -- force it closed before re-raising.
            logger.exception("job %d: run_judging_window exiting on an unhandled exception", job_id)
            conn.execute(
                "UPDATE job SET judging_deadline = ? WHERE id = ?",
                (now_fn().strftime(_DT_FORMAT), job_id),
            )
            conn.commit()
            raise
        finally:
            _clear_active_window(job_id)
    finally:
        conn.close()


def is_any_window_open(conn: sqlite3.Connection) -> bool:
    """§3 rule 5: only one window across all jobs. Checked before any
    action that would call LM Studio."""
    row = conn.execute("SELECT 1 FROM job WHERE judging_deadline > datetime('now') LIMIT 1").fetchone()
    return row is not None


def is_job_window_open(conn: sqlite3.Connection, job_id: int) -> bool:
    """§3's edit block is scoped to the owning job's own window, not the
    global one-window rule (another job's past window closing doesn't
    block edits on jobs that were never in a window)."""
    row = conn.execute(
        "SELECT 1 FROM job WHERE id = ? AND judging_deadline > datetime('now')", (job_id,)
    ).fetchone()
    return row is not None


def ensure_model_not_busy(conn: sqlite3.Connection) -> None:
    """Guard for every endpoint that calls LM Studio (extraction, resume
    ingestion, re-embedding edits) -- not just the judging window itself."""
    if is_any_window_open(conn):
        raise HTTPException(409, "A judging window is open on another job. Try again once it finishes.")


def ensure_job_not_judging(conn: sqlite3.Connection, job_id: int) -> None:
    """Guard for the edit-block endpoints (§3's edit block): verdict
    changes, add/edit/delete requirement, attach unit, No match, Proceed."""
    if is_job_window_open(conn, job_id):
        raise HTTPException(409, "Judging is in progress for this job. Try again once it finishes.")


def has_judging_started(conn: sqlite3.Connection, job_id: int) -> bool:
    """Judging no longer starts automatically after extraction (a review
    step comes first) -- this is "has it ever started", not "is it
    running now": true once judging_deadline is set (whether the window
    is currently open or already closed), or -- for jobs that already
    went through the old automatic-start path before this existed, where
    judging_deadline is reliably set too, but checked here as a second,
    independent signal rather than relying on that alone -- once the model
    has actually judged something (a judgment row with model_verdict set).
    Checking model_verdict rather than requirement.status: a manual action
    taken during the review step (No match, attach-unit, setting a verdict
    by hand) also sets a requirement's status to 'done' with no judging
    ever having run, and must not make this look like it already started.
    Used only to make "Start judging" a one-time action; no new column, no
    migration."""
    row = conn.execute(
        "SELECT 1 FROM job j WHERE j.id = ? AND ("
        "  j.judging_deadline IS NOT NULL"
        "  OR EXISTS ("
        "    SELECT 1 FROM judgment g JOIN requirement r ON r.id = g.requirement_id "
        "    WHERE r.job_id = j.id AND g.model_verdict IS NOT NULL"
        "  )"
        ") LIMIT 1",
        (job_id,),
    ).fetchone()
    return row is not None


def unjudged_requirement_count(conn: sqlite3.Connection, job_id: int) -> int:
    """Proceed's completion gate: a non-deleted requirement with no
    judgment row carrying a model_verdict or user_verdict -- covers both
    a requirement still truly 'pending' and one that was never even
    shortlisted (zero judgment rows). A requirement with only 'none'
    selections (e.g. after No match) still counts as judged here: 'none'
    is itself a recorded verdict (a deliberate gap), not an omission."""
    row = conn.execute(
        "SELECT COUNT(*) AS c FROM requirement r WHERE r.job_id = ? AND r.deleted = 0 "
        "AND NOT EXISTS ("
        "  SELECT 1 FROM judgment j WHERE j.requirement_id = r.id "
        "  AND (j.model_verdict IS NOT NULL OR j.user_verdict IS NOT NULL)"
        ")",
        (job_id,),
    ).fetchone()
    return row["c"]


def finish_window(conn: sqlite3.Connection, job_id: int) -> None:
    """Finish button, or Back navigating away while a window is open:
    cancels the in-flight call (if this process is running it) and closes
    the window immediately."""
    request_cancel(job_id)
    conn.execute("UPDATE job SET judging_deadline = datetime('now') WHERE id = ?", (job_id,))
    conn.commit()


def close_open_judging_windows(db_path: str) -> None:
    """Startup hook (app/main.py's lifespan): no job can have a running
    judging task in this fresh process -- a window's background task
    never survives a restart (whether the restart was intended, or the
    task was killed mid-run, e.g. by a dev --reload picking up a file
    change). A judging_deadline still in the future would otherwise keep
    reading as "running" (now < judging_deadline) until real wall-clock
    time happened to catch up, leaving the job's edit-block lock stuck
    open for however long was left. Closes it immediately instead --
    releasing the lock -- and leaves every requirement's own status
    (including whatever's still 'pending') untouched; this is a lock
    release, not a retry or a completion."""
    conn = connect(db_path)
    try:
        stuck = conn.execute(
            "SELECT id FROM job WHERE judging_deadline IS NOT NULL AND judging_deadline > datetime('now')"
        ).fetchall()
        if stuck:
            logger.info(
                "startup: releasing %d job(s) whose judging window was still open with no task running: %s",
                len(stuck), [row["id"] for row in stuck],
            )
        conn.execute(
            "UPDATE job SET judging_deadline = datetime('now') "
            "WHERE judging_deadline IS NOT NULL AND judging_deadline > datetime('now')"
        )
        conn.commit()
    finally:
        conn.close()


def mark_done_if_pending(conn: sqlite3.Connection, requirement_id: int) -> None:
    """Manual mode: there is no separate "Done" action -- a status set by
    its own dedicated click carries no information the verdicts
    themselves don't already have. Instead, the first real verdict the
    user sets on a requirement (a chip click, or attaching a unit, which
    sets one) is what completes it. A requirement with no candidates at
    all, or one a user never touches, stays pending -- a gap is a normal,
    expected outcome (CLAUDE.md principle 4), not something that needs a
    dedicated action to close out."""
    conn.execute("UPDATE requirement SET status = 'done' WHERE id = ? AND status = 'pending'", (requirement_id,))
    conn.commit()


def wipe_job_requirements(conn: sqlite3.Connection, job_id: int) -> None:
    """JD resubmission (§3.1): discards this job's requirements,
    judgments, pairs, statements, thread data, and the letter -- units and
    their enrichment (inventory) are untouched. Hard delete, not soft:
    this is a full restart of the job's matching state, not a user-facing
    single-item delete. Pairs/statements/threads/letter all go too (§6,
    §7, §9): they're all derived from this job's matched units and
    requirements, which a resubmission can completely change.

    Also resets judging_deadline/judging_started_at to NULL -- without
    this, has_judging_started() kept reading the previous run's stale
    deadline as "judging already started" on the brand-new requirements
    this creates, permanently hiding Start judging after any resubmit
    that followed a real judging run (bug: Start judging disappears after
    editing the JD and resubmitting)."""
    conn.execute("UPDATE job SET judging_deadline = NULL, judging_started_at = NULL WHERE id = ?", (job_id,))
    conn.execute("DELETE FROM letter WHERE job_id = ?", (job_id,))
    conn.execute(
        "DELETE FROM judgment WHERE requirement_id IN (SELECT id FROM requirement WHERE job_id = ?)", (job_id,)
    )
    conn.execute("DELETE FROM requirement WHERE job_id = ?", (job_id,))
    conn.execute(
        "DELETE FROM thread_unit WHERE thread_id IN "
        "(SELECT id FROM thread WHERE run_id IN (SELECT id FROM thread_run WHERE job_id = ?))", (job_id,)
    )
    conn.execute(
        "DELETE FROM thread_statement WHERE thread_id IN "
        "(SELECT id FROM thread WHERE run_id IN (SELECT id FROM thread_run WHERE job_id = ?))", (job_id,)
    )
    # job_thread.thread_id references thread(id) -- must be deleted before
    # the thread rows themselves, or this raises a FOREIGN KEY constraint
    # error whenever a primary/secondary choice was ever made for this job.
    conn.execute("DELETE FROM job_thread WHERE job_id = ?", (job_id,))
    conn.execute(
        "DELETE FROM thread WHERE run_id IN (SELECT id FROM thread_run WHERE job_id = ?)", (job_id,)
    )
    conn.execute("DELETE FROM thread_run WHERE job_id = ?", (job_id,))
    conn.execute("DELETE FROM statement WHERE pair_id IN (SELECT id FROM pair WHERE job_id = ?)", (job_id,))
    conn.execute("DELETE FROM pair WHERE job_id = ?", (job_id,))
    conn.commit()
