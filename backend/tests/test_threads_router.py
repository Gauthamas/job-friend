"""Milestone 4: the thread-discovery endpoints -- 409 gates, run history,
and the edit actions (move/remove/merge/delete/idea), none of which call
the model."""

import json

from app.db import connect


def setup_job(db_path: str) -> int:
    conn = connect(db_path)
    conn.execute("INSERT INTO profile (name) VALUES ('p')")
    conn.execute("INSERT INTO inventory (profile_id, name) VALUES (1, 'inv')")
    conn.execute("INSERT INTO role (inventory_id, company, title, sort_order) VALUES (1, 'c', 't', 0)")
    conn.execute("INSERT INTO flow (profile_id, name, inventory_id) VALUES (1, 'f', 1)")
    conn.execute("INSERT INTO job (flow_id, title, jd_text) VALUES (1, 'job', 'jd')")
    job_id = conn.execute("SELECT id FROM job ORDER BY id DESC LIMIT 1").fetchone()["id"]
    conn.commit()
    conn.close()
    return job_id


def add_written_pair(db_path: str, job_id: int, text: str) -> int:
    conn = connect(db_path)
    conn.execute("INSERT INTO unit (role_id, text, source, sort_order) VALUES (1, 'unit a', 'manual', 0)")
    unit_a = conn.execute("SELECT id FROM unit ORDER BY id DESC LIMIT 1").fetchone()["id"]
    conn.execute("INSERT INTO unit (role_id, text, source, sort_order) VALUES (1, 'unit b', 'manual', 1)")
    unit_b = conn.execute("SELECT id FROM unit ORDER BY id DESC LIMIT 1").fetchone()["id"]
    conn.execute(
        "INSERT INTO pair (job_id, unit_a_id, unit_b_id, score, model) VALUES (?, ?, ?, 0.5, 'm')",
        (job_id, unit_a, unit_b),
    )
    pair_id = conn.execute("SELECT id FROM pair ORDER BY id DESC LIMIT 1").fetchone()["id"]
    conn.execute("INSERT INTO statement (pair_id, status, text) VALUES (?, 'written', ?)", (pair_id, text))
    statement_id = conn.execute("SELECT id FROM statement ORDER BY id DESC LIMIT 1").fetchone()["id"]
    conn.commit()
    conn.close()
    return statement_id


def run_with_two_threads(client, mock_llm, job_id):
    mock_llm.queue("propose_threads", json.dumps({
        "threads": [
            {"idea": "Thread A", "supporting_statement_ids": ["1", "2", "3"]},
        ],
        "unused": ["4", "5", "6"],
    }))
    mock_llm.queue("assign_unused", json.dumps({"thread": "none"}))
    mock_llm.queue("assign_unused", json.dumps({"thread": "none"}))
    mock_llm.queue("assign_unused", json.dumps({"thread": "none"}))
    for _ in range(6):
        mock_llm.queue("verify_thread", json.dumps({"verdict": "no", "quote": ""}))
    resp = client.post(f"/api/jobs/{job_id}/threads/run")
    assert resp.status_code == 200
    return resp.json()


def test_can_run_reports_not_blocked_by_default(client, db_path):
    job_id = setup_job(db_path)
    resp = client.get(f"/api/jobs/{job_id}/threads/can-run")
    assert resp.status_code == 200
    assert resp.json()["blocked"] is False


def test_run_409_when_judging_window_open(client, mock_llm, db_path):
    job_id = setup_job(db_path)
    conn = connect(db_path)
    conn.execute("UPDATE job SET judging_deadline = datetime('now', '+20 minutes') WHERE id = ?", (job_id,))
    conn.commit()
    conn.close()

    assert client.get(f"/api/jobs/{job_id}/threads/can-run").json()["blocked"] is True
    assert client.post(f"/api/jobs/{job_id}/threads/run").status_code == 409


def test_run_409_when_autofilled_statement_unconfirmed(client, mock_llm, db_path):
    job_id = setup_job(db_path)
    other_job_id = setup_job(db_path)
    statement_id = add_written_pair(db_path, job_id, "x")
    conn = connect(db_path)
    conn.execute(
        "UPDATE statement SET autofilled_from_job_id = ?, confirmed = 0 WHERE id = ?", (other_job_id, statement_id)
    )
    conn.commit()
    conn.close()

    assert client.get(f"/api/jobs/{job_id}/threads/can-run").json()["blocked"] is True
    assert client.post(f"/api/jobs/{job_id}/threads/run").status_code == 409


def test_run_creates_threads_and_history_keeps_both_runs(client, mock_llm, db_path):
    job_id = setup_job(db_path)
    for i in range(6):
        add_written_pair(db_path, job_id, f"s{i}")

    body1 = run_with_two_threads(client, mock_llm, job_id)
    assert len(body1["threads"]) == 1

    mock_llm.queue("propose_threads", json.dumps({"threads": [], "unused": [str(i) for i in range(1, 7)]}))
    for _ in range(6):
        mock_llm.queue("assign_unused", json.dumps({"thread": "none"}))
    resp2 = client.post(f"/api/jobs/{job_id}/threads/run")
    assert resp2.status_code == 200

    history = client.get(f"/api/jobs/{job_id}/threads/history").json()["runs"]
    assert len(history) == 2

    latest = client.get(f"/api/jobs/{job_id}/threads").json()
    assert latest["id"] == history[0]["id"]  # most recent first
    old_run = client.get(f"/api/thread-runs/{body1['id']}").json()
    assert len(old_run["threads"]) == 1  # the first run's thread is still viewable


def test_edit_idea_move_remove_and_delete_thread(client, mock_llm, db_path):
    job_id = setup_job(db_path)
    for i in range(6):
        add_written_pair(db_path, job_id, f"s{i}")
    body = run_with_two_threads(client, mock_llm, job_id)
    thread_id = body["threads"][0]["id"]
    statement_ids = [s["statement_id"] for s in body["threads"][0]["statements"]]

    resp = client.patch(f"/api/threads/{thread_id}", json={"idea": "Edited idea"})
    assert resp.json()["edited_idea"] == "Edited idea"

    resp = client.delete(f"/api/threads/{thread_id}/statements/{statement_ids[0]}")
    assert len(resp.json()["statements"]) == 2

    resp = client.delete(f"/api/threads/{thread_id}")
    assert resp.status_code == 204
    assert client.get(f"/api/jobs/{job_id}/threads").json()["threads"] == []


def test_move_statement_between_threads(client, mock_llm, db_path):
    job_id = setup_job(db_path)
    for i in range(6):
        add_written_pair(db_path, job_id, f"s{i}")
    mock_llm.queue("propose_threads", json.dumps({
        "threads": [
            {"idea": "Thread A", "supporting_statement_ids": ["1", "2", "3"]},
            {"idea": "Thread B", "supporting_statement_ids": ["4", "5", "6"]},
        ],
        "unused": [],
    }))
    for _ in range(12):
        mock_llm.queue("verify_thread", json.dumps({"verdict": "no", "quote": ""}))
    body = client.post(f"/api/jobs/{job_id}/threads/run").json()
    thread_a, thread_b = body["threads"]
    statement_from_b = thread_b["statements"][0]["statement_id"]

    resp = client.post(f"/api/threads/{thread_a['id']}/statements", json={"statement_id": statement_from_b})
    assert resp.status_code == 201
    assert statement_from_b in {s["statement_id"] for s in resp.json()["statements"]}

    refreshed_b = next(t for t in client.get(f"/api/jobs/{job_id}/threads").json()["threads"] if t["id"] == thread_b["id"])
    assert statement_from_b not in {s["statement_id"] for s in refreshed_b["statements"]}


def test_merge_threads(client, mock_llm, db_path):
    job_id = setup_job(db_path)
    for i in range(6):
        add_written_pair(db_path, job_id, f"s{i}")
    mock_llm.queue("propose_threads", json.dumps({
        "threads": [
            {"idea": "Thread A", "supporting_statement_ids": ["1", "2", "3"]},
            {"idea": "Thread B", "supporting_statement_ids": ["4", "5", "6"]},
        ],
        "unused": [],
    }))
    for _ in range(12):
        mock_llm.queue("verify_thread", json.dumps({"verdict": "no", "quote": ""}))
    body = client.post(f"/api/jobs/{job_id}/threads/run").json()
    thread_a, thread_b = body["threads"]

    resp = client.post(f"/api/threads/{thread_a['id']}/merge", json={"other_thread_id": thread_b["id"]})
    assert resp.status_code == 200
    assert len(resp.json()["statements"]) == 6
    assert len(resp.json()["units"]) == 12  # 6 pairs, 2 units each, no overlap -> union of all

    remaining = client.get(f"/api/jobs/{job_id}/threads").json()["threads"]
    assert len(remaining) == 1


def test_editing_a_statement_marks_its_thread_stale_via_the_endpoint(client, mock_llm, db_path):
    job_id = setup_job(db_path)
    for i in range(6):
        add_written_pair(db_path, job_id, f"s{i}")
    body = run_with_two_threads(client, mock_llm, job_id)
    thread_id = body["threads"][0]["id"]
    statement_id = body["threads"][0]["statements"][0]["statement_id"]

    assert client.get(f"/api/jobs/{job_id}/threads").json()["threads"][0]["stale"] is False

    client.patch(f"/api/statements/{statement_id}", json={"status": "written", "text": "edited"})
    assert client.get(f"/api/jobs/{job_id}/threads").json()["threads"][0]["stale"] is True


def test_below_min_thread_is_promotable_via_use_anyway(client, mock_llm, db_path):
    job_id = setup_job(db_path)
    for i in range(2):
        add_written_pair(db_path, job_id, f"s{i}")
    mock_llm.queue("propose_threads", json.dumps({
        "threads": [{"idea": "Too small", "supporting_statement_ids": ["1", "2"]}],  # below default min_support=3
        "unused": [],
    }))
    for _ in range(4):  # 2 statements -> 4 units
        mock_llm.queue("verify_thread", json.dumps({"verdict": "no", "quote": ""}))
    body = client.post(f"/api/jobs/{job_id}/threads/run").json()
    assert len(body["threads"]) == 1
    thread = body["threads"][0]
    assert thread["below_min"] is True

    resp = client.post(f"/api/threads/{thread['id']}/promote")
    assert resp.status_code == 200
    assert resp.json()["below_min"] is False

    refetched = client.get(f"/api/jobs/{job_id}/threads").json()["threads"][0]
    assert refetched["below_min"] is False
