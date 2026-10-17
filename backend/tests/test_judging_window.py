"""Direct tests of app/judging.py's batch-call/window machinery against the
"Judging" checklist. Uses MockLLMClient (real complete_stream chunking) plus
an injectable clock for the 9-minute-left and deadline rules -- no real
waiting anywhere here."""

import json
from datetime import datetime, timedelta

import pytest

from app import judging
from app.config import settings
from app.db import connect, init_db
from app.llm.mock_client import MockLLMClient
from app.llm.schemas import JudgedUnit


class FakeClock:
    """now() auto-advances by `step` on every call -- stands in for "this
    much wall time passed since the last check", without ever sleeping."""

    def __init__(self, start: datetime, step: timedelta = timedelta(0)):
        self.t = start
        self.step = step

    def now(self) -> datetime:
        current = self.t
        self.t += self.step
        return current


@pytest.fixture
def db_path(tmp_path) -> str:
    path = str(tmp_path / "test.db")
    init_db(path).close()
    return path


def _make_job(db_path: str, requirements: list[tuple[str, str]]) -> tuple[int, list[int]]:
    """One unit per requirement, already shortlisted (one judgment row
    each, model_verdict NULL) -- mirrors what shortlist_and_create_
    judgments would have produced at extraction time."""
    conn = connect(db_path)
    conn.execute("INSERT INTO profile (name) VALUES ('p')")
    conn.execute("INSERT INTO inventory (profile_id, name) VALUES (1, 'inv')")
    conn.execute("INSERT INTO role (inventory_id, company, title, sort_order) VALUES (1, 'c', 't', 0)")
    conn.execute("INSERT INTO flow (profile_id, name, inventory_id) VALUES (1, 'f', 1)")
    conn.execute("INSERT INTO job (flow_id, title, jd_text) VALUES (1, 'job', 'jd')")
    job_id = conn.execute("SELECT id FROM job").fetchone()["id"]

    requirement_ids = []
    for i, (text, weight) in enumerate(requirements):
        conn.execute(
            "INSERT INTO unit (role_id, text, source, sort_order) VALUES (1, ?, 'manual', ?)",
            (f"unit for {text}", i),
        )
        unit_id = conn.execute("SELECT id FROM unit ORDER BY id DESC LIMIT 1").fetchone()["id"]
        cur = conn.execute(
            "INSERT INTO requirement (job_id, text, weight, source, status, sort_order) "
            "VALUES (?, ?, ?, 'extracted', 'pending', ?)",
            (job_id, text, weight, i),
        )
        requirement_id = cur.lastrowid
        conn.execute(
            "INSERT INTO judgment (requirement_id, unit_id, score, model_verdict) VALUES (?, ?, 0.9, NULL)",
            (requirement_id, unit_id),
        )
        requirement_ids.append(requirement_id)
    conn.commit()
    conn.close()
    return job_id, requirement_ids


def _requirement_row(db_path, requirement_id):
    conn = connect(db_path)
    row = conn.execute("SELECT * FROM requirement WHERE id = ?", (requirement_id,)).fetchone()
    conn.close()
    return row


def _job_row(db_path, job_id):
    conn = connect(db_path)
    row = conn.execute("SELECT * FROM job WHERE id = ?", (job_id,)).fetchone()
    conn.close()
    return row


def _batch_ok(pairs: list[tuple[str, int | None, str]]) -> str:
    """pairs: (small_req_id, unit_id_or_None, verdict). unit_id None means
    an empty units list (no match) for that requirement."""
    results = []
    for req_id, unit_id, verdict in pairs:
        units = [] if unit_id is None else [{"id": f"{req_id}.U{unit_id}", "quote": "", "shows": "fits", "needs": "fits", "v": verdict}]
        results.append({"req_id": req_id, "units": units, "reason": "ok"})
    return json.dumps({"results": results})


# --- invalid / truncated / mixed batch responses ---

def test_invalid_batch_response_writes_nothing_all_stay_pending(db_path):
    job_id, [rid] = _make_job(db_path, [("Req A", "high")])
    llm = MockLLMClient({"judge_batch": ["not valid json at all"]})

    judging.run_judging_window(db_path, job_id, llm, model="m")

    row = _requirement_row(db_path, rid)
    assert row["status"] == "pending"
    assert row["last_error"] is not None
    assert len(llm.calls) == 1  # no retry, no fallback


def test_truncated_response_keeps_complete_valid_results_before_the_cut(db_path):
    job_id, [rid1, rid2] = _make_job(db_path, [("Req A", "high"), ("Req B", "high")])
    conn = connect(db_path)
    unit1 = conn.execute("SELECT unit_id FROM judgment WHERE requirement_id = ?", (rid1,)).fetchone()["unit_id"]
    conn.close()

    # A complete result for "1", then a result for "2" cut off mid-object
    # (as finish_reason="length" would produce) -- never valid JSON overall.
    raw = (
        '{"results": [{"req_id": "1", "units": [{"id": "1.U%d", "quote": "", "shows": "fits", "needs": "fits", "v": "match"}], '
        '"reason": "ok"}, {"req_id": "2", "units": [{"id": "2.U9", "quote": "cu' % unit1
    )
    llm = MockLLMClient({"judge_batch": [raw]})

    judging.run_judging_window(db_path, job_id, llm, model="m")

    assert _requirement_row(db_path, rid1)["status"] == "done"
    row2 = _requirement_row(db_path, rid2)
    assert row2["status"] == "pending"
    assert row2["last_error"] is not None


def _make_job_with_shared_candidates(db_path: str) -> tuple[int, int, int, dict[str, int]]:
    """Reproduces job 47's shape: two requirements in one batch that
    shortlist overlapping units -- unit "shared" is a candidate of BOTH,
    "only_a" only of the first, "only_b" only of the second."""
    conn = connect(db_path)
    conn.execute("INSERT INTO profile (name) VALUES ('p')")
    conn.execute("INSERT INTO inventory (profile_id, name) VALUES (1, 'inv')")
    conn.execute("INSERT INTO role (inventory_id, company, title, sort_order) VALUES (1, 'c', 't', 0)")
    conn.execute("INSERT INTO flow (profile_id, name, inventory_id) VALUES (1, 'f', 1)")
    conn.execute("INSERT INTO job (flow_id, title, jd_text) VALUES (1, 'job', 'jd')")
    job_id = conn.execute("SELECT id FROM job").fetchone()["id"]

    unit_ids = {}
    for name in ("shared", "only_a", "only_b"):
        conn.execute("INSERT INTO unit (role_id, text, source, sort_order) VALUES (1, ?, 'manual', 0)", (name,))
        unit_ids[name] = conn.execute("SELECT id FROM unit ORDER BY id DESC LIMIT 1").fetchone()["id"]

    requirement_ids = []
    for text, candidates in (("Req A", ("shared", "only_a")), ("Req B", ("shared", "only_b"))):
        cur = conn.execute(
            "INSERT INTO requirement (job_id, text, weight, source, status, sort_order) "
            "VALUES (?, ?, 'high', 'extracted', 'pending', ?)", (job_id, text, len(requirement_ids)),
        )
        requirement_id = cur.lastrowid
        for name in candidates:
            conn.execute(
                "INSERT INTO judgment (requirement_id, unit_id, score, model_verdict) VALUES (?, ?, 0.9, NULL)",
                (requirement_id, unit_ids[name]),
            )
        requirement_ids.append(requirement_id)
    conn.commit()
    conn.close()
    return job_id, requirement_ids[0], requirement_ids[1], unit_ids


def test_a_unit_shared_by_two_requirements_in_one_batch_is_judged_correctly(db_path):
    """job 47 regression: both requirements use the SAME real unit
    ("shared") plus their own unique one. Each candidate id is scoped to
    its own req_id, so a correct response citing req 1's own-scoped
    "shared" id and req 2's own-scoped "only_b" id writes both cleanly --
    no cross-requirement ambiguity even though the same unit appears
    under both."""
    job_id, rid1, rid2, unit_ids = _make_job_with_shared_candidates(db_path)
    raw = json.dumps({"results": [
        {"req_id": "1", "units": [{"id": f"1.U{unit_ids['shared']}", "quote": "", "shows": "fits", "needs": "fits", "v": "match"}], "reason": "ok"},
        {"req_id": "2", "units": [{"id": f"2.U{unit_ids['only_b']}", "quote": "", "shows": "fits", "needs": "fits", "v": "match"}], "reason": "ok"},
    ]})
    llm = MockLLMClient({"judge_batch": [raw]})

    judging.run_judging_window(db_path, job_id, llm, model="m")

    assert _requirement_row(db_path, rid1)["status"] == "done"
    assert _requirement_row(db_path, rid2)["status"] == "done"


def test_citing_the_other_requirements_scoped_id_is_still_rejected(db_path):
    """If a response ever did mix up which requirement a unit belongs to
    -- citing req 2's own-scoped id for "only_b" under req 1's result --
    it's still a hard validation error: req 1's own candidate set only
    ever contains ids scoped to "1", so "2.U<only_b>" is never valid
    there, exactly the job 47 failure mode, now impossible to mistake for
    a legitimate id."""
    job_id, rid1, rid2, unit_ids = _make_job_with_shared_candidates(db_path)
    raw = json.dumps({"results": [
        {"req_id": "1", "units": [{"id": f"2.U{unit_ids['only_b']}", "quote": "", "shows": "fits", "needs": "fits", "v": "match"}], "reason": "ok"},
        {"req_id": "2", "units": [{"id": f"2.U{unit_ids['only_b']}", "quote": "", "shows": "fits", "needs": "fits", "v": "match"}], "reason": "ok"},
    ]})
    llm = MockLLMClient({"judge_batch": [raw]})

    judging.run_judging_window(db_path, job_id, llm, model="m")

    row1 = _requirement_row(db_path, rid1)
    assert row1["status"] == "pending"
    assert row1["last_error"] is not None
    assert _requirement_row(db_path, rid2)["status"] == "done"  # its own correct citation still succeeds


def test_mixed_valid_and_invalid_writes_only_the_valid_ones(db_path):
    job_id, [rid1, rid2] = _make_job(db_path, [("Req A", "high"), ("Req B", "high")])
    conn = connect(db_path)
    unit1 = conn.execute("SELECT unit_id FROM judgment WHERE requirement_id = ?", (rid1,)).fetchone()["unit_id"]
    conn.close()

    # rid2's result references a unit id that isn't in its own candidate
    # set -- a hard validation error for that result only.
    raw = json.dumps({"results": [
        {"req_id": "1", "units": [{"id": f"1.U{unit1}", "quote": "", "shows": "fits", "needs": "fits", "v": "match"}], "reason": "ok"},
        {"req_id": "2", "units": [{"id": "2.U99999", "quote": "", "shows": "bad id", "needs": "bad id", "v": "match"}], "reason": "bad"},
    ]})
    llm = MockLLMClient({"judge_batch": [raw]})

    judging.run_judging_window(db_path, job_id, llm, model="m")

    assert _requirement_row(db_path, rid1)["status"] == "done"
    row2 = _requirement_row(db_path, rid2)
    assert row2["status"] == "pending"
    assert row2["last_error"] is not None


def test_no_retry_or_fallback_is_ever_made(db_path):
    job_id, [rid] = _make_job(db_path, [("Req A", "high")])
    # Only one response queued for judge_batch, and nothing at all queued
    # for "judge" (the old single-call task name) -- a fallback call would
    # raise AssertionError against an empty/missing queue.
    llm = MockLLMClient({"judge_batch": ["garbage"]})

    judging.run_judging_window(db_path, job_id, llm, model="m")

    assert len(llm.calls) == 1
    assert all(name == "judge_batch" for name, _ in llm.calls)


# --- status invariant ---

@pytest.mark.parametrize("scenario", ["success", "invalid", "no_candidates"])
def test_requirement_status_is_always_pending_or_done(db_path, scenario):
    job_id, [rid] = _make_job(db_path, [("Req A", "high")])

    if scenario == "success":
        llm = MockLLMClient({"judge_batch": [_batch_ok([("1", None, "match")])]})
    elif scenario == "invalid":
        llm = MockLLMClient({"judge_batch": ["not json"]})
    else:
        conn = connect(db_path)
        conn.execute("DELETE FROM judgment WHERE requirement_id = ?", (rid,))
        conn.commit()
        conn.close()
        llm = MockLLMClient({"judge_batch": [_batch_ok([("1", None, "match")])]})

    judging.run_judging_window(db_path, job_id, llm, model="m")
    assert _requirement_row(db_path, rid)["status"] in ("pending", "done")


# --- weight-then-position order ---

def test_batches_follow_weight_then_position_order(db_path):
    job_id, rids = _make_job(db_path, [
        ("low one", "low"), ("high one", "high"), ("medium one", "medium"), ("high two", "high"),
    ])
    llm = MockLLMClient()
    for _ in range(1):
        llm.queue("judge_batch", _batch_ok([(str(i + 1), None, "match") for i in range(4)]))

    import app.config as config_module
    old_batch_size = config_module.settings.judge_batch_size
    config_module.settings.judge_batch_size = 10  # all four in one batch -- order is what we're checking
    try:
        judging.run_judging_window(db_path, job_id, llm, model="m")
    finally:
        config_module.settings.judge_batch_size = old_batch_size

    sent = json.loads(llm.calls[0][1])
    texts = [r["text"] for r in sent["requirements"]]
    assert texts == ["high one", "high two", "medium one", "low one"]


# --- fake clock: the judge_start_min_left rule and the deadline ---

def test_batch_never_starts_with_less_than_judge_start_min_left_minutes_left(db_path, monkeypatch):
    job_id, rids = _make_job(db_path, [(f"Req {i}", "high") for i in range(2)])
    monkeypatch.setattr(settings, "judge_batch_size", 1)  # one requirement per batch -> two chunks

    llm = MockLLMClient({"judge_batch": [
        _batch_ok([("1", None, "match")]),
        _batch_ok([("1", None, "match")]),
    ]})

    # judge_start_min_left defaults to 2. start=t0 (deadline=t0+20m); the
    # first now_fn() call returns t0 itself (consumed by "start = now_fn()"),
    # so the chunk-1 check uses now()=t0+19m -> remaining=1m < 2m -> stop
    # before ANY batch.
    clock = FakeClock(start=datetime(2026, 1, 1, 0, 0, 0), step=timedelta(minutes=19))
    judging.run_judging_window(db_path, job_id, llm, model="m", now_fn=clock.now)

    assert len(llm.calls) == 0
    for rid in rids:
        assert _requirement_row(db_path, rid)["status"] == "pending"

    # judge_start_min_left refused to start any batch -- the loop has
    # nothing left to try this run, so the window closes right away
    # (dialog closes, banner appears) rather than staying open until the
    # real deadline with pending requirements left over.
    job = _job_row(db_path, job_id)
    assert job["judging_deadline"] != "2026-01-01 00:20:00"


def test_second_batch_runs_when_enough_time_remains(db_path, monkeypatch):
    job_id, rids = _make_job(db_path, [(f"Req {i}", "high") for i in range(2)])
    monkeypatch.setattr(settings, "judge_batch_size", 1)

    llm = MockLLMClient({"judge_batch": [
        _batch_ok([("1", None, "match")]),
        _batch_ok([("1", None, "match")]),
    ]})

    # step=1 minute: deadline=t0+20m; chunk1 check at t0+1m -> 19m left, proceeds;
    # chunk2 check at t0+2m -> 18m left, proceeds. Both batches run.
    clock = FakeClock(start=datetime(2026, 1, 1, 0, 0, 0), step=timedelta(minutes=1))
    judging.run_judging_window(db_path, job_id, llm, model="m", now_fn=clock.now)

    assert len(llm.calls) == 2
    for rid in rids:
        assert _requirement_row(db_path, rid)["status"] == "done"

    # Everything got resolved with minutes to spare -- the window should
    # close right away instead of leaving the blocking dialog up for the
    # rest of the 20-minute window.
    job = _job_row(db_path, job_id)
    assert job["judging_deadline"] != "2026-01-01 00:20:00"


def test_nothing_runs_past_the_deadline_across_many_batches(db_path, monkeypatch):
    job_id, rids = _make_job(db_path, [(f"Req {i}", "high") for i in range(5)])
    monkeypatch.setattr(settings, "judge_batch_size", 1)

    llm = MockLLMClient({"judge_batch": [_batch_ok([("1", None, "match")]) for _ in range(5)]})

    # 6-minute step: deadline=t0+20m. Checks at t0+6,12,18,24,30 minutes ->
    # remaining 14,8,2,-4,-10 -- the judge_start_min_left=2 floor (120s) is
    # cleared by 14m, 8m and exactly 2m (not strictly less), so three
    # batches run before -4m stops the fourth.
    clock = FakeClock(start=datetime(2026, 1, 1, 0, 0, 0), step=timedelta(minutes=6))
    judging.run_judging_window(db_path, job_id, llm, model="m", now_fn=clock.now)

    done = [r for r in rids if _requirement_row(db_path, r)["status"] == "done"]
    pending = [r for r in rids if _requirement_row(db_path, r)["status"] == "pending"]
    assert len(done) == 3
    assert len(pending) == 2
    assert len(llm.calls) == 3

    # judge_start_min_left refused the next batch with pending
    # requirements left over -- the loop still has nothing left to try
    # this run, so the window closes right away instead of staying open
    # until the real deadline.
    job = _job_row(db_path, job_id)
    assert job["judging_deadline"] != "2026-01-01 00:20:00"


def test_window_closes_early_when_everything_is_done(db_path):
    """The dialog must close (judging_deadline set to "now") the moment
    the batch loop has nothing left to try this run -- here, everything
    done with minutes to spare."""
    clock = FakeClock(start=datetime(2026, 1, 1, 0, 0, 0), step=timedelta(minutes=1))
    job_id, [rid] = _make_job(db_path, [("Req A", "high")])
    llm = MockLLMClient({"judge_batch": [_batch_ok([("1", None, "match")])]})
    judging.run_judging_window(db_path, job_id, llm, model="m", now_fn=clock.now)
    assert _requirement_row(db_path, rid)["status"] == "done"
    assert _job_row(db_path, job_id)["judging_deadline"] != "2026-01-01 00:20:00"


def test_window_closes_early_when_floor_refuses_the_only_batch(db_path):
    """Same close-early rule, but nothing ran at all: judge_start_min_left
    refused the only batch, so the requirement is still pending -- the
    loop still has nothing left to try this run."""
    clock = FakeClock(start=datetime(2026, 1, 1, 0, 0, 0), step=timedelta(minutes=19))
    job_id, [rid] = _make_job(db_path, [("Req B", "high")])
    llm = MockLLMClient({"judge_batch": [_batch_ok([("1", None, "match")])]})
    judging.run_judging_window(db_path, job_id, llm, model="m", now_fn=clock.now)
    assert _requirement_row(db_path, rid)["status"] == "pending"
    assert len(llm.calls) == 0
    assert _job_row(db_path, job_id)["judging_deadline"] != "2026-01-01 00:20:00"


def test_window_closes_early_when_chunks_run_out_with_some_still_pending(db_path, monkeypatch):
    """Same close-early rule when the chunk list runs out partway: some
    requirements done, the rest left pending because
    judge_start_min_left refused the next batch -- "nothing left to try
    this run" either way."""
    job_id, rids = _make_job(db_path, [(f"Req {i}", "high") for i in range(3)])
    monkeypatch.setattr(settings, "judge_batch_size", 1)
    llm = MockLLMClient({"judge_batch": [_batch_ok([("1", None, "match")]) for _ in range(3)]})
    clock = FakeClock(start=datetime(2026, 1, 1, 0, 0, 0), step=timedelta(minutes=10))
    judging.run_judging_window(db_path, job_id, llm, model="m", now_fn=clock.now)
    done = [r for r in rids if _requirement_row(db_path, r)["status"] == "done"]
    pending = [r for r in rids if _requirement_row(db_path, r)["status"] == "pending"]
    assert len(done) == 1
    assert len(pending) == 2
    assert _job_row(db_path, job_id)["judging_deadline"] != "2026-01-01 00:20:00"


# --- cancellation: deadline/Finish/Back write nothing, earlier batches stay ---

def test_cancelled_call_writes_nothing(db_path):
    job_id, [rid] = _make_job(db_path, [("Req A", "high")])
    llm = MockLLMClient({"judge_batch": [_batch_ok([("1", None, "match")])]})

    cancel_event = judging.threading.Event()
    cancel_event.set()  # already cancelled before the call even starts

    conn = connect(db_path)
    row = conn.execute("SELECT * FROM requirement WHERE id = ?", (rid,)).fetchone()
    written = judging._process_batch(conn, job_id, [row], llm, cancel_event)
    conn.close()

    assert written == 0
    row = _requirement_row(db_path, rid)
    assert row["status"] == "pending"
    assert row["last_error"] is None  # nothing written at all, not even an error


def test_cancel_between_batches_keeps_earlier_results_and_skips_the_rest(db_path, monkeypatch):
    job_id, [rid1, rid2] = _make_job(db_path, [("Req A", "high"), ("Req B", "high")])
    monkeypatch.setattr(settings, "judge_batch_size", 1)
    llm = MockLLMClient({"judge_batch": [_batch_ok([("1", None, "match")])]})

    # Simulates Finish/Back landing right after batch 1 writes its result
    # but before the outer loop starts batch 2 -- request_cancel runs
    # synchronously right after the real _process_batch returns, so the
    # next loop iteration's cancel_event.is_set() check sees it.
    original_process_batch = judging._process_batch
    calls = {"n": 0}

    def wrapped(conn, jid, rows, llm_client, cancel_event):
        calls["n"] += 1
        result = original_process_batch(conn, jid, rows, llm_client, cancel_event)
        if calls["n"] == 1:
            judging.request_cancel(jid)
        return result

    monkeypatch.setattr(judging, "_process_batch", wrapped)

    judging.run_judging_window(db_path, job_id, llm, model="m")

    assert _requirement_row(db_path, rid1)["status"] == "done"  # earlier batch stays
    assert _requirement_row(db_path, rid2)["status"] == "pending"  # never attempted
    assert len(llm.calls) == 1


# --- free-text fields (quote/shows/needs) are truncated for display only ---

def test_long_shows_and_needs_are_truncated_for_display_not_rejected():
    unit = JudgedUnit(
        id="U1", quote="short quote", shows=" ".join(["word"] * 30), needs=" ".join(["word"] * 30), v="match",
    )
    why = judging._fold_quote_into_why(unit)
    assert why.count("word") == 15 + 15  # each truncated to 15 words, not dropped entirely
    assert "…" in why


def test_short_shows_and_needs_are_not_truncated():
    unit = JudgedUnit(id="U1", quote="short quote", shows="brief", needs="also brief", v="match")
    why = judging._fold_quote_into_why(unit)
    assert why == '"short quote" — Shows: brief. Needs: also brief.'


# --- a crashing batch must not kill the rest of the window (Mishipay bug) ---

def test_a_raising_batch_records_an_error_and_the_loop_continues(db_path, monkeypatch):
    """Regression test for the Mishipay bug: a non-LlmTimeout exception
    from the LLM client (or any bug, network blip, etc.) inside one
    batch's call must not take the rest of the window down with it. Before
    the fix, this propagated out of run_judging_window entirely, skipping
    every later batch, the deadline-closing code, and leaving no
    last_error anywhere -- exactly what was observed on the real job (11
    pending rows, all last_error=NULL, judging_deadline left at its
    original start+20m). Now the batch's own rows get last_error (with the
    exception type and message) and the loop moves on to the next chunk."""
    job_id, [rid1, rid2, rid3] = _make_job(
        db_path, [("Req A", "high"), ("Req B", "high"), ("Req C", "high")]
    )
    monkeypatch.setattr(settings, "judge_batch_size", 1)
    llm = MockLLMClient({"judge_batch": [
        _batch_ok([("1", None, "match")]),
        _batch_ok([("1", None, "match")]),
    ]})

    original_process_batch = judging._process_batch
    calls = {"n": 0}

    def wrapped(conn, jid, rows, llm_client, cancel_event):
        calls["n"] += 1
        if calls["n"] == 2:
            raise RuntimeError("simulated LLM client crash on batch 2")
        return original_process_batch(conn, jid, rows, llm_client, cancel_event)

    monkeypatch.setattr(judging, "_process_batch", wrapped)

    # Plenty of time for all three batches -- nothing here should stop the
    # loop except the crash itself.
    clock = FakeClock(start=datetime(2026, 1, 1, 0, 0, 0), step=timedelta(minutes=1))
    judging.run_judging_window(db_path, job_id, llm, model="m", now_fn=clock.now)

    assert _requirement_row(db_path, rid1)["status"] == "done"
    row2 = _requirement_row(db_path, rid2)
    assert row2["status"] == "pending"
    # Exception type and message both land in last_error.
    assert row2["last_error"] is not None
    assert "RuntimeError" in row2["last_error"]
    assert "simulated LLM client crash" in row2["last_error"]
    # The bug being regression-tested: batch 3 must still get attempted
    # even though batch 2 blew up.
    assert _requirement_row(db_path, rid3)["status"] == "done"
    assert calls["n"] == 3

    # And the window must still close normally afterward (everything
    # resolved -- 2 done, 1 pending-with-error -- so nothing left to try).
    job = _job_row(db_path, job_id)
    assert job["judging_deadline"] != "2026-01-01 00:20:00"


def test_a_finished_window_records_a_positive_seconds_total(db_path):
    """Regression test: run_judging_window used to hardcode
    seconds_total=0.0 on the run_timing row it writes, so a window's real
    duration was never actually measured even though historical rows in
    production show it used to be. Real elapsed wall time (time.monotonic,
    not the injectable now_fn the deadline logic uses) must land here."""
    job_id, [rid] = _make_job(db_path, [("Req A", "high")])
    llm = MockLLMClient({"judge_batch": [_batch_ok([("1", None, "match")])]})

    judging.run_judging_window(db_path, job_id, llm, model="m")

    conn = connect(db_path)
    row = conn.execute("SELECT * FROM run_timing WHERE phase = 'judging' ORDER BY id DESC LIMIT 1").fetchone()
    conn.close()
    assert row is not None
    assert row["seconds_total"] > 0


def test_an_exception_escaping_the_whole_loop_still_closes_the_window(db_path, monkeypatch):
    """The per-batch try/except above covers _process_batch itself, but
    something else in the surrounding bookkeeping could still raise (here,
    record_run_timing, forced to for the test) -- run_judging_window's
    outer exception handler must force judging_deadline to "now" before
    re-raising, so a dead window can never stay open until its original
    20-minute deadline."""
    job_id, [rid] = _make_job(db_path, [("Req A", "high")])
    llm = MockLLMClient({"judge_batch": [_batch_ok([("1", None, "match")])]})

    def raising_record_run_timing(*args, **kwargs):
        raise RuntimeError("simulated bookkeeping crash")

    monkeypatch.setattr(judging, "record_run_timing", raising_record_run_timing)

    clock = FakeClock(start=datetime(2026, 1, 1, 0, 0, 0), step=timedelta(minutes=1))
    with pytest.raises(RuntimeError, match="simulated bookkeeping crash"):
        judging.run_judging_window(db_path, job_id, llm, model="m", now_fn=clock.now)

    # The exception still propagates (nothing here hides it) -- but the
    # window must not be left open until the untouched start+20m deadline.
    job = _job_row(db_path, job_id)
    assert job["judging_deadline"] != "2026-01-01 00:20:00"
