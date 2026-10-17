import json

from app.db import connect


def parse_events(resp) -> list[dict]:
    return [json.loads(block[len("data: "):]) for block in resp.text.split("\n\n") if block.strip()]


def setup_job_ready_to_judge(client, mock_llm, db_path):
    conn = connect(db_path)
    conn.execute("INSERT INTO profile (name) VALUES ('p')")
    conn.execute("INSERT INTO inventory (profile_id, name) VALUES (1, 'inv')")
    conn.execute("INSERT INTO role (inventory_id, company, title, sort_order) VALUES (1, 'c', 't', 0)")
    conn.execute("INSERT INTO unit (role_id, text, source, sort_order) VALUES (1, 'Fixed SDK crash bugs', 'manual', 0)")
    conn.commit()
    inv_id = conn.execute("SELECT id FROM inventory").fetchone()["id"]
    unit_id = conn.execute("SELECT id FROM unit").fetchone()["id"]
    conn.close()

    flow_id = client.post("/api/flows", json={"name": "f", "inventory_id": inv_id}).json()["id"]
    job_id = client.post(f"/api/flows/{flow_id}/jobs", json={"title": "t"}).json()["job"]["id"]
    mock_llm.queue("requirement_extract", json.dumps({
        "requirements": [{"text": "Error handling in SDKs", "weight": "high"}]
    }))
    return job_id, unit_id


def test_events_stream_reports_requirement_judged_then_judging_finished(client, mock_llm, db_path):
    job_id, unit_id = setup_job_ready_to_judge(client, mock_llm, db_path)
    mock_llm.queue("judge_batch", json.dumps({
        "results": [{"req_id": "1", "units": [{"id": f"1.U{unit_id}", "quote": "", "shows": "reason", "needs": "reason", "v": "match"}], "reason": "ok"}]
    }))
    job_resp = client.post(f"/api/jobs/{job_id}/submit-jd", json={"jd_text": "jd"})
    requirement_id = job_resp.json()["requirements"][0]["requirement"]["id"]
    client.post(f"/api/jobs/{job_id}/start-judging")

    # The window closes only once judging_deadline (20 real minutes out)
    # passes, or Finish is called -- Finish here, same as a user clicking
    # "Finish and complete manually" once everything they care about is done.
    client.post(f"/api/jobs/{job_id}/finish")

    resp = client.get(f"/api/jobs/{job_id}/events")
    assert resp.status_code == 200

    events = parse_events(resp)
    kinds = [e["event"] for e in events]
    assert "requirement_judged" in kinds
    assert "judging_finished" in kinds

    judged = next(e for e in events if e["event"] == "requirement_judged")
    assert judged["requirement_id"] == requirement_id
    assert judged["verdict"] == "match"
    assert len(judged["judgments"]) == 1


def test_events_stream_unknown_job_returns_404(client):
    resp = client.get("/api/jobs/999/events")
    assert resp.status_code == 404


def test_job_updated_carries_the_deadline_the_background_task_set(client, mock_llm, db_path, monkeypatch):
    # start-judging's own synchronous response always has judging_deadline =
    # None (the window only starts in the detached background task) -- a
    # client that only trusted that snapshot could never show the
    # blocking dialog. job_updated is what catches the deadline up.
    # The window stays "open" for the full 20 real minutes regardless of
    # finishing early, so cap MAX_STREAM_SECONDS short -- this test isn't
    # about judging_finished, just about job_updated arriving at all.
    import app.routers.jobs as jobs_module
    monkeypatch.setattr(jobs_module, "MAX_STREAM_SECONDS", 0.5)

    job_id, unit_id = setup_job_ready_to_judge(client, mock_llm, db_path)
    mock_llm.queue("judge_batch", json.dumps({"results": [{"req_id": "1", "units": [], "reason": "ok"}]}))
    client.post(f"/api/jobs/{job_id}/submit-jd", json={"jd_text": "jd"})
    start_resp = client.post(f"/api/jobs/{job_id}/start-judging")
    assert start_resp.json()["judging_deadline"] is None  # confirms the stale-snapshot premise

    resp = client.get(f"/api/jobs/{job_id}/events")
    events = parse_events(resp)
    job_updates = [e for e in events if e["event"] == "job_updated"]
    assert job_updates, "expected at least one job_updated event"
    assert job_updates[-1]["job"]["judging_deadline"] is not None
    assert job_updates[-1]["job"]["judging_started_at"] is not None


def test_everything_already_judged_closes_the_window_and_emits_judging_finished(client, mock_llm, db_path, monkeypatch):
    # Once every requirement the window covered is resolved (done or
    # no-match) with real time still left, run_judging_window closes the
    # window right away instead of leaving judging_deadline at its
    # original 20-minutes-out value -- so judging_finished fires on this
    # same poll instead of only once real wall-clock time catches up. Cap
    # MAX_STREAM_SECONDS short as a safety net in case that regresses.
    import app.routers.jobs as jobs_module
    monkeypatch.setattr(jobs_module, "MAX_STREAM_SECONDS", 2.0)

    job_id, unit_id = setup_job_ready_to_judge(client, mock_llm, db_path)
    mock_llm.queue("judge_batch", json.dumps({"results": [{"req_id": "1", "units": [], "reason": "no match"}]}))
    client.post(f"/api/jobs/{job_id}/submit-jd", json={"jd_text": "jd"})
    client.post(f"/api/jobs/{job_id}/start-judging")

    resp = client.get(f"/api/jobs/{job_id}/events")
    events = parse_events(resp)
    kinds = [e["event"] for e in events]
    assert "requirement_judged" in kinds
    assert "judging_finished" in kinds


def test_reconnect_replays_full_judgment_rows_including_corrections(client, mock_llm, db_path):
    job_id, unit_id = setup_job_ready_to_judge(client, mock_llm, db_path)
    mock_llm.queue("judge_batch", json.dumps({
        "results": [{"req_id": "1", "units": [{"id": f"1.U{unit_id}", "quote": "", "shows": "fixing crashes", "needs": "fixing crashes", "v": "match"}], "reason": "ok"}]
    }))
    job_resp = client.post(f"/api/jobs/{job_id}/submit-jd", json={"jd_text": "jd"})
    requirement_id = job_resp.json()["requirements"][0]["requirement"]["id"]
    client.post(f"/api/jobs/{job_id}/start-judging")
    client.post(f"/api/jobs/{job_id}/finish")

    conn = connect(db_path)
    # User corrects the model's verdict.
    conn.execute("UPDATE judgment SET user_verdict = 'weak' WHERE requirement_id = ?", (requirement_id,))
    conn.commit()
    # And manually attaches a second unit.
    conn.execute("INSERT INTO unit (role_id, text, source, sort_order) VALUES (1, 'Manual bullet', 'manual', 1)")
    conn.commit()
    manual_unit_id = conn.execute("SELECT id FROM unit ORDER BY id DESC LIMIT 1").fetchone()["id"]
    conn.execute(
        "INSERT INTO judgment (requirement_id, unit_id, added_by_user, user_verdict) VALUES (?, ?, 1, 'match')",
        (requirement_id, manual_unit_id),
    )
    conn.commit()
    conn.close()

    resp = client.get(f"/api/jobs/{job_id}/events")
    events = parse_events(resp)
    judged = next(e for e in events if e["event"] == "requirement_judged")

    judgments_by_unit = {j["unit_id"]: j for j in judged["judgments"]}
    assert judgments_by_unit[unit_id]["model_verdict"] == "match"
    assert judgments_by_unit[unit_id]["user_verdict"] == "weak"
    assert judgments_by_unit[unit_id]["why"] == "Shows: fixing crashes. Needs: fixing crashes."
    assert judgments_by_unit[manual_unit_id]["added_by_user"] is True
    assert judgments_by_unit[manual_unit_id]["user_verdict"] == "match"
    assert judgments_by_unit[manual_unit_id]["model_verdict"] is None
