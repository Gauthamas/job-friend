"""Bug B's companion: resuming judging on whatever's still pending after
a window closed early. Same no-retry/batch rules as the first run --
resume_judging just calls run_judging_window again, unchanged."""

import json

from app.db import connect


def setup_job_two_requirements(client, mock_llm, db_path):
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
    mock_llm.queue("requirement_extract", json.dumps({
        "requirements": [{"text": "first", "weight": "high"}, {"text": "second", "weight": "high"}]
    }))
    # Batch size defaults to 2, so both requirements go in one chunk --
    # an invalid response leaves both 'pending' with no judgment written.
    mock_llm.queue("judge_batch", "not valid json")
    client.post(f"/api/jobs/{job_id}/submit-jd", json={"jd_text": "jd"})
    client.post(f"/api/jobs/{job_id}/start-judging")
    client.post(f"/api/jobs/{job_id}/finish")
    return job_id


def test_resume_judging_rejects_while_a_window_is_open(client, mock_llm, db_path):
    job_id = setup_job_two_requirements(client, mock_llm, db_path)
    conn = connect(db_path)
    conn.execute("UPDATE job SET judging_deadline = datetime('now', '+20 minutes') WHERE id = ?", (job_id,))
    conn.commit()
    conn.close()

    resp = client.post(f"/api/jobs/{job_id}/resume-judging")
    assert resp.status_code == 409


def test_resume_judging_rejects_when_nothing_is_pending(client, mock_llm, db_path):
    conn = connect(db_path)
    conn.execute("INSERT INTO profile (name) VALUES ('p')")
    conn.execute("INSERT INTO inventory (profile_id, name) VALUES (1, 'inv')")
    conn.commit()
    inv_id = conn.execute("SELECT id FROM inventory").fetchone()["id"]
    conn.close()
    flow_id = client.post("/api/flows", json={"name": "f", "inventory_id": inv_id}).json()["id"]
    job_id = client.post(f"/api/flows/{flow_id}/jobs", json={"title": "t"}).json()["job"]["id"]
    mock_llm.queue("requirement_extract", json.dumps({"requirements": [{"text": "x", "weight": "high"}]}))
    mock_llm.queue("judge_batch", json.dumps({"results": [{"req_id": "1", "units": [], "reason": "ok"}]}))
    client.post(f"/api/jobs/{job_id}/submit-jd", json={"jd_text": "jd"})
    client.post(f"/api/jobs/{job_id}/start-judging")
    client.post(f"/api/jobs/{job_id}/finish")

    resp = client.post(f"/api/jobs/{job_id}/resume-judging")
    assert resp.status_code == 400


def test_resume_judging_unknown_job_returns_404(client):
    resp = client.post("/api/jobs/999/resume-judging")
    assert resp.status_code == 404


def test_resume_judging_judges_only_the_pending_subset(client, mock_llm, db_path):
    job_id = setup_job_two_requirements(client, mock_llm, db_path)
    requirements = client.get(f"/api/jobs/{job_id}").json()["requirements"]
    assert all(r["requirement"]["status"] == "pending" for r in requirements)

    unit_id = connect(db_path).execute("SELECT id FROM unit").fetchone()["id"]
    mock_llm.queue("judge_batch", json.dumps({"results": [
        {"req_id": "1", "units": [{"id": f"1.U{unit_id}", "quote": "", "shows": "x", "needs": "x", "v": "match"}], "reason": "ok"},
        {"req_id": "2", "units": [], "reason": "no match"},
    ]}))

    resp = client.post(f"/api/jobs/{job_id}/resume-judging")
    assert resp.status_code == 200
    client.post(f"/api/jobs/{job_id}/finish")  # stale-snapshot pattern: resume's own response predates the write

    requirements = client.get(f"/api/jobs/{job_id}").json()["requirements"]
    assert all(r["requirement"]["status"] == "done" for r in requirements)
    proceed = client.post(f"/api/jobs/{job_id}/proceed").json()
    assert proceed["ok"] is True
    assert proceed["unjudged_count"] == 0


def test_resume_judging_respects_the_global_one_window_rule(client, mock_llm, db_path):
    job_id = setup_job_two_requirements(client, mock_llm, db_path)

    # A second job elsewhere with its own window open -- the global
    # one-window-at-a-time rule must block resume-judging on this job too.
    conn = connect(db_path)
    inv_id = conn.execute("SELECT id FROM inventory").fetchone()["id"]
    conn.close()
    flow_id = client.post("/api/flows", json={"name": "f2", "inventory_id": inv_id}).json()["id"]
    other_job_id = client.post(f"/api/flows/{flow_id}/jobs", json={"title": "t2"}).json()["job"]["id"]
    conn = connect(db_path)
    conn.execute("UPDATE job SET judging_deadline = datetime('now', '+20 minutes') WHERE id = ?", (other_job_id,))
    conn.commit()
    conn.close()

    resp = client.post(f"/api/jobs/{job_id}/resume-judging")
    assert resp.status_code == 409
