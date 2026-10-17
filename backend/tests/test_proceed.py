"""§3 Proceed gate: blocked (409) only while a window is open. Pending
requirements no longer block it -- a gap is a normal, expected outcome
(CLAUDE.md principle 4) -- but the response still carries a no_matches
flag when nothing matched or was weak, as a warning rather than a gate."""

import json

from app.db import connect


def create_job_with_one_requirement(client, mock_llm, db_path, judge_response):
    conn = connect(db_path)
    conn.execute("INSERT INTO profile (name) VALUES ('p')")
    conn.execute("INSERT INTO inventory (profile_id, name) VALUES (1, 'inv')")
    conn.execute("INSERT INTO role (inventory_id, company, title, sort_order) VALUES (1, 'c', 't', 0)")
    conn.execute("INSERT INTO unit (role_id, text, source, sort_order) VALUES (1, 'a unit', 'manual', 0)")
    conn.commit()
    inv_id = conn.execute("SELECT id FROM inventory").fetchone()["id"]
    unit_id = conn.execute("SELECT id FROM unit").fetchone()["id"]
    conn.close()

    flow_id = client.post("/api/flows", json={"name": "f", "inventory_id": inv_id}).json()["id"]
    job_id = client.post(f"/api/flows/{flow_id}/jobs", json={"title": "t"}).json()["job"]["id"]
    mock_llm.queue("requirement_extract", json.dumps({"requirements": [{"text": "x", "weight": "high"}]}))
    mock_llm.queue("judge_batch", judge_response(unit_id))
    client.post(f"/api/jobs/{job_id}/submit-jd", json={"jd_text": "jd"})
    client.post(f"/api/jobs/{job_id}/start-judging")
    return job_id


def test_proceed_blocked_while_window_open(client, mock_llm, db_path):
    # run_judging_window closes the window the instant its loop has
    # nothing left to try, and the mock's batch call returns instantly --
    # so by the time submit-jd returns, a real window would still be
    # mid-call but this one is already closed. Force the deadline back
    # into the future to test the 409 guard itself.
    job_id = create_job_with_one_requirement(
        client, mock_llm, db_path, lambda unit_id: "not valid json",
    )
    conn = connect(db_path)
    conn.execute("UPDATE job SET judging_deadline = datetime('now', '+20 minutes') WHERE id = ?", (job_id,))
    conn.commit()
    conn.close()

    resp = client.post(f"/api/jobs/{job_id}/proceed")
    assert resp.status_code == 409


def test_proceed_200_with_pending_requirement_once_window_closed(client, mock_llm, db_path):
    job_id = create_job_with_one_requirement(
        client, mock_llm, db_path, lambda unit_id: "not valid json",
    )
    client.post(f"/api/jobs/{job_id}/finish")

    resp = client.post(f"/api/jobs/{job_id}/proceed")
    assert resp.status_code == 200
    assert resp.json()["no_matches"] is True  # nothing matched or was weak -- still pending too


def test_proceed_200_with_no_matches_flag_when_all_done_but_none_matched(client, mock_llm, db_path):
    job_id = create_job_with_one_requirement(
        client, mock_llm, db_path,
        lambda unit_id: json.dumps({"results": [{"req_id": "1", "units": [], "reason": "no match"}]}),
    )
    client.post(f"/api/jobs/{job_id}/finish")

    resp = client.post(f"/api/jobs/{job_id}/proceed")
    assert resp.status_code == 200
    assert resp.json()["no_matches"] is True


def test_proceed_200_without_no_matches_flag_when_something_matched(client, mock_llm, db_path):
    job_id = create_job_with_one_requirement(
        client, mock_llm, db_path,
        lambda unit_id: json.dumps({"results": [
            {"req_id": "1", "units": [{"id": f"1.U{unit_id}", "quote": "", "shows": "fits", "needs": "fits", "v": "match"}], "reason": "ok"}
        ]}),
    )
    client.post(f"/api/jobs/{job_id}/finish")

    resp = client.post(f"/api/jobs/{job_id}/proceed")
    assert resp.status_code == 200
    assert resp.json()["no_matches"] is False


def test_proceed_unknown_job_returns_404(client):
    resp = client.post("/api/jobs/999/proceed")
    assert resp.status_code == 404


# --- Bug B: Proceed must not silently skip unjudged requirements ---

def test_proceed_ok_false_when_a_requirement_was_never_judged(client, mock_llm, db_path):
    """Same reproduction as test_proceed_200_with_pending_requirement_once_
    window_closed above (invalid JSON -> the batch write never happens,
    requirement stays 'pending' with no judgment carrying a verdict) --
    this is exactly the shape Proceed must now block on, not just a 200
    with no_matches."""
    job_id = create_job_with_one_requirement(
        client, mock_llm, db_path, lambda unit_id: "not valid json",
    )
    client.post(f"/api/jobs/{job_id}/finish")

    resp = client.post(f"/api/jobs/{job_id}/proceed")

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is False
    assert body["unjudged_count"] == 1


def test_proceed_ok_true_once_every_requirement_has_a_verdict(client, mock_llm, db_path):
    job_id = create_job_with_one_requirement(
        client, mock_llm, db_path,
        lambda unit_id: json.dumps({"results": [{"req_id": "1", "units": [], "reason": "no match"}]}),
    )
    client.post(f"/api/jobs/{job_id}/finish")

    resp = client.post(f"/api/jobs/{job_id}/proceed")

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["unjudged_count"] == 0
    assert body["no_matches"] is True  # still a valid, judged gap


def test_proceed_a_manually_set_verdict_counts_as_judged(client, mock_llm, db_path):
    job_id = create_job_with_one_requirement(
        client, mock_llm, db_path, lambda unit_id: "not valid json",
    )
    client.post(f"/api/jobs/{job_id}/finish")
    requirement_id = client.get(f"/api/jobs/{job_id}").json()["requirements"][0]["requirement"]["id"]
    judgment_id = client.get(f"/api/jobs/{job_id}").json()["requirements"][0]["judgments"][0]["id"]
    client.patch(f"/api/judgments/{judgment_id}", json={"user_verdict": "weak"})

    resp = client.post(f"/api/jobs/{job_id}/proceed")

    assert resp.json()["ok"] is True
    assert resp.json()["unjudged_count"] == 0


def test_proceed_ignores_a_deleted_requirement(client, mock_llm, db_path):
    job_id = create_job_with_one_requirement(
        client, mock_llm, db_path, lambda unit_id: "not valid json",
    )
    client.post(f"/api/jobs/{job_id}/finish")
    requirement_id = client.get(f"/api/jobs/{job_id}").json()["requirements"][0]["requirement"]["id"]
    client.delete(f"/api/requirements/{requirement_id}")

    resp = client.post(f"/api/jobs/{job_id}/proceed")

    assert resp.json()["ok"] is True
    assert resp.json()["unjudged_count"] == 0


def test_proceed_catches_a_requirement_pending_with_no_last_error_at_all(client, mock_llm, db_path):
    """Regression shape straight from a real production job's data: status='pending',
    last_error=NULL, zero judgment rows -- no error was ever recorded, the
    window just never got back to it (e.g. its background task died).
    Proceed must still catch this, not just the "batch call failed"
    shape the other tests above use."""
    job_id = create_job_with_one_requirement(
        client, mock_llm, db_path,
        lambda unit_id: json.dumps({"results": [{"req_id": "1", "units": [], "reason": "no match"}]}),
    )
    conn = connect(db_path)
    conn.execute(
        "INSERT INTO requirement (job_id, text, weight, source, status, sort_order) "
        "VALUES (?, 'never got to it', 'high', 'extracted', 'pending', 1)", (job_id,),
    )
    conn.commit()
    conn.close()
    client.post(f"/api/jobs/{job_id}/finish")

    resp = client.post(f"/api/jobs/{job_id}/proceed")

    assert resp.json()["ok"] is False
    assert resp.json()["unjudged_count"] == 1
