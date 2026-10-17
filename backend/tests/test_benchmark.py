"""Milestone 9: scripts/benchmark.py and
scripts/bench_metrics.py. No LLM calls except in the one test that
exercises the thread-replay plumbing, which uses MockLLMClient. Guards:
the real db is never touched (session-wide check in test_db_isolation.py
covers this too); the thread replay always runs against a temp db."""

import argparse
import json
import sqlite3
import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parent.parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import bench_metrics as bm  # noqa: E402
import benchmark  # noqa: E402

from app.db import connect, init_db  # noqa: E402
from app.llm.mock_client import MockLLMClient  # noqa: E402
from app.llm.schemas import ProposeThreadsResult  # noqa: E402


# --- Jaccard stability / best-match grouping ---

def test_jaccard_basic_cases():
    assert bm.jaccard(set(), set()) == 1.0
    assert bm.jaccard({1, 2}, set()) == 0.0
    assert bm.jaccard({1, 2}, {2, 3}) == pytest.approx(1 / 3)
    assert bm.jaccard({1, 2}, {1, 2}) == 1.0


def test_best_match_average_jaccard_picks_the_closest_group():
    groups_a = [{1, 2, 3}, {7, 8}]
    groups_b = [{1, 2, 3, 4}, {7}, {100, 101}]
    # group {1,2,3} best matches {1,2,3,4} (0.75); {7,8} best matches {7} (0.5)
    assert bm.best_match_average_jaccard(groups_a, groups_b) == pytest.approx((0.75 + 0.5) / 2)


def test_best_match_average_jaccard_empty_sides():
    assert bm.best_match_average_jaccard([], []) == 1.0
    assert bm.best_match_average_jaccard([{1}], []) == 0.0
    assert bm.best_match_average_jaccard([], [{1}]) == 1.0


def test_pairwise_stability_identical_runs_is_one():
    run = [{1, 2}, {3, 4}]
    assert bm.pairwise_stability([run, run, run]) == 1.0


def test_pairwise_stability_disjoint_runs_is_zero():
    assert bm.pairwise_stability([[{1, 2}], [{3, 4}]]) == 0.0


def test_pairwise_stability_single_run_is_one():
    assert bm.pairwise_stability([[{1, 2}]]) == 1.0


# --- Valid-support rate ---

def test_valid_support_rate_drops_invalid_and_duplicate_ids():
    proposed = ProposeThreadsResult(
        threads=[
            {"idea": "A", "supporting_statement_ids": ["1", "2", "99"]},  # "99" invalid
            {"idea": "B", "supporting_statement_ids": ["2", "3"]},  # "2" duplicate, claimed by A
        ],
        unused=[],
    )
    result = bm.valid_support_rate(proposed, valid_ids={"1", "2", "3"})
    assert result["raw_total"] == 5
    assert result["cleaned_total"] == 3  # "1","2" kept for A; "3" kept for B ("2" dropped as dup, "99" invalid)
    assert result["rate"] == pytest.approx(3 / 5)


def test_valid_support_rate_vacuous_when_nothing_proposed():
    proposed = ProposeThreadsResult(threads=[], unused=[])
    assert bm.valid_support_rate(proposed, valid_ids=set())["rate"] == 1.0


# --- verdict mix / quote share ---

def test_verdict_mix_and_quote_share():
    assert bm.verdict_mix(["yes", "yes", "no", "partly"]) == {"yes": 0.5, "partly": 0.25, "no": 0.25}
    assert bm.quote_found_share(["a quote", None, "another"]) == pytest.approx(2 / 3)
    assert bm.quote_found_share([]) == 0.0


# --- confusion matrix / override rate, including null user_verdict ---

def test_error_type_buckets_known_messages():
    assert bm.error_type("unit id 'U50' is not in the candidate set") == "id not in candidate set"
    assert bm.error_type("Not included in the batch response (cut off or missing).") == "cut off / missing from batch response"
    assert bm.error_type("unit id 'U50' listed more than once") == "duplicate id"
    assert bm.error_type("verdict 'none' for unit 'U61' is not match/weak") == "invalid verdict value"
    assert bm.error_type("Model call timed out.") == "model call timed out"
    assert bm.error_type("needs for unit 'U52' exceeds 8 words") == "field too long (legacy rule, no longer rejected)"
    assert bm.error_type("Batch call raised an unexpected error: ValueError: x") == "unexpected exception"
    assert bm.error_type("something nobody expected") == "other"


def test_override_rate_and_confusion_matrix_with_nulls():
    rows = [
        {"model_verdict": "match", "user_verdict": None},  # not changed
        {"model_verdict": "match", "user_verdict": "weak"},  # overridden
        {"model_verdict": "none", "user_verdict": None},
        {"model_verdict": "weak", "user_verdict": "weak"},  # overridden but same value
    ]
    rate = bm.override_rate(rows)
    assert rate == {"total": 4, "overridden": 2, "rate": 0.5}
    matrix = bm.confusion_matrix(rows)
    assert matrix["match"]["weak"] == 1
    assert matrix["weak"]["weak"] == 1
    assert matrix["none"]["match"] == 0  # null user_verdict never enters the matrix


def test_confusion_matrix_and_agreement_on_a_temp_db(db_path):
    """Integration: run_agreement_section against a synthetic temp-db copy
    (never the real one), including a null user_verdict."""
    conn = connect(db_path)
    conn.execute("INSERT INTO profile (name) VALUES ('p')")
    conn.execute("INSERT INTO inventory (profile_id, name) VALUES (1, 'inv')")
    conn.execute("INSERT INTO role (inventory_id, company, title, sort_order) VALUES (1, 'c', 't', 0)")
    conn.execute("INSERT INTO flow (profile_id, name, inventory_id) VALUES (1, 'f', 1)")
    conn.execute("INSERT INTO job (flow_id, title, jd_text) VALUES (1, 'job', 'jd')")
    job_id = conn.execute("SELECT id FROM job").fetchone()["id"]
    conn.execute("INSERT INTO unit (role_id, text, source, sort_order) VALUES (1, 'u', 'manual', 0)")
    unit_id = conn.execute("SELECT id FROM unit").fetchone()["id"]
    conn.execute(
        "INSERT INTO requirement (job_id, text, weight, source, status, sort_order) "
        "VALUES (?, 'req', 'high', 'extracted', 'pending', 0)", (job_id,),
    )
    req_id = conn.execute("SELECT id FROM requirement").fetchone()["id"]
    conn.execute(
        "INSERT INTO judgment (requirement_id, unit_id, model_verdict, user_verdict) VALUES (?, ?, 'match', NULL)",
        (req_id, unit_id),
    )
    conn.execute(
        "INSERT INTO judgment (requirement_id, unit_id, model_verdict, user_verdict, added_by_user) "
        "VALUES (?, ?, 'none', 'match', 0)", (req_id, unit_id),
    )
    conn.commit()
    conn.close()

    result = benchmark.run_agreement_section(argparse.Namespace(db=db_path))
    overall = result["overall"]["agreement"]
    assert overall["override_rate"] == {"total": 2, "overridden": 1, "rate": 0.5}
    assert overall["confusion_matrix"]["none"]["match"] == 1
    assert "not changed" in result["note"]


# --- read-only DB open ---

def test_open_readonly_connection_cannot_write(db_path):
    conn = benchmark.open_readonly(db_path)
    try:
        with pytest.raises(sqlite3.OperationalError):
            conn.execute("INSERT INTO profile (name) VALUES ('nope')")
    finally:
        conn.close()


def test_real_db_mtime_unchanged_by_open_readonly():
    """Opening (and failing to write to) the real db must never touch it."""
    import conftest
    if conftest.REAL_DB_MTIME_AT_SESSION_START is None:
        pytest.skip("job_friend.db doesn't exist in this environment")
    conn = benchmark.open_readonly(str(conftest.REAL_DB_PATH))
    conn.execute("SELECT 1 FROM job LIMIT 1").fetchall()
    conn.close()
    assert conftest.REAL_DB_PATH.stat().st_mtime == conftest.REAL_DB_MTIME_AT_SESSION_START


# --- thread replay uses a temp db, never the real one ---

def _write_tiny_fixture(tmp_path: Path) -> Path:
    fixture_dir = tmp_path / "fixture"
    fixture_dir.mkdir()
    units = [{"id": f"U{i}", "text": f"unit {i} text"} for i in range(1, 5)]
    statements = {"U1-U2": "shared trait one", "U2-U3": "shared trait two", "U3-U4": "shared trait three"}
    (fixture_dir / "units.json").write_text(json.dumps(units), encoding="utf-8")
    (fixture_dir / "statements.json").write_text(json.dumps(statements), encoding="utf-8")
    return fixture_dir


def test_thread_replay_runs_against_a_temp_db_not_the_real_one(tmp_path):
    import conftest

    fixture_dir = _write_tiny_fixture(tmp_path)
    tmp_db_path = str(tmp_path / "bench.db")
    conn = init_db(tmp_db_path)
    job_id = benchmark._build_fixture_job(conn, fixture_dir)

    mock = MockLLMClient({
        "propose_threads": [json.dumps({
            "threads": [{"idea": "Shared trait", "supporting_statement_ids": ["1", "2", "3"]}],
            "unused": [],
        })],
        "verify_thread": [json.dumps({"verdict": "yes", "quote": "unit 1 text"})] * 8,
    })
    recorder = benchmark.RecordingLLMClient(mock)

    real_mtime_before = (
        conftest.REAL_DB_PATH.stat().st_mtime if conftest.REAL_DB_MTIME_AT_SESSION_START is not None else None
    )

    repeat = benchmark._run_thread_repeat(conn, job_id, recorder, "mock-model")
    conn.close()

    assert repeat["error"] is None
    assert repeat["threads_proposed"] == 1
    assert len(recorder.calls) >= 2  # propose_threads + at least one verify_thread
    assert recorder.calls[0]["task"] == "propose_threads"

    if real_mtime_before is not None:
        assert conftest.REAL_DB_PATH.stat().st_mtime == real_mtime_before


# --- timing aggregation, including a job with missing stages ---

SAMPLE_LOG_LINES = [
    "2026-10-12 12:00:00,000 INFO job 1: batch of requirements [10, 11] (start=2026-10-12 06:00:00.000000) -> "
    "2 written (2 valid results), finish_reason=stop, prompt_tokens=1000, completion_tokens=200, "
    "reasoning_tokens=0, seconds_total=40.00, seconds_to_first_chunk=5.00, "
    "seconds_to_first_content_chunk=5.00, tokens_per_s=5.00",
    "2026-10-12 12:01:00,000 INFO job 1: batch of requirements [12] (start=2026-10-12 06:00:40.000000) -> "
    "1 written (1 valid results), finish_reason=stop, prompt_tokens=500, completion_tokens=100, "
    "reasoning_tokens=0, seconds_total=20.00, seconds_to_first_chunk=2.00, "
    "seconds_to_first_content_chunk=2.00, tokens_per_s=5.00",
]


def test_parse_judging_log_line_and_aggregate():
    parsed = bm.parse_judging_log_line(SAMPLE_LOG_LINES[0])
    assert parsed == {
        "job_id": 1, "prompt_tokens": 1000.0, "completion_tokens": 200.0,
        "reasoning_tokens": 0.0, "seconds_total": 40.0, "tokens_per_s": 5.0,
    }
    agg = bm.aggregate_log_metrics(SAMPLE_LOG_LINES, job_id=1)
    assert agg["batches"] == 2
    assert agg["total_completion_tokens"] == 300
    assert agg["total_seconds"] == 60.0
    assert agg["completion_tokens_per_second"] == pytest.approx(5.0)


def test_aggregate_log_metrics_missing_job_returns_zeroed():
    agg = bm.aggregate_log_metrics(SAMPLE_LOG_LINES, job_id=999)
    assert agg["batches"] == 0
    assert agg["completion_tokens_per_second"] is None


def test_duration_or_none_rejects_negative_durations():
    assert bm.duration_or_none(42.0) == 42.0
    assert bm.duration_or_none(0.0) == 0.0
    assert bm.duration_or_none(-5.0) is None
    assert bm.duration_or_none(None) is None


def test_stage_span_and_median_handle_missing_values():
    assert bm.stage_span(["2026-10-12 06:00:00", "2026-10-12 06:01:00"]) == 60.0
    assert bm.stage_span([None, "2026-10-12 06:00:00"]) is None  # only one parses
    assert bm.stage_span([]) is None
    assert bm.median([1.0, None, 3.0]) == 2.0
    assert bm.median([]) is None


def test_timing_section_handles_a_job_with_missing_stages(db_path, tmp_path):
    """One job has every timestamp; a second has none at all (no judging
    window run yet, no statements, no thread run, no letter) -- the
    section must report it without crashing, with Nones where expected."""
    conn = connect(db_path)
    conn.execute("INSERT INTO profile (name) VALUES ('p')")
    conn.execute("INSERT INTO inventory (profile_id, name) VALUES (1, 'inv')")
    conn.execute("INSERT INTO role (inventory_id, company, title, sort_order) VALUES (1, 'c', 't', 0)")
    conn.execute("INSERT INTO flow (profile_id, name, inventory_id) VALUES (1, 'f', 1)")

    conn.execute(
        "INSERT INTO job (flow_id, title, jd_text, extraction_seconds, judging_started_at, judging_deadline) "
        "VALUES (1, 'full', 'jd', 12.5, '2026-10-12 06:00:00', '2026-10-12 06:20:00')"
    )
    full_job_id = conn.execute("SELECT id FROM job WHERE title = 'full'").fetchone()["id"]
    conn.execute(
        "INSERT INTO requirement (job_id, text, weight, source, status, sort_order, judged_at, judge_seconds) "
        "VALUES (?, 'r', 'high', 'extracted', 'done', 0, '2026-10-12 06:00:30', 2.5)", (full_job_id,),
    )

    conn.execute("INSERT INTO job (flow_id, title, jd_text) VALUES (1, 'empty', 'jd')")

    conn.commit()
    conn.close()

    empty_log = tmp_path / "judging.log"
    empty_log.write_text("", encoding="utf-8")

    result = benchmark.run_timing_section(argparse.Namespace(db=db_path, log=str(empty_log)))
    full_job_id_str = full_job_id
    empty_data = next(d for jid, d in result["per_job"].items() if d["title"] == "empty")
    full_data = result["per_job"][full_job_id_str]

    assert empty_data["extraction_seconds"] is None
    assert empty_data["time_to_first_judged_row_s"] is None
    assert empty_data["statements_span_s"] is None
    assert empty_data["autofilled_count"] == 0

    assert full_data["extraction_seconds"] == 12.5
    assert full_data["time_to_first_judged_row_s"] == pytest.approx(30.0)
    assert full_data["judging_window_total_s"] == pytest.approx(1200.0)
    assert full_data["requirements_judged"] == 1
