"""§3.1 extraction failure: no window opens, job.extraction_error is set,
Retry re-runs."""

import json

from app.db import connect


def create_inventory_and_flow(client, db_path):
    conn = connect(db_path)
    conn.execute("INSERT INTO profile (name) VALUES ('p')")
    conn.execute("INSERT INTO inventory (profile_id, name) VALUES (1, 'inv')")
    conn.commit()
    inv_id = conn.execute("SELECT id FROM inventory").fetchone()["id"]
    conn.close()
    return client.post("/api/flows", json={"name": "f", "inventory_id": inv_id}).json()["id"]


def test_malformed_extraction_opens_no_window_and_sets_extraction_error(client, mock_llm, db_path):
    flow_id = create_inventory_and_flow(client, db_path)
    job_id = client.post(f"/api/flows/{flow_id}/jobs", json={"title": "t"}).json()["job"]["id"]
    mock_llm.queue("requirement_extract", "not valid json")

    resp = client.post(f"/api/jobs/{job_id}/submit-jd", json={"jd_text": "jd"})

    assert resp.status_code == 200
    body = resp.json()
    assert body["requirements"] == []
    assert body["job"]["extraction_error"] is not None
    assert body["job"]["judging_deadline"] is None
    assert body["job"]["judging_started_at"] is None


def test_zero_requirements_opens_no_window_and_sets_extraction_error(client, mock_llm, db_path):
    flow_id = create_inventory_and_flow(client, db_path)
    job_id = client.post(f"/api/flows/{flow_id}/jobs", json={"title": "t"}).json()["job"]["id"]
    mock_llm.queue("requirement_extract", json.dumps({"requirements": []}))

    resp = client.post(f"/api/jobs/{job_id}/submit-jd", json={"jd_text": "jd"})

    body = resp.json()
    assert body["requirements"] == []
    assert body["job"]["extraction_error"] is not None
    assert body["job"]["judging_deadline"] is None


def test_retry_extraction_reruns_on_the_same_submitted_text(client, mock_llm, db_path):
    flow_id = create_inventory_and_flow(client, db_path)
    job_id = client.post(f"/api/flows/{flow_id}/jobs", json={"title": "t"}).json()["job"]["id"]
    mock_llm.queue("requirement_extract", "not valid json")
    client.post(f"/api/jobs/{job_id}/submit-jd", json={"jd_text": "the real jd text"})

    mock_llm.queue("requirement_extract", json.dumps({"requirements": [{"text": "ok now", "weight": "high"}]}))
    mock_llm.queue("judge_batch", json.dumps({"results": [{"req_id": "1", "units": [], "reason": "ok"}]}))

    resp = client.post(f"/api/jobs/{job_id}/retry-extraction")

    assert resp.status_code == 200
    body = resp.json()
    assert len(body["requirements"]) == 1
    assert body["requirements"][0]["requirement"]["text"] == "ok now"
    assert body["job"]["extraction_error"] is None
    assert body["job"]["jd_submitted_text"] == "the real jd text"


def test_retry_extraction_without_a_prior_submit_returns_400(client, db_path):
    flow_id = create_inventory_and_flow(client, db_path)
    job_id = client.post(f"/api/flows/{flow_id}/jobs", json={"title": "t"}).json()["job"]["id"]

    resp = client.post(f"/api/jobs/{job_id}/retry-extraction")
    assert resp.status_code == 400


def test_retry_extraction_unknown_job_returns_404(client):
    resp = client.post("/api/jobs/999/retry-extraction")
    assert resp.status_code == 404
