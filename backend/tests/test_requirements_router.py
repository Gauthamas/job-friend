import json

from app.db import connect


def setup_job_with_requirement(client, mock_llm, db_path):
    """A job with one 'done' requirement, no shortlisted candidate (so the
    window finishes with nothing left pending) -- fast, deterministic, and
    done with it so later edits/actions aren't blocked by an open window."""
    conn = connect(db_path)
    conn.execute("INSERT INTO profile (name) VALUES ('p')")
    conn.execute("INSERT INTO inventory (profile_id, name) VALUES (1, 'inv')")
    conn.commit()
    inv_id = conn.execute("SELECT id FROM inventory").fetchone()["id"]
    conn.close()

    flow_id = client.post("/api/flows", json={"name": "f", "inventory_id": inv_id}).json()["id"]
    job_id = client.post(f"/api/flows/{flow_id}/jobs", json={"title": "t"}).json()["job"]["id"]

    mock_llm.queue("requirement_extract", json.dumps({
        "requirements": [{"text": "Error handling in SDKs", "weight": "high"}]
    }))
    mock_llm.queue("judge_batch", json.dumps({
        "results": [{"req_id": "1", "units": [], "reason": "no candidates"}]
    }))
    resp = client.post(f"/api/jobs/{job_id}/submit-jd", json={"jd_text": "jd"})
    requirement_id = resp.json()["requirements"][0]["requirement"]["id"]
    client.post(f"/api/jobs/{job_id}/start-judging")

    # Close the window so later edit-block actions in these tests aren't
    # themselves blocked by it (it stays "open" for the full 20 minutes
    # regardless of finishing early -- see judging.py).
    client.post(f"/api/jobs/{job_id}/finish")

    return job_id, requirement_id


def test_add_requirement_is_pending_with_shortlist_no_model_call(client, mock_llm, db_path):
    job_id, first_id = setup_job_with_requirement(client, mock_llm, db_path)
    # No "judge_batch" response queued -- adding a requirement never calls the model.

    resp = client.post(f"/api/jobs/{job_id}/requirements", json={"text": "User-added requirement", "weight": "high"})

    assert resp.status_code == 201
    body = resp.json()
    assert body["source"] == "user"
    assert body["status"] == "pending"


def test_add_requirement_unknown_job_returns_404(client):
    resp = client.post("/api/jobs/999/requirements", json={"text": "x", "weight": "high"})
    assert resp.status_code == 404


def test_patch_requirement_text_keeps_verdict_and_status(client, mock_llm, db_path):
    # §3 rule 10: editing text/weight never touches verdicts or status --
    # this is the opposite of the earlier milestone's behavior.
    job_id, requirement_id = setup_job_with_requirement(client, mock_llm, db_path)
    conn = connect(db_path)
    conn.execute("INSERT INTO role (inventory_id, company, title, sort_order) VALUES (1, 'c', 't', 0)")
    conn.execute("INSERT INTO unit (role_id, text, source, sort_order) VALUES (1, 'a unit', 'manual', 0)")
    conn.commit()
    unit_id = conn.execute("SELECT id FROM unit").fetchone()["id"]
    conn.execute(
        "INSERT INTO judgment (requirement_id, unit_id, model_verdict, why) VALUES (?, ?, 'match', 'reason')",
        (requirement_id, unit_id),
    )
    conn.execute("UPDATE requirement SET status = 'done' WHERE id = ?", (requirement_id,))
    conn.commit()
    conn.close()

    resp = client.patch(f"/api/requirements/{requirement_id}", json={"text": "Revised requirement text"})

    assert resp.status_code == 200
    body = resp.json()
    assert body["text"] == "Revised requirement text"
    assert body["status"] == "done"  # untouched

    conn = connect(db_path)
    row = conn.execute(
        "SELECT model_verdict, why FROM judgment WHERE requirement_id = ? AND unit_id = ?", (requirement_id, unit_id)
    ).fetchone()
    conn.close()
    assert row["model_verdict"] == "match"
    assert row["why"] == "reason"


def test_patch_requirement_weight_also_keeps_verdict_and_status(client, mock_llm, db_path):
    job_id, requirement_id = setup_job_with_requirement(client, mock_llm, db_path)
    conn = connect(db_path)
    conn.execute("INSERT INTO role (inventory_id, company, title, sort_order) VALUES (1, 'c', 't', 0)")
    conn.execute("INSERT INTO unit (role_id, text, source, sort_order) VALUES (1, 'a unit', 'manual', 0)")
    conn.commit()
    unit_id = conn.execute("SELECT id FROM unit").fetchone()["id"]
    conn.execute(
        "INSERT INTO judgment (requirement_id, unit_id, model_verdict) VALUES (?, ?, 'match')",
        (requirement_id, unit_id),
    )
    conn.execute("UPDATE requirement SET status = 'done' WHERE id = ?", (requirement_id,))
    conn.commit()
    conn.close()

    resp = client.patch(f"/api/requirements/{requirement_id}", json={"weight": "low"})

    assert resp.status_code == 200
    body = resp.json()
    assert body["weight"] == "low"
    assert body["status"] == "done"


def test_patch_requirement_rejects_empty_text(client, mock_llm, db_path):
    _, requirement_id = setup_job_with_requirement(client, mock_llm, db_path)
    resp = client.patch(f"/api/requirements/{requirement_id}", json={"text": ""})
    assert resp.status_code == 400


def test_patch_requirement_unknown_returns_404(client):
    resp = client.patch("/api/requirements/999", json={"weight": "low"})
    assert resp.status_code == 404


def test_delete_requirement_soft_deletes(client, mock_llm, db_path):
    _, requirement_id = setup_job_with_requirement(client, mock_llm, db_path)

    resp = client.delete(f"/api/requirements/{requirement_id}")

    assert resp.status_code == 204
    assert client.patch(f"/api/requirements/{requirement_id}", json={"weight": "low"}).status_code == 404


def test_delete_requirement_unknown_returns_404(client):
    resp = client.delete("/api/requirements/999")
    assert resp.status_code == 404


def test_attach_unit_creates_judgment_instantly_no_model_call(client, mock_llm, db_path):
    job_id, requirement_id = setup_job_with_requirement(client, mock_llm, db_path)

    conn = connect(db_path)
    conn.execute("INSERT INTO role (inventory_id, company, title, sort_order) VALUES (1, 'c', 't', 0)")
    conn.execute("INSERT INTO unit (role_id, text, source, sort_order) VALUES (1, 'manual unit text', 'manual', 0)")
    conn.commit()
    unit_id = conn.execute("SELECT id FROM unit").fetchone()["id"]
    conn.close()

    # No "judge_batch" fixture queued: if this hit the model it would raise.
    resp = client.post(f"/api/requirements/{requirement_id}/units", json={"unit_id": unit_id})

    assert resp.status_code == 201
    body = resp.json()
    assert body["judgment"]["added_by_user"] is True
    assert body["judgment"]["user_verdict"] == "match"
    assert body["judgment"]["model_verdict"] is None


def test_attach_unit_unknown_unit_returns_404(client, mock_llm, db_path):
    _, requirement_id = setup_job_with_requirement(client, mock_llm, db_path)
    resp = client.post(f"/api/requirements/{requirement_id}/units", json={"unit_id": 999})
    assert resp.status_code == 404


def test_attaching_a_unit_completes_a_pending_requirement_no_separate_done_action(client, mock_llm, db_path):
    # setup_job_with_requirement's one requirement is already 'done' (its
    # batch call succeeded with an empty shortlist) -- add a fresh,
    # genuinely 'pending' one to attach a unit to.
    job_id, _ = setup_job_with_requirement(client, mock_llm, db_path)
    resp = client.post(f"/api/jobs/{job_id}/requirements", json={"text": "Another one", "weight": "low"})
    requirement_id = resp.json()["id"]
    assert resp.json()["status"] == "pending"

    conn = connect(db_path)
    conn.execute("INSERT INTO role (inventory_id, company, title, sort_order) VALUES (1, 'c', 't', 0)")
    conn.execute("INSERT INTO unit (role_id, text, source, sort_order) VALUES (1, 'a unit', 'manual', 0)")
    conn.commit()
    unit_id = conn.execute("SELECT id FROM unit").fetchone()["id"]
    conn.close()

    resp = client.post(f"/api/requirements/{requirement_id}/units", json={"unit_id": unit_id})

    assert resp.status_code == 201
    assert resp.json()["requirement_status"] == "done"
    assert client.get(f"/api/jobs/{job_id}").json()["requirements"][1]["requirement"]["status"] == "done"


