"""Milestone 5: primary/secondary ranking. Pure
scoring tests + persistence/endpoint tests. No LLM calls anywhere here."""

import json

from app.config import settings
from app.db import connect
from app.thread_ranking import rank_candidates


def setup_job(db_path: str) -> int:
    conn = connect(db_path)
    conn.execute("INSERT INTO profile (name) VALUES ('p')")
    conn.execute("INSERT INTO inventory (profile_id, name) VALUES (1, 'inv')")
    conn.execute("INSERT INTO role (inventory_id, company, title, sort_order) VALUES (1, 'c', 't', 0)")
    conn.execute("INSERT INTO flow (profile_id, name, inventory_id) VALUES (1, 'f', 1)")
    conn.execute("INSERT INTO job (flow_id, title, jd_text) VALUES (1, 'job', 'jd')")
    job_id = conn.execute("SELECT id FROM job ORDER BY id DESC LIMIT 1").fetchone()["id"]
    conn.commit()
    conn.close()
    return job_id


def add_pair_with_statement(db_path: str, job_id: int, text: str = "s") -> tuple[int, int, int]:
    """Returns (statement_id, unit_a_id, unit_b_id)."""
    conn = connect(db_path)
    conn.execute("INSERT INTO unit (role_id, text, source, sort_order) VALUES (1, 'unit a', 'manual', 0)")
    unit_a = conn.execute("SELECT id FROM unit ORDER BY id DESC LIMIT 1").fetchone()["id"]
    conn.execute("INSERT INTO unit (role_id, text, source, sort_order) VALUES (1, 'unit b', 'manual', 1)")
    unit_b = conn.execute("SELECT id FROM unit ORDER BY id DESC LIMIT 1").fetchone()["id"]
    conn.execute(
        "INSERT INTO pair (job_id, unit_a_id, unit_b_id, score, model) VALUES (?, ?, ?, 0.5, 'm')",
        (job_id, unit_a, unit_b),
    )
    pair_id = conn.execute("SELECT id FROM pair ORDER BY id DESC LIMIT 1").fetchone()["id"]
    conn.execute("INSERT INTO statement (pair_id, status, text) VALUES (?, 'written', ?)", (pair_id, text))
    statement_id = conn.execute("SELECT id FROM statement ORDER BY id DESC LIMIT 1").fetchone()["id"]
    conn.commit()
    conn.close()
    return statement_id, unit_a, unit_b


def add_requirement_judgment(db_path: str, job_id: int, unit_id: int, weight: str, model_verdict: str, user_verdict=None):
    conn = connect(db_path)
    conn.execute(
        "INSERT INTO requirement (job_id, text, weight, source, status, sort_order) "
        "VALUES (?, 'req', ?, 'extracted', 'done', 0)", (job_id, weight),
    )
    requirement_id = conn.execute("SELECT id FROM requirement ORDER BY id DESC LIMIT 1").fetchone()["id"]
    conn.execute(
        "INSERT INTO judgment (requirement_id, unit_id, model_verdict, user_verdict) VALUES (?, ?, ?, ?)",
        (requirement_id, unit_id, model_verdict, user_verdict),
    )
    conn.commit()
    conn.close()
    return requirement_id


def make_model_thread(
    db_path: str, job_id: int, idea: str, statement_ids: list[int], run_id: int | None = None, below_min: bool = False,
) -> int:
    conn = connect(db_path)
    if run_id is None:
        conn.execute("INSERT INTO thread_run (job_id, params_json, statements_snapshot_json) VALUES (?, '{}', '[]')", (job_id,))
        run_id = conn.execute("SELECT id FROM thread_run ORDER BY id DESC LIMIT 1").fetchone()["id"]
    conn.execute("INSERT INTO thread (run_id, idea, source, below_min) VALUES (?, ?, 'model', ?)", (run_id, idea, int(below_min)))
    thread_id = conn.execute("SELECT id FROM thread ORDER BY id DESC LIMIT 1").fetchone()["id"]
    for sid in statement_ids:
        conn.execute("INSERT INTO thread_statement (thread_id, statement_id, origin) VALUES (?, ?, 'proposed')", (thread_id, sid))
    conn.commit()
    conn.close()
    return thread_id


def test_weights_and_tiebreak_by_support_count_then_id(db_path):
    job_id = setup_job(db_path)
    settings.min_support = 1
    try:
        s1, u1a, u1b = add_pair_with_statement(db_path, job_id, "s1")
        s2, u2a, u2b = add_pair_with_statement(db_path, job_id, "s2")
        s3, u3a, u3b = add_pair_with_statement(db_path, job_id, "s3")
        # Thread A: covers one "high" requirement (score 3) via u1a.
        add_requirement_judgment(db_path, job_id, u1a, "high", "match")
        thread_a = make_model_thread(db_path, job_id, "A", [s1])
        conn = connect(db_path)
        run_id = conn.execute("SELECT run_id FROM thread WHERE id = ?", (thread_a,)).fetchone()["run_id"]
        conn.close()
        # Thread B: covers one "medium" + one "low" requirement (score 3,
        # tied with A) via u2a/u2b, but fewer supporting statements isn't
        # the case here -- same count (1) as A, so tie-break falls to id;
        # make C explicitly worse to confirm ordering by score first.
        add_requirement_judgment(db_path, job_id, u2a, "medium", "match")
        add_requirement_judgment(db_path, job_id, u2b, "low", "match")
        thread_b = make_model_thread(db_path, job_id, "B", [s2], run_id=run_id)
        # Thread C: no covered requirements -- score 0, ranks last.
        thread_c = make_model_thread(db_path, job_id, "C", [s3], run_id=run_id)

        conn = connect(db_path)
        ranked = rank_candidates(conn, job_id)
        conn.close()

        scores = {r["thread"]["id"]: r["score"] for r in ranked}
        assert scores[thread_a] == 3
        assert scores[thread_b] == 3
        assert scores[thread_c] == 0
        order = [r["thread"]["id"] for r in ranked]
        # A and B tie on score (3) -- tie-break is support_count then id;
        # both have support_count=1, so lower id (A) comes first.
        assert order == [thread_a, thread_b, thread_c]
    finally:
        settings.min_support = 3


def test_effective_verdict_user_override_changes_coverage(db_path):
    job_id = setup_job(db_path)
    settings.min_support = 1
    try:
        s1, u1a, u1b = add_pair_with_statement(db_path, job_id, "s1")
        # model said "none" -- not covered -- but user overrode to "match".
        add_requirement_judgment(db_path, job_id, u1a, "high", "none", user_verdict="match")
        thread_id = make_model_thread(db_path, job_id, "A", [s1])

        conn = connect(db_path)
        ranked = rank_candidates(conn, job_id)
        conn.close()

        assert ranked[0]["score"] == 3  # the user override made it count
        assert len(ranked[0]["covered"]) == 1
    finally:
        settings.min_support = 3


def test_below_min_thread_is_excluded_until_promoted(db_path):
    """Milestone 7 part B point 7: ranking ignores below_min threads until
    the user promotes one -- a flag the thread run persisted, not a live
    recheck against the current min_support setting."""
    job_id = setup_job(db_path)
    s1, u1a, u1b = add_pair_with_statement(db_path, job_id, "s1")
    add_requirement_judgment(db_path, job_id, u1a, "high", "match")
    thread_id = make_model_thread(db_path, job_id, "Too small", [s1])
    conn = connect(db_path)
    conn.execute("UPDATE thread SET below_min = 1 WHERE id = ?", (thread_id,))
    conn.commit()
    conn.close()

    conn = connect(db_path)
    ranked = rank_candidates(conn, job_id)
    conn.close()
    assert ranked == []

    conn = connect(db_path)
    conn.execute("UPDATE thread SET below_min = 0 WHERE id = ?", (thread_id,))
    conn.commit()
    conn.close()

    conn = connect(db_path)
    ranked = rank_candidates(conn, job_id)
    conn.close()
    assert len(ranked) == 1
    assert ranked[0]["thread"]["id"] == thread_id


def test_user_written_thread_is_exempt_from_min_support(db_path):
    job_id = setup_job(db_path)
    s1, u1a, u1b = add_pair_with_statement(db_path, job_id, "s1")
    conn = connect(db_path)
    conn.execute("INSERT INTO thread_run (job_id, params_json, statements_snapshot_json) VALUES (?, '{}', '[]')", (job_id,))
    run_id = conn.execute("SELECT id FROM thread_run ORDER BY id DESC LIMIT 1").fetchone()["id"]
    conn.execute("INSERT INTO thread (run_id, idea, source) VALUES (?, 'Hand-written', 'user')", (run_id,))
    thread_id = conn.execute("SELECT id FROM thread ORDER BY id DESC LIMIT 1").fetchone()["id"]
    conn.execute("INSERT INTO thread_statement (thread_id, statement_id, origin) VALUES (?, ?, 'user')", (thread_id, s1))
    conn.commit()
    conn.close()

    conn = connect(db_path)
    ranked = rank_candidates(conn, job_id)  # settings.min_support=3 default, but only 1 statement
    conn.close()

    assert len(ranked) == 1
    assert ranked[0]["thread"]["id"] == thread_id
