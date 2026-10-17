"""Milestone 5: primary/secondary ranking.
Deterministic, no LLM calls. Candidates = non-deleted threads from the
latest run meeting min_support, plus user-written threads (any run,
exempt from min_support -- §8 point 9)."""

import sqlite3

from app.verdicts import effective_verdict

WEIGHT_VALUE = {"high": 3, "medium": 2, "low": 1}


def thread_unit_ids(conn: sqlite3.Connection, thread_id: int) -> set[int]:
    """"A thread's units = the union of the units of its supporting
    statements" -- recomputed from thread_statement/pair every time, so
    it's always correct even after a move/remove that didn't touch
    thread_unit (the verified-quote cache)."""
    unit_ids: set[int] = set()
    for row in conn.execute(
        "SELECT p.unit_a_id, p.unit_b_id FROM thread_statement ts "
        "JOIN statement s ON s.id = ts.statement_id JOIN pair p ON p.id = s.pair_id "
        "WHERE ts.thread_id = ?",
        (thread_id,),
    ).fetchall():
        unit_ids.update((row["unit_a_id"], row["unit_b_id"]))
    return unit_ids


def covered_and_uncovered(conn: sqlite3.Connection, job_id: int, unit_ids: set[int]) -> tuple[list, list]:
    requirements = conn.execute(
        "SELECT * FROM requirement WHERE job_id = ? AND deleted = 0 ORDER BY sort_order", (job_id,)
    ).fetchall()
    covered, uncovered = [], []
    for req in requirements:
        judgments = conn.execute("SELECT * FROM judgment WHERE requirement_id = ?", (req["id"],)).fetchall()
        hit = any(j["unit_id"] in unit_ids and effective_verdict(j) in ("match", "weak") for j in judgments)
        (covered if hit else uncovered).append(req)
    return covered, uncovered


def _candidate_threads(conn: sqlite3.Connection, job_id: int) -> list[sqlite3.Row]:
    latest_run = conn.execute(
        "SELECT id FROM thread_run WHERE job_id = ? ORDER BY id DESC LIMIT 1", (job_id,)
    ).fetchone()

    candidates: list[sqlite3.Row] = []
    seen_ids: set[int] = set()
    if latest_run:
        # §7/milestone 7 part B: below_min is a persisted, sticky flag --
        # ranking ignores a thread until the user promotes it ("Use
        # anyway"), independent of whatever min_support is set to now.
        for t in conn.execute(
            "SELECT * FROM thread WHERE run_id = ? AND deleted = 0 AND source = 'model' AND below_min = 0",
            (latest_run["id"],),
        ).fetchall():
            candidates.append(t)
            seen_ids.add(t["id"])

    for t in conn.execute(
        "SELECT t.* FROM thread t JOIN thread_run r ON r.id = t.run_id "
        "WHERE r.job_id = ? AND t.deleted = 0 AND t.source = 'user'",
        (job_id,),
    ).fetchall():
        if t["id"] not in seen_ids:
            candidates.append(t)
            seen_ids.add(t["id"])

    return candidates


def rank_candidates(conn: sqlite3.Connection, job_id: int) -> list[dict]:
    """Returns ranked dicts: {thread, unit_ids, covered, uncovered, score,
    support_count}, highest first. Tie-break: more supporting statements,
    then lower thread id (§8 point 3)."""
    scored = []
    for t in _candidate_threads(conn, job_id):
        unit_ids = thread_unit_ids(conn, t["id"])
        covered, uncovered = covered_and_uncovered(conn, job_id, unit_ids)
        support_count = conn.execute(
            "SELECT COUNT(*) AS n FROM thread_statement WHERE thread_id = ?", (t["id"],)
        ).fetchone()["n"]
        score = sum(WEIGHT_VALUE.get(r["weight"], 0) for r in covered)
        scored.append({
            "thread": t, "unit_ids": unit_ids, "covered": covered, "uncovered": uncovered,
            "score": score, "support_count": support_count,
        })
    scored.sort(key=lambda s: (-s["score"], -s["support_count"], s["thread"]["id"]))
    return scored


def get_choice(conn: sqlite3.Connection, job_id: int, role: str) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM job_thread WHERE job_id = ? AND role = ?", (job_id, role)).fetchone()


def set_choice(conn: sqlite3.Connection, job_id: int, role: str, thread_id: int) -> None:
    conn.execute("DELETE FROM job_thread WHERE job_id = ? AND role = ?", (job_id, role))
    conn.execute("INSERT INTO job_thread (job_id, thread_id, role) VALUES (?, ?, ?)", (job_id, thread_id, role))


def clear_choice(conn: sqlite3.Connection, job_id: int, role: str) -> None:
    conn.execute("DELETE FROM job_thread WHERE job_id = ? AND role = ?", (job_id, role))


def suggest_and_persist(conn: sqlite3.Connection, job_id: int) -> list[dict]:
    """"Suggest again": recomputes the ranking and resets the choice to
    the top two (§8 point 7) -- this is the only thing that overwrites an
    existing choice."""
    ranked = rank_candidates(conn, job_id)
    clear_choice(conn, job_id, "primary")
    clear_choice(conn, job_id, "secondary")
    if ranked:
        set_choice(conn, job_id, "primary", ranked[0]["thread"]["id"])
    if len(ranked) > 1:
        set_choice(conn, job_id, "secondary", ranked[1]["thread"]["id"])
    conn.commit()
    return ranked
