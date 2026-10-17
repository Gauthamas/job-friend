"""Milestone 4: thread discovery. Code-side
validation is the point of this module -- the model only proposes."""

import json

from app.config import settings
from app.db import connect
from app.llm.mock_client import MockLLMClient
from app.threads import run_thread_discovery


def _setup_job_with_statements(db_path: str, statements: list[str]) -> tuple[int, list[int]]:
    """One job with one pair per statement, each pair's two units freshly
    made, statement already 'written'. Returns (job_id, [statement_id,...])."""
    conn = connect(db_path)
    conn.execute("INSERT INTO profile (name) VALUES ('p')")
    conn.execute("INSERT INTO inventory (profile_id, name) VALUES (1, 'inv')")
    conn.execute("INSERT INTO role (inventory_id, company, title, sort_order) VALUES (1, 'c', 't', 0)")
    conn.execute("INSERT INTO flow (profile_id, name, inventory_id) VALUES (1, 'f', 1)")
    conn.execute("INSERT INTO job (flow_id, title, jd_text) VALUES (1, 'job', 'jd')")
    job_id = conn.execute("SELECT id FROM job ORDER BY id DESC LIMIT 1").fetchone()["id"]

    statement_ids = []
    for i, text in enumerate(statements):
        # Every unit shares the substring "shared-phrase" so a single
        # canned verify_thread quote verifies against any of them,
        # regardless of call order.
        conn.execute("INSERT INTO unit (role_id, text, source, sort_order) VALUES (1, ?, 'manual', ?)", (f"unit a{i} shared-phrase", i * 2))
        unit_a = conn.execute("SELECT id FROM unit ORDER BY id DESC LIMIT 1").fetchone()["id"]
        conn.execute("INSERT INTO unit (role_id, text, source, sort_order) VALUES (1, ?, 'manual', ?)", (f"unit b{i} shared-phrase", i * 2 + 1))
        unit_b = conn.execute("SELECT id FROM unit ORDER BY id DESC LIMIT 1").fetchone()["id"]
        conn.execute(
            "INSERT INTO pair (job_id, unit_a_id, unit_b_id, score, model) VALUES (?, ?, ?, 0.5, 'm')",
            (job_id, unit_a, unit_b),
        )
        pair_id = conn.execute("SELECT id FROM pair ORDER BY id DESC LIMIT 1").fetchone()["id"]
        conn.execute(
            "INSERT INTO statement (pair_id, status, text) VALUES (?, 'written', ?)", (pair_id, text),
        )
        statement_ids.append(conn.execute("SELECT id FROM statement ORDER BY id DESC LIMIT 1").fetchone()["id"])

    conn.commit()
    conn.close()
    return job_id, statement_ids


def _propose(threads: list[dict], unused: list[str]) -> str:
    return json.dumps({"threads": threads, "unused": unused})


def test_valid_proposal_creates_threads_statements_and_verified_units(db_path):
    job_id, sids = _setup_job_with_statements(db_path, ["s1 about android", "s2 about android", "s3 about android"])
    llm = MockLLMClient({
        "propose_threads": [_propose([{"idea": "Android work", "supporting_statement_ids": ["1", "2", "3"]}], [])],
        "verify_thread": [json.dumps({"verdict": "yes", "quote": "shared-phrase"})] * 6,  # 3 pairs -> 6 units
    })

    run_id = run_thread_discovery(connect(db_path), job_id, llm, "m")

    conn = connect(db_path)
    run = conn.execute("SELECT * FROM thread_run WHERE id = ?", (run_id,)).fetchone()
    assert run["error"] is None
    threads = conn.execute("SELECT * FROM thread WHERE run_id = ?", (run_id,)).fetchall()
    assert len(threads) == 1
    assert threads[0]["idea"] == "Android work"
    thread_statements = conn.execute("SELECT * FROM thread_statement WHERE thread_id = ?", (threads[0]["id"],)).fetchall()
    assert {r["statement_id"] for r in thread_statements} == set(sids)
    assert all(r["origin"] == "proposed" for r in thread_statements)
    thread_units = conn.execute("SELECT * FROM thread_unit WHERE thread_id = ?", (threads[0]["id"],)).fetchall()
    assert len(thread_units) == 6  # 3 pairs x 2 units each, all distinct
    assert all(r["model_verdict"] == "yes" for r in thread_units)
    assert all(r["quote"] is not None for r in thread_units)
    conn.close()


def test_successful_run_records_seconds_total_and_run_timing(db_path):
    """Threads now store a total duration the same way extraction and
    judging do: a per-run column (thread_run.seconds_total) plus a
    'threads' row in the shared run_timing table."""
    job_id, sids = _setup_job_with_statements(db_path, ["s1 about android"])
    llm = MockLLMClient({
        "propose_threads": [_propose([{"idea": "Android work", "supporting_statement_ids": ["1"]}], [])],
        "verify_thread": [json.dumps({"verdict": "yes", "quote": "shared-phrase"})] * 2,
    })

    run_id = run_thread_discovery(connect(db_path), job_id, llm, "m")

    conn = connect(db_path)
    run = conn.execute("SELECT * FROM thread_run WHERE id = ?", (run_id,)).fetchone()
    assert run["seconds_total"] is not None
    timing_row = conn.execute("SELECT * FROM run_timing WHERE phase = 'threads'").fetchone()
    assert timing_row is not None
    assert timing_row["items"] == 1
    conn.close()


def test_a_run_with_no_statements_records_no_timing(db_path):
    """Nothing to call the model for -- seconds_total stays unset, same as
    extraction's own seconds field when there's nothing to record."""
    job_id, _ = _setup_job_with_statements(db_path, [])
    llm = MockLLMClient({})

    run_id = run_thread_discovery(connect(db_path), job_id, llm, "m")

    conn = connect(db_path)
    run = conn.execute("SELECT * FROM thread_run WHERE id = ?", (run_id,)).fetchone()
    assert run["seconds_total"] is None
    assert conn.execute("SELECT * FROM run_timing WHERE phase = 'threads'").fetchone() is None
    conn.close()


def test_invalid_and_duplicate_statement_ids_are_dropped(db_path):
    job_id, sids = _setup_job_with_statements(db_path, ["s1", "s2", "s3"])
    llm = MockLLMClient({
        "propose_threads": [_propose([
            # "9" doesn't exist; "2" is claimed by both threads -- second occurrence drops.
            {"idea": "Thread A", "supporting_statement_ids": ["1", "2", "9"]},
            {"idea": "Thread B", "supporting_statement_ids": ["2", "3"]},
        ], [])],
        # Thread A: 2 statements -> 4 units. Thread B (kept, below_min): 1 statement -> 2 units.
        "verify_thread": [json.dumps({"verdict": "no", "quote": ""})] * 6,
    })

    original_min_support = settings.min_support
    settings.min_support = 2
    try:
        run_id = run_thread_discovery(connect(db_path), job_id, llm, "m")
    finally:
        settings.min_support = original_min_support

    conn = connect(db_path)
    threads = conn.execute("SELECT * FROM thread WHERE run_id = ? ORDER BY id", (run_id,)).fetchall()
    assert len(threads) == 2  # Thread A (2 valid ids) clears min_support=2; Thread B (1 id) is kept, flagged
    assert threads[0]["below_min"] == 0
    assert threads[1]["below_min"] == 1
    statement_ids_in_a = {
        r["statement_id"] for r in conn.execute(
            "SELECT * FROM thread_statement WHERE thread_id = ?", (threads[0]["id"],)
        ).fetchall()
    }
    assert statement_ids_in_a == {sids[0], sids[1]}  # "9" dropped, duplicate "2" went to A not B
    statement_ids_in_b = {
        r["statement_id"] for r in conn.execute(
            "SELECT * FROM thread_statement WHERE thread_id = ?", (threads[1]["id"],)
        ).fetchall()
    }
    assert statement_ids_in_b == {sids[2]}
    conn.close()


def test_thread_below_min_support_is_kept_flagged_not_dropped(db_path):
    job_id, sids = _setup_job_with_statements(db_path, ["s1", "s2", "s3", "s4"])
    llm = MockLLMClient({
        "propose_threads": [_propose([
            {"idea": "Too small", "supporting_statement_ids": ["1", "2"]},  # below default min_support=3
        ], ["3", "4"])],
        "assign_unused": [
            json.dumps({"thread": "none"}),  # for whichever of 3,4 ends up "unused"
        ] * 2,
        "verify_thread": [json.dumps({"verdict": "no", "quote": ""})] * 4,  # 2 statements -> 4 units
    })

    run_id = run_thread_discovery(connect(db_path), job_id, llm, "m")

    conn = connect(db_path)
    threads = conn.execute("SELECT * FROM thread WHERE run_id = ?", (run_id,)).fetchall()
    assert len(threads) == 1  # kept, not dropped
    assert threads[0]["below_min"] == 1
    statement_ids = {
        r["statement_id"] for r in conn.execute(
            "SELECT * FROM thread_statement WHERE thread_id = ?", (threads[0]["id"],)
        ).fetchall()
    }
    assert statement_ids == {sids[0], sids[1]}
    run = conn.execute("SELECT * FROM thread_run WHERE id = ?", (run_id,)).fetchone()
    assert run["proposed_count"] == 2
    assert run["moved_count"] == 0
    assert run["removed_count"] == 2  # 3, 4 never offered to assign_unused (no assignable thread)
    conn.close()


def test_verify_thread_quote_not_in_unit_text_is_dropped_not_repaired(db_path):
    job_id, sids = _setup_job_with_statements(db_path, ["s1", "s2", "s3"])
    llm = MockLLMClient({
        "propose_threads": [_propose([{"idea": "T", "supporting_statement_ids": ["1", "2", "3"]}], [])],
        "verify_thread": [json.dumps({"verdict": "yes", "quote": "this text is not in any unit"})] * 6,
    })

    run_id = run_thread_discovery(connect(db_path), job_id, llm, "m")

    conn = connect(db_path)
    thread = conn.execute("SELECT * FROM thread WHERE run_id = ?", (run_id,)).fetchone()
    units = conn.execute("SELECT * FROM thread_unit WHERE thread_id = ?", (thread["id"],)).fetchall()
    assert len(units) == 6
    assert all(u["quote"] is None for u in units)  # fabricated quote -> no quote, verdict kept
    assert all(u["model_verdict"] == "yes" for u in units)
    conn.close()


def test_a_raising_call_is_recorded_as_a_run_error_nothing_half_written(db_path):
    job_id, sids = _setup_job_with_statements(db_path, ["s1", "s2", "s3"])
    llm = MockLLMClient({})  # nothing queued -- complete_stream raises AssertionError immediately

    run_id = run_thread_discovery(connect(db_path), job_id, llm, "m")

    conn = connect(db_path)
    run = conn.execute("SELECT * FROM thread_run WHERE id = ?", (run_id,)).fetchone()
    assert run["error"] is not None
    assert "AssertionError" in run["error"]
    assert conn.execute("SELECT COUNT(*) AS n FROM thread WHERE run_id = ?", (run_id,)).fetchone()["n"] == 0
    conn.close()


def test_truncated_json_is_a_run_error_with_nothing_half_written(db_path):
    job_id, sids = _setup_job_with_statements(db_path, ["s1", "s2", "s3"])
    llm = MockLLMClient({"propose_threads": ['{"threads": [{"idea": "cut off mid-objec']})

    run_id = run_thread_discovery(connect(db_path), job_id, llm, "m")

    conn = connect(db_path)
    run = conn.execute("SELECT * FROM thread_run WHERE id = ?", (run_id,)).fetchone()
    assert run["error"] is not None
    assert conn.execute("SELECT COUNT(*) AS n FROM thread WHERE run_id = ?", (run_id,)).fetchone()["n"] == 0
    conn.close()


def test_rerun_creates_a_new_run_and_keeps_old_one_viewable(db_path):
    job_id, sids = _setup_job_with_statements(db_path, ["s1", "s2", "s3"])
    llm = MockLLMClient({
        "propose_threads": [
            _propose([{"idea": "First idea", "supporting_statement_ids": ["1", "2", "3"]}], []),
            _propose([{"idea": "Second idea", "supporting_statement_ids": ["1", "2", "3"]}], []),
        ],
        "verify_thread": [json.dumps({"verdict": "no", "quote": ""})] * 12,
    })

    run_id_1 = run_thread_discovery(connect(db_path), job_id, llm, "m")
    run_id_2 = run_thread_discovery(connect(db_path), job_id, llm, "m")

    assert run_id_1 != run_id_2
    conn = connect(db_path)
    runs = conn.execute("SELECT id FROM thread_run WHERE job_id = ? ORDER BY id", (job_id,)).fetchall()
    assert [r["id"] for r in runs] == [run_id_1, run_id_2]
    idea_1 = conn.execute("SELECT idea FROM thread WHERE run_id = ?", (run_id_1,)).fetchone()["idea"]
    idea_2 = conn.execute("SELECT idea FROM thread WHERE run_id = ?", (run_id_2,)).fetchone()["idea"]
    assert idea_1 == "First idea"
    assert idea_2 == "Second idea"
    conn.close()


def test_editing_a_statement_marks_its_threads_stale(db_path):
    job_id, sids = _setup_job_with_statements(db_path, ["s1", "s2", "s3"])
    llm = MockLLMClient({
        "propose_threads": [_propose([{"idea": "T", "supporting_statement_ids": ["1", "2", "3"]}], [])],
        "verify_thread": [json.dumps({"verdict": "no", "quote": ""})] * 6,
    })
    run_id = run_thread_discovery(connect(db_path), job_id, llm, "m")

    conn = connect(db_path)
    thread_id = conn.execute("SELECT id FROM thread WHERE run_id = ?", (run_id,)).fetchone()["id"]
    assert conn.execute("SELECT stale FROM thread WHERE id = ?", (thread_id,)).fetchone()["stale"] == 0
    conn.close()

    from app.threads import mark_threads_stale_for_statement
    conn = connect(db_path)
    mark_threads_stale_for_statement(conn, sids[0])
    conn.commit()
    assert conn.execute("SELECT stale FROM thread WHERE id = ?", (thread_id,)).fetchone()["stale"] == 1
    conn.close()
