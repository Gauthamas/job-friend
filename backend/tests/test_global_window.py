"""§3 rule 5 (only one window across all jobs) and the startup rule
(§13: "startup sets a future deadline to now")."""

import json

from app.db import connect


def create_inventory_and_flow(client, db_path, name="f"):
    conn = connect(db_path)
    conn.execute("INSERT INTO profile (name) VALUES ('p')")
    conn.execute("INSERT INTO inventory (profile_id, name) VALUES (1, 'inv')")
    conn.commit()
    inv_id = conn.execute("SELECT id FROM inventory").fetchone()["id"]
    conn.close()
    flow_id = client.post("/api/flows", json={"name": name, "inventory_id": inv_id}).json()["id"]
    return flow_id


def open_a_window(client, mock_llm, db_path, flow_id):
    """Submits a JD, then forces judging_deadline back into the future.
    run_judging_window now closes the window the instant its loop has
    nothing left to try, and the mock's batch call returns instantly --
    so by the time submit-jd's background task returns, a real window
    would still be mid-call but this one is already closed. Forcing the
    deadline simulates "still mid-window" for testing the 409 guards
    themselves, not run_judging_window's own closing logic (covered by
    test_judging_window.py)."""
    job_id = client.post(f"/api/flows/{flow_id}/jobs", json={"title": "t"}).json()["job"]["id"]
    mock_llm.queue("requirement_extract", json.dumps({"requirements": [{"text": "x", "weight": "high"}]}))
    mock_llm.queue("judge_batch", "not valid json")
    client.post(f"/api/jobs/{job_id}/submit-jd", json={"jd_text": "jd"})

    conn = connect(db_path)
    conn.execute("UPDATE job SET judging_deadline = datetime('now', '+20 minutes') WHERE id = ?", (job_id,))
    conn.commit()
    conn.close()

    return job_id


def test_second_job_create_409_while_a_window_is_open(client, mock_llm, db_path):
    flow_id = create_inventory_and_flow(client, db_path)
    open_a_window(client, mock_llm, db_path, flow_id)

    resp = client.post(f"/api/flows/{flow_id}/jobs", json={"title": "another"})
    assert resp.status_code == 409


def test_second_job_submit_jd_409_while_a_window_is_open_on_a_different_job(client, mock_llm, db_path):
    flow_id = create_inventory_and_flow(client, db_path)
    open_a_window(client, mock_llm, db_path, flow_id)

    # Create the second job before the window opened would also 409, so
    # bypass that by inserting it directly -- what's under test here is
    # submit-jd itself refusing while another job's window is open.
    conn = connect(db_path)
    conn.execute("INSERT INTO job (flow_id, title, jd_text) VALUES (?, 'second', '')", (flow_id,))
    conn.commit()
    second_job_id = conn.execute("SELECT id FROM job ORDER BY id DESC LIMIT 1").fetchone()["id"]
    conn.close()

    resp = client.post(f"/api/jobs/{second_job_id}/submit-jd", json={"jd_text": "jd2"})
    assert resp.status_code == 409


def test_retry_extraction_409_while_a_window_is_open_on_a_different_job(client, mock_llm, db_path):
    flow_id = create_inventory_and_flow(client, db_path)
    open_a_window(client, mock_llm, db_path, flow_id)

    conn = connect(db_path)
    conn.execute(
        "INSERT INTO job (flow_id, title, jd_text, jd_submitted_text, extraction_error) "
        "VALUES (?, 'second', '', 'failed jd', 'boom')",
        (flow_id,),
    )
    conn.commit()
    second_job_id = conn.execute("SELECT id FROM job ORDER BY id DESC LIMIT 1").fetchone()["id"]
    conn.close()

    resp = client.post(f"/api/jobs/{second_job_id}/retry-extraction")
    assert resp.status_code == 409


def test_resume_ingestion_409_while_a_window_is_open(client, mock_llm, db_path):
    flow_id = create_inventory_and_flow(client, db_path)
    open_a_window(client, mock_llm, db_path, flow_id)

    resp = client.post("/api/inventories", data={"name": "n", "text": "resume text"})
    assert resp.status_code == 409


def test_commit_inventory_409_while_a_window_is_open(client, mock_llm, db_path):
    flow_id = create_inventory_and_flow(client, db_path)
    open_a_window(client, mock_llm, db_path, flow_id)

    conn = connect(db_path)
    inv_id = conn.execute("SELECT id FROM inventory LIMIT 1").fetchone()["id"]
    conn.close()

    resp = client.post(f"/api/inventories/{inv_id}/commit", json={"roles": []})
    assert resp.status_code == 409


def test_add_unit_409_while_a_window_is_open(client, mock_llm, db_path):
    flow_id = create_inventory_and_flow(client, db_path)
    open_a_window(client, mock_llm, db_path, flow_id)

    conn = connect(db_path)
    conn.execute("INSERT INTO role (inventory_id, company, title, sort_order) VALUES (1, 'c', 't', 0)")
    conn.commit()
    role_id = conn.execute("SELECT id FROM role").fetchone()["id"]
    conn.close()

    resp = client.post(f"/api/roles/{role_id}/units", json={"text": "new unit"})
    assert resp.status_code == 409


def test_patch_unit_409_while_a_window_is_open(client, mock_llm, db_path):
    flow_id = create_inventory_and_flow(client, db_path)
    conn = connect(db_path)
    conn.execute("INSERT INTO role (inventory_id, company, title, sort_order) VALUES (1, 'c', 't', 0)")
    conn.execute("INSERT INTO unit (role_id, text, source, sort_order) VALUES (1, 'x', 'manual', 0)")
    conn.commit()
    unit_id = conn.execute("SELECT id FROM unit").fetchone()["id"]
    conn.close()

    open_a_window(client, mock_llm, db_path, flow_id)

    resp = client.patch(f"/api/units/{unit_id}", json={"text": "changed"})
    assert resp.status_code == 409


def test_everything_works_again_once_the_window_closes(client, mock_llm, db_path):
    flow_id = create_inventory_and_flow(client, db_path)
    job_id = open_a_window(client, mock_llm, db_path, flow_id)
    client.post(f"/api/jobs/{job_id}/finish")

    resp = client.post(f"/api/flows/{flow_id}/jobs", json={"title": "another"})
    assert resp.status_code == 200


def test_startup_sets_a_future_deadline_to_now(db_path, monkeypatch):
    from app.config import settings
    from app.judging import close_open_judging_windows

    conn = connect(db_path)
    conn.execute("INSERT INTO profile (name) VALUES ('p')")
    conn.execute("INSERT INTO inventory (profile_id, name) VALUES (1, 'inv')")
    conn.execute("INSERT INTO flow (profile_id, name, inventory_id) VALUES (1, 'f', 1)")
    conn.execute(
        "INSERT INTO job (flow_id, title, jd_text, judging_deadline) "
        "VALUES (1, 't', 'jd', datetime('now', '+20 minutes'))"
    )
    job_id = conn.execute("SELECT id FROM job").fetchone()["id"]
    conn.commit()
    conn.close()

    close_open_judging_windows(db_path)

    conn = connect(db_path)
    row = conn.execute("SELECT judging_deadline, datetime('now') AS now FROM job WHERE id = ?", (job_id,)).fetchone()
    conn.close()
    assert row["judging_deadline"] <= row["now"]


def test_startup_recovery_releases_the_lock_so_edits_work_again(client, mock_llm, db_path):
    """Reliability fix: a window's background task never survives a
    restart (a real production job showed exactly this -- 2 of 24
    requirements judged, the rest stuck 'pending' with no error, the
    deadline never closed). After a simulated restart with a future
    deadline and no running task, the lock must release -- edits allowed,
    pending requirements left untouched."""
    from app.judging import close_open_judging_windows

    flow_id = create_inventory_and_flow(client, db_path)
    job_id = client.post(f"/api/flows/{flow_id}/jobs", json={"title": "t"}).json()["job"]["id"]
    mock_llm.queue("requirement_extract", json.dumps({"requirements": [{"text": "x", "weight": "high"}]}))
    mock_llm.queue("judge_batch", "not valid json")  # leaves it pending, no error path taken
    client.post(f"/api/jobs/{job_id}/submit-jd", json={"jd_text": "jd"})
    client.post(f"/api/jobs/{job_id}/start-judging")
    requirement_id = client.get(f"/api/jobs/{job_id}").json()["requirements"][0]["requirement"]["id"]

    # Simulate the background task having died: force the deadline back
    # into the future, as if the window were still genuinely running.
    conn = connect(db_path)
    conn.execute("UPDATE job SET judging_deadline = datetime('now', '+20 minutes') WHERE id = ?", (job_id,))
    conn.commit()
    conn.close()

    assert client.patch(f"/api/requirements/{requirement_id}", json={"text": "blocked"}).status_code == 409

    close_open_judging_windows(db_path)  # the simulated restart

    resp = client.patch(f"/api/requirements/{requirement_id}", json={"text": "unblocked"})
    assert resp.status_code == 200

    # Pending requirements are untouched -- this is a lock release, not a
    # retry or a completion.
    body = client.get(f"/api/jobs/{job_id}").json()
    assert body["requirements"][0]["requirement"]["status"] == "pending"


def test_startup_leaves_null_and_past_deadlines_alone(db_path):
    from app.judging import close_open_judging_windows

    conn = connect(db_path)
    conn.execute("INSERT INTO profile (name) VALUES ('p')")
    conn.execute("INSERT INTO inventory (profile_id, name) VALUES (1, 'inv')")
    conn.execute("INSERT INTO flow (profile_id, name, inventory_id) VALUES (1, 'f', 1)")
    conn.execute("INSERT INTO job (flow_id, title, jd_text) VALUES (1, 'null_deadline', '')")
    conn.execute(
        "INSERT INTO job (flow_id, title, jd_text, judging_deadline) "
        "VALUES (1, 'past_deadline', '', datetime('now', '-5 minutes'))"
    )
    conn.commit()
    null_id = conn.execute("SELECT id FROM job WHERE title = 'null_deadline'").fetchone()["id"]
    past_id = conn.execute("SELECT id FROM job WHERE title = 'past_deadline'").fetchone()["id"]
    past_before = conn.execute("SELECT judging_deadline FROM job WHERE id = ?", (past_id,)).fetchone()["judging_deadline"]
    conn.close()

    from app.judging import close_open_judging_windows as cojw
    cojw(db_path)

    conn = connect(db_path)
    null_row = conn.execute("SELECT judging_deadline FROM job WHERE id = ?", (null_id,)).fetchone()
    past_row = conn.execute("SELECT judging_deadline FROM job WHERE id = ?", (past_id,)).fetchone()
    conn.close()
    assert null_row["judging_deadline"] is None
    assert past_row["judging_deadline"] == past_before
