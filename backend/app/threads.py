"""Milestone 4: thread discovery. The model only
proposes; every rule that decides what survives runs in code
(app/llm/thread_validation.py). No retries, no fallbacks -- one call per
step, any exception ends the run cleanly with the error recorded."""

import json
import logging
import sqlite3
import time
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Optional

from app.config import settings
from app.llm.base import CallMetrics, LLMClient
from app.llm.schemas import AssignUnusedResult, ProposeThreadsResult, VerifyThreadResult
from app.llm.tasks import ASSIGN_UNUSED, PROPOSE_THREADS, VERIFY_THREAD
from app.llm.thread_validation import clean_proposed_threads, quote_or_none
from app.run_timing import record_run_timing
from app.thread_input import build_assign_unused_message, build_propose_threads_message, build_verify_thread_message

logger = logging.getLogger("job_friend.threads")
logger.setLevel(logging.INFO)

# Reuse the same rotating log file judging.py writes to ("the existing
# log") rather than starting a second one.
_LOG_FILE = Path(__file__).resolve().parent.parent / "logs" / "judging.log"
if not any(
    isinstance(h, RotatingFileHandler) and getattr(h, "baseFilename", None) == str(_LOG_FILE)
    for h in logger.handlers
):
    _LOG_FILE.parent.mkdir(exist_ok=True)
    _file_handler = RotatingFileHandler(_LOG_FILE, maxBytes=5_000_000, backupCount=3)
    _file_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.addHandler(_file_handler)


def _run_call(llm_client: LLMClient, task, message: str) -> tuple[str, Optional[CallMetrics]]:
    """Consumes complete_stream as one document (no incremental parsing),
    same as judging.py's batch call. Raises whatever the client raises --
    the caller (run_thread_discovery) is the one try/except boundary."""
    accumulated = ""
    metrics = None
    for event in llm_client.complete_stream(task, message):
        if event[0] == "delta":
            continue
        _, accumulated, metrics = event
    return accumulated, metrics


def _log_call(task_name: str, metrics: Optional[CallMetrics]) -> None:
    logger.info(
        "thread task=%s prompt_tokens=%s completion_tokens=%s seconds=%s finish_reason=%s",
        task_name,
        metrics.prompt_tokens if metrics else None,
        metrics.completion_tokens if metrics else None,
        f"{metrics.seconds:.2f}" if metrics else None,
        metrics.finish_reason if metrics else None,
    )


def gather_written_statements(conn: sqlite3.Connection, job_id: int) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT s.id, s.text FROM statement s JOIN pair p ON p.id = s.pair_id "
        "WHERE p.job_id = ? AND s.status = 'written' ORDER BY s.id",
        (job_id,),
    ).fetchall()


def mark_threads_stale_for_statement(conn: sqlite3.Connection, statement_id: int) -> None:
    """§7: "mark a thread stale when any of its statements is edited after
    the run." Applies across every run that ever used this statement, not
    just the latest -- old runs stay viewable, so their staleness should
    be honest too."""
    conn.execute(
        "UPDATE thread SET stale = 1 WHERE id IN (SELECT thread_id FROM thread_statement WHERE statement_id = ?)",
        (statement_id,),
    )


def run_thread_discovery(conn: sqlite3.Connection, job_id: int, llm_client: LLMClient, model: str) -> int:
    statements = gather_written_statements(conn, job_id)
    small_id_map = {str(i): row["id"] for i, row in enumerate(statements, start=1)}
    text_by_small = {str(i): row["text"] for i, row in enumerate(statements, start=1)}

    params = {
        "n_threads": settings.n_threads,
        "min_support": settings.min_support,
        "model": model,
        "prompt_versions": {
            "propose_threads": PROPOSE_THREADS.prompt_version,
            "assign_unused": ASSIGN_UNUSED.prompt_version,
            "verify_thread": VERIFY_THREAD.prompt_version,
        },
    }
    snapshot = [{"id": sid, "text": text_by_small[sid]} for sid in small_id_map]

    cursor = conn.execute(
        "INSERT INTO thread_run (job_id, params_json, statements_snapshot_json) VALUES (?, ?, ?)",
        (job_id, json.dumps(params), json.dumps(snapshot)),
    )
    run_id = cursor.lastrowid
    # Committed on its own: even if everything after this fails, the run
    # itself (and whatever error gets attached to it) must survive.
    conn.commit()

    total_seconds = 0.0

    try:
        if not small_id_map:
            return run_id

        propose_message = build_propose_threads_message([(sid, text_by_small[sid]) for sid in small_id_map])
        raw, metrics = _run_call(llm_client, PROPOSE_THREADS, propose_message)
        if metrics:
            total_seconds += metrics.seconds
        _log_call("propose_threads", metrics)
        parsed = ProposeThreadsResult.model_validate_json(raw)

        cleaned = clean_proposed_threads(parsed, set(small_id_map.keys()))
        # §7 extended by milestone 7 part B: a thread under min_support is
        # no longer dropped -- it's persisted flagged (below_min=1) instead,
        # and only full-strength threads are offered as assign_unused
        # targets (a below_min thread isn't a valid home until promoted).
        thread_entries: list[dict] = []
        proposed_count = 0
        for idea, ids in cleaned:
            below_min = len(ids) < settings.min_support
            if below_min:
                logger.info("propose_threads: thread %r has only %d statement(s) (< min_support), keeping as below_min", idea, len(ids))
            thread_entries.append({"idea": idea, "ids": list(ids), "assigned_ids": [], "below_min": below_min})
            proposed_count += len(ids)

        used_ids = {sid for t in thread_entries for sid in t["ids"]}
        unused_ids = [sid for sid in small_id_map if sid not in used_ids]
        assignable = [t for t in thread_entries if not t["below_min"]]

        moved_count = 0
        removed_count = 0
        for sid in unused_ids:
            if not assignable:
                removed_count += 1
                continue
            threads_for_prompt = [(str(i), t["idea"]) for i, t in enumerate(assignable, start=1)]
            message = build_assign_unused_message(threads_for_prompt, sid, text_by_small[sid])
            raw, metrics = _run_call(llm_client, ASSIGN_UNUSED, message)
            if metrics:
                total_seconds += metrics.seconds
            _log_call("assign_unused", metrics)
            assigned = AssignUnusedResult.model_validate_json(raw)
            if assigned.thread == "none":
                removed_count += 1
                continue
            try:
                idx = int(assigned.thread) - 1
            except ValueError:
                idx = -1
            if 0 <= idx < len(assignable):
                assignable[idx]["ids"].append(sid)
                assignable[idx]["assigned_ids"].append(sid)
                moved_count += 1
            else:
                logger.info("assign_unused: statement %r got an unknown thread id %r, leaving unassigned", sid, assigned.thread)
                removed_count += 1

        conn.execute(
            "UPDATE thread_run SET proposed_count = ?, moved_count = ?, removed_count = ? WHERE id = ?",
            (proposed_count, moved_count, removed_count, run_id),
        )

        thread_db_ids = []
        for t in thread_entries:
            cur = conn.execute(
                "INSERT INTO thread (run_id, idea, source, below_min) VALUES (?, ?, 'model', ?)",
                (run_id, t["idea"], int(t["below_min"])),
            )
            thread_db_ids.append(cur.lastrowid)
            assigned_set = set(t["assigned_ids"])
            for sid in t["ids"]:
                origin = "assigned" if sid in assigned_set else "proposed"
                conn.execute(
                    "INSERT INTO thread_statement (thread_id, statement_id, origin) VALUES (?, ?, ?)",
                    (thread_db_ids[-1], small_id_map[sid], origin),
                )

        for thread_db_id, t in zip(thread_db_ids, thread_entries):
            # A thread's units = the union of the units of its supporting
            # statements' pairs (mechanical, no model -- §7).
            unit_ids: set[int] = set()
            for sid in t["ids"]:
                pair_row = conn.execute(
                    "SELECT p.unit_a_id, p.unit_b_id FROM pair p JOIN statement s ON s.pair_id = p.id WHERE s.id = ?",
                    (small_id_map[sid],),
                ).fetchone()
                unit_ids.update((pair_row["unit_a_id"], pair_row["unit_b_id"]))

            for unit_id in sorted(unit_ids):
                unit_text = conn.execute("SELECT text FROM unit WHERE id = ?", (unit_id,)).fetchone()["text"]
                message = build_verify_thread_message(t["idea"], unit_text)
                raw, metrics = _run_call(llm_client, VERIFY_THREAD, message)
                if metrics:
                    total_seconds += metrics.seconds
                _log_call("verify_thread", metrics)
                verified = VerifyThreadResult.model_validate_json(raw)
                quote = quote_or_none(verified.quote, unit_text)
                conn.execute(
                    "INSERT INTO thread_unit (thread_id, unit_id, model_verdict, quote) VALUES (?, ?, ?, ?)",
                    (thread_db_id, unit_id, verified.verdict, quote),
                )

        conn.execute("UPDATE thread_run SET seconds_total = ? WHERE id = ?", (total_seconds, run_id))
        record_run_timing(
            conn, phase="threads", model=model, thinking=settings.thread_thinking,
            prompt_version=PROPOSE_THREADS.prompt_version, items=len(statements), seconds_total=total_seconds,
        )
        conn.commit()
        return run_id
    except Exception as e:
        conn.rollback()
        logger.exception("job %d thread_run %d failed", job_id, run_id)
        conn.execute("UPDATE thread_run SET error = ? WHERE id = ?", (f"{type(e).__name__}: {e}", run_id))
        conn.commit()
        return run_id
