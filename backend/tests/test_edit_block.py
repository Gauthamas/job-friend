"""§3's edit block: while a job's own window is open, verdict changes,
add-unit, requirement edit/add/delete, and Proceed all 409; once it
closes they work again."""

import json

from app.db import connect


def setup_job_with_pending_requirement(client, mock_llm, db_path):
    """A job with one 'pending' requirement and one shortlisted unit
    (judgment row, model_verdict NULL). The mock's batch call returns
    instantly (no real waiting), and run_judging_window now closes the
    window the moment its loop has nothing left to try -- so by the time
    submit-jd's background task returns, the window is already closed.
    To test the 409 guards (not run_judging_window's own closing logic,
    which test_judging_window.py covers), force judging_deadline back
    into the future directly, simulating "still mid-window" the same way
    a real, still-running call would leave it."""
    conn = connect(db_path)
    conn.execute("INSERT INTO profile (name) VALUES ('p')")
    conn.execute("INSERT INTO inventory (profile_id, name) VALUES (1, 'inv')")
    conn.execute("INSERT INTO role (inventory_id, company, title, sort_order) VALUES (1, 'c', 't', 0)")
    conn.execute("INSERT INTO unit (role_id, text, source, sort_order) VALUES (1, 'a unit', 'manual', 0)")
    conn.commit()
    inv_id = conn.execute("SELECT id FROM inventory").fetchone()["id"]
    conn.close()

    flow_id = client.post("/api/flows", json={"name": "f", "inventory_id": inv_id}).json()["id"]
    job_id = client.post(f"/api/flows/{flow_id}/jobs", json={"title": "t"}).json()["job"]["id"]
    mock_llm.queue("requirement_extract", json.dumps({"requirements": [{"text": "x", "weight": "high"}]}))
    mock_llm.queue("judge_batch", "not valid json")  # leaves the requirement pending
    resp = client.post(f"/api/jobs/{job_id}/submit-jd", json={"jd_text": "jd"})
    requirement_id = resp.json()["requirements"][0]["requirement"]["id"]
    judgment_id = resp.json()["requirements"][0]["judgments"][0]["id"]

    conn = connect(db_path)
    conn.execute("UPDATE job SET judging_deadline = datetime('now', '+20 minutes') WHERE id = ?", (job_id,))
    conn.commit()
    conn.close()

    return job_id, requirement_id, judgment_id


def test_patch_judgment_409_while_open_then_works_once_closed(client, mock_llm, db_path):
    job_id, requirement_id, judgment_id = setup_job_with_pending_requirement(client, mock_llm, db_path)

    resp = client.patch(f"/api/judgments/{judgment_id}", json={"user_verdict": "match"})
    assert resp.status_code == 409

    client.post(f"/api/jobs/{job_id}/finish")
    resp = client.patch(f"/api/judgments/{judgment_id}", json={"user_verdict": "match"})
    assert resp.status_code == 200


def test_attach_unit_409_while_open_then_works_once_closed(client, mock_llm, db_path):
    job_id, requirement_id, _ = setup_job_with_pending_requirement(client, mock_llm, db_path)
    conn = connect(db_path)
    conn.execute("INSERT INTO unit (role_id, text, source, sort_order) VALUES (1, 'another unit', 'manual', 1)")
    conn.commit()
    other_unit_id = conn.execute("SELECT id FROM unit ORDER BY id DESC LIMIT 1").fetchone()["id"]
    conn.close()

    resp = client.post(f"/api/requirements/{requirement_id}/units", json={"unit_id": other_unit_id})
    assert resp.status_code == 409

    client.post(f"/api/jobs/{job_id}/finish")
    resp = client.post(f"/api/requirements/{requirement_id}/units", json={"unit_id": other_unit_id})
    assert resp.status_code == 201


def test_patch_requirement_409_while_open_then_works_once_closed(client, mock_llm, db_path):
    job_id, requirement_id, _ = setup_job_with_pending_requirement(client, mock_llm, db_path)

    resp = client.patch(f"/api/requirements/{requirement_id}", json={"text": "new text"})
    assert resp.status_code == 409

    client.post(f"/api/jobs/{job_id}/finish")
    resp = client.patch(f"/api/requirements/{requirement_id}", json={"text": "new text"})
    assert resp.status_code == 200


def test_add_requirement_409_while_open_then_works_once_closed(client, mock_llm, db_path):
    job_id, _, _ = setup_job_with_pending_requirement(client, mock_llm, db_path)

    resp = client.post(f"/api/jobs/{job_id}/requirements", json={"text": "new req", "weight": "low"})
    assert resp.status_code == 409

    client.post(f"/api/jobs/{job_id}/finish")
    resp = client.post(f"/api/jobs/{job_id}/requirements", json={"text": "new req", "weight": "low"})
    assert resp.status_code == 201


def test_delete_requirement_409_while_open_then_works_once_closed(client, mock_llm, db_path):
    job_id, requirement_id, _ = setup_job_with_pending_requirement(client, mock_llm, db_path)

    resp = client.delete(f"/api/requirements/{requirement_id}")
    assert resp.status_code == 409

    client.post(f"/api/jobs/{job_id}/finish")
    resp = client.delete(f"/api/requirements/{requirement_id}")
    assert resp.status_code == 204


def test_setting_a_verdict_completes_a_pending_requirement_no_separate_done_action(client, mock_llm, db_path):
    job_id, requirement_id, judgment_id = setup_job_with_pending_requirement(client, mock_llm, db_path)
    client.post(f"/api/jobs/{job_id}/finish")

    resp = client.patch(f"/api/judgments/{judgment_id}", json={"user_verdict": "match"})

    assert resp.status_code == 200
    assert resp.json()["requirement_status"] == "done"
    assert client.get(f"/api/jobs/{job_id}").json()["requirements"][0]["requirement"]["status"] == "done"


def test_proceed_409_while_open_then_200_with_pending_once_closed(client, mock_llm, db_path):
    job_id, requirement_id, _ = setup_job_with_pending_requirement(client, mock_llm, db_path)

    resp = client.post(f"/api/jobs/{job_id}/proceed")
    assert resp.status_code == 409

    client.post(f"/api/jobs/{job_id}/finish")
    resp = client.post(f"/api/jobs/{job_id}/proceed")
    assert resp.status_code == 200  # pending requirements no longer block Proceed -- a gap is normal


def test_editing_requirement_text_or_weight_keeps_verdicts_and_status(client, mock_llm, db_path):
    job_id, requirement_id, judgment_id = setup_job_with_pending_requirement(client, mock_llm, db_path)
    client.post(f"/api/jobs/{job_id}/finish")

    conn = connect(db_path)
    conn.execute("UPDATE judgment SET model_verdict = 'weak', why = 'x' WHERE id = ?", (judgment_id,))
    conn.execute("UPDATE requirement SET status = 'done' WHERE id = ?", (requirement_id,))
    conn.commit()
    conn.close()

    resp = client.patch(f"/api/requirements/{requirement_id}", json={"text": "edited text", "weight": "low"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["text"] == "edited text"
    assert body["weight"] == "low"
    assert body["status"] == "done"  # untouched

    conn = connect(db_path)
    row = conn.execute("SELECT model_verdict, why FROM judgment WHERE id = ?", (judgment_id,)).fetchone()
    conn.close()
    assert row["model_verdict"] == "weak"
    assert row["why"] == "x"
