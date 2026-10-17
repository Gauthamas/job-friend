import json

from app.db import connect


def create_inventory_and_flow(client, db_path):
    conn = connect(db_path)
    conn.execute("INSERT INTO profile (name) VALUES ('p')")
    conn.execute("INSERT INTO inventory (profile_id, name) VALUES (1, 'inv')")
    conn.commit()
    inv_id = conn.execute("SELECT id FROM inventory").fetchone()["id"]
    conn.close()

    flow_resp = client.post("/api/flows", json={"name": "My Flow", "inventory_id": inv_id})
    return inv_id, flow_resp


def add_unit(db_path, text="Fixed SDK crash bugs"):
    conn = connect(db_path)
    conn.execute("INSERT INTO role (inventory_id, company, title, sort_order) VALUES (1, 'c', 't', 0)")
    conn.execute("INSERT INTO unit (role_id, text, source, sort_order) VALUES (1, ?, 'manual', 0)", (text,))
    conn.commit()
    unit_id = conn.execute("SELECT id FROM unit ORDER BY id DESC LIMIT 1").fetchone()["id"]
    conn.close()
    return unit_id


def batch_response(pairs: list[tuple[str, int, str]]) -> str:
    """pairs: (small_req_id, unit_id_or_None, verdict_or_None) -- unit_id
    None means an empty units list (no match) for that requirement."""
    results = []
    for req_id, unit_id, verdict in pairs:
        units = [] if unit_id is None else [{"id": f"{req_id}.U{unit_id}", "quote": "", "shows": "fits", "needs": "fits", "v": verdict}]
        results.append({"req_id": req_id, "units": units, "reason": "ok"})
    return json.dumps({"results": results})


def test_create_flow(client, db_path):
    inv_id, flow_resp = create_inventory_and_flow(client, db_path)
    assert flow_resp.status_code == 200
    assert flow_resp.json()["inventory_id"] == inv_id


def test_create_flow_rejects_unknown_inventory(client):
    resp = client.post("/api/flows", json={"name": "f", "inventory_id": 999})
    assert resp.status_code == 404


def test_get_flow_unknown_returns_404(client):
    resp = client.get("/api/flows/999")
    assert resp.status_code == 404


def test_create_job_is_bare_title_only(client, db_path):
    _, flow_resp = create_inventory_and_flow(client, db_path)
    flow_id = flow_resp.json()["id"]

    resp = client.post(f"/api/flows/{flow_id}/jobs", json={"title": "SDK Engineer"})

    assert resp.status_code == 200
    body = resp.json()["job"]
    assert body["title"] == "SDK Engineer"
    assert body["jd_text"] == ""
    assert body["jd_submitted_text"] is None
    assert body["judging_deadline"] is None


def test_create_job_unknown_flow_returns_404(client):
    resp = client.post("/api/flows/999/jobs", json={"title": "t"})
    assert resp.status_code == 404


def test_list_flow_jobs_newest_first(client, db_path):
    _, flow_resp = create_inventory_and_flow(client, db_path)
    flow_id = flow_resp.json()["id"]
    first = client.post(f"/api/flows/{flow_id}/jobs", json={"title": "First"}).json()["job"]
    second = client.post(f"/api/flows/{flow_id}/jobs", json={"title": "Second"}).json()["job"]

    resp = client.get(f"/api/flows/{flow_id}/jobs")
    assert resp.status_code == 200
    ids = [j["id"] for j in resp.json()["jobs"]]
    assert ids == [second["id"], first["id"]]


def test_list_flow_jobs_empty_when_none_created(client, db_path):
    _, flow_resp = create_inventory_and_flow(client, db_path)
    flow_id = flow_resp.json()["id"]
    assert client.get(f"/api/flows/{flow_id}/jobs").json()["jobs"] == []


def test_list_flow_jobs_unknown_flow_returns_404(client):
    resp = client.get("/api/flows/999/jobs")
    assert resp.status_code == 404


def test_job_progress_defaults_to_job_screen(client, db_path):
    _, flow_resp = create_inventory_and_flow(client, db_path)
    flow_id = flow_resp.json()["id"]
    job_id = client.post(f"/api/flows/{flow_id}/jobs", json={"title": "t"}).json()["job"]["id"]

    assert client.get(f"/api/jobs/{job_id}/progress").json()["route"] == "job"


def test_job_progress_follows_pairs_threads_primary_secondary_and_letter(client, db_path):
    _, flow_resp = create_inventory_and_flow(client, db_path)
    flow_id = flow_resp.json()["id"]
    job_id = client.post(f"/api/flows/{flow_id}/jobs", json={"title": "t"}).json()["job"]["id"]

    conn = connect(db_path)
    conn.execute("INSERT INTO role (inventory_id, company, title, sort_order) VALUES (1, 'c', 't', 0)")
    conn.execute("INSERT INTO unit (role_id, text, source, sort_order) VALUES (1, 'u1', 'manual', 0)")
    conn.execute("INSERT INTO unit (role_id, text, source, sort_order) VALUES (1, 'u2', 'manual', 1)")
    u1, u2 = [r["id"] for r in conn.execute("SELECT id FROM unit ORDER BY id").fetchall()]
    conn.execute(
        "INSERT INTO pair (job_id, unit_a_id, unit_b_id, score, model) VALUES (?, ?, ?, 0.5, 'm')", (job_id, u1, u2)
    )
    conn.commit()
    conn.close()
    assert client.get(f"/api/jobs/{job_id}/progress").json()["route"] == "statements"

    conn = connect(db_path)
    conn.execute(
        "INSERT INTO thread_run (job_id, params_json, statements_snapshot_json) VALUES (?, '{}', '[]')", (job_id,)
    )
    conn.commit()
    conn.close()
    assert client.get(f"/api/jobs/{job_id}/progress").json()["route"] == "threads"

    conn = connect(db_path)
    run_id = conn.execute("SELECT id FROM thread_run WHERE job_id = ?", (job_id,)).fetchone()["id"]
    conn.execute("INSERT INTO thread (run_id, idea, source) VALUES (?, 'idea', 'model')", (run_id,))
    thread_id = conn.execute("SELECT id FROM thread ORDER BY id DESC LIMIT 1").fetchone()["id"]
    conn.execute("INSERT INTO job_thread (job_id, thread_id, role) VALUES (?, ?, 'primary')", (job_id, thread_id))
    conn.commit()
    conn.close()
    assert client.get(f"/api/jobs/{job_id}/progress").json()["route"] == "primary_secondary"

    conn = connect(db_path)
    conn.execute("INSERT INTO letter (job_id, finished) VALUES (?, 1)", (job_id,))
    conn.commit()
    conn.close()
    assert client.get(f"/api/jobs/{job_id}/progress").json()["route"] == "write"


def test_job_progress_unknown_job_returns_404(client):
    resp = client.get("/api/jobs/999/progress")
    assert resp.status_code == 404


def test_patch_job_title_never_blocked_and_never_reruns(client, mock_llm, db_path):
    _, flow_resp = create_inventory_and_flow(client, db_path)
    flow_id = flow_resp.json()["id"]
    job_id = client.post(f"/api/flows/{flow_id}/jobs", json={"title": "Old title"}).json()["job"]["id"]

    resp = client.patch(f"/api/jobs/{job_id}", json={"title": "New title"})

    assert resp.status_code == 200
    assert resp.json()["title"] == "New title"
    assert resp.json()["jd_submitted_text"] is None  # unaffected


def test_patch_job_company_and_role_title_are_optional_and_partial(client, mock_llm, db_path):
    _, flow_resp = create_inventory_and_flow(client, db_path)
    flow_id = flow_resp.json()["id"]
    job_id = client.post(f"/api/flows/{flow_id}/jobs", json={"title": "t"}).json()["job"]["id"]

    # Neither field set yet -- nothing breaks when empty.
    body = client.get(f"/api/jobs/{job_id}").json()["job"]
    assert body["company"] is None
    assert body["role_title"] is None

    resp = client.patch(f"/api/jobs/{job_id}", json={"company": "Acme", "role_title": "Engineer"})
    assert resp.status_code == 200
    assert resp.json()["company"] == "Acme"
    assert resp.json()["role_title"] == "Engineer"

    # Partial: updating only title leaves company/role_title untouched.
    resp = client.patch(f"/api/jobs/{job_id}", json={"title": "New title"})
    assert resp.json()["title"] == "New title"
    assert resp.json()["company"] == "Acme"
    assert resp.json()["role_title"] == "Engineer"

    # Explicit null clears a field.
    resp = client.patch(f"/api/jobs/{job_id}", json={"company": None})
    assert resp.json()["company"] is None
    assert resp.json()["role_title"] == "Engineer"


def test_submit_jd_extracts_but_does_not_start_judging(client, mock_llm, db_path):
    _, flow_resp = create_inventory_and_flow(client, db_path)
    flow_id = flow_resp.json()["id"]
    add_unit(db_path)
    job_id = client.post(f"/api/flows/{flow_id}/jobs", json={"title": "t"}).json()["job"]["id"]

    mock_llm.queue("requirement_extract", json.dumps({
        "requirements": [{"text": "Error handling in SDKs", "weight": "high"}]
    }))
    # No "judge_batch" response queued -- extraction alone must never call
    # the model to judge anything; judging only starts via start-judging.

    resp = client.post(f"/api/jobs/{job_id}/submit-jd", json={"jd_text": "some JD text"})

    assert resp.status_code == 200
    body = resp.json()
    assert len(body["requirements"]) == 1
    assert body["job"]["judging_deadline"] is None
    assert body["job"]["judging_started_at"] is None

    get_body = client.get(f"/api/jobs/{job_id}").json()
    assert get_body["requirements"][0]["requirement"]["status"] == "pending"
    assert get_body["requirements"][0]["verdict"] == "gap"
    assert get_body["job"]["jd_submitted_text"] == "some JD text"
    assert get_body["job"]["jd_text"] == "some JD text"


def test_start_judging_runs_the_window_on_the_extracted_requirements(client, mock_llm, db_path):
    _, flow_resp = create_inventory_and_flow(client, db_path)
    flow_id = flow_resp.json()["id"]
    unit_id = add_unit(db_path)
    job_id = client.post(f"/api/flows/{flow_id}/jobs", json={"title": "t"}).json()["job"]["id"]

    mock_llm.queue("requirement_extract", json.dumps({
        "requirements": [{"text": "Error handling in SDKs", "weight": "high"}]
    }))
    mock_llm.queue("judge_batch", batch_response([("1", unit_id, "match")]))
    client.post(f"/api/jobs/{job_id}/submit-jd", json={"jd_text": "some JD text"})

    resp = client.post(f"/api/jobs/{job_id}/start-judging")
    assert resp.status_code == 200
    # Same stale-snapshot shape as submit-jd's own response: judging_deadline
    # is only set inside the detached background task, not in the route
    # handler's own response body.
    assert resp.json()["judging_deadline"] is None

    # TestClient runs the background task (run_judging_window) synchronously,
    # and MockLLMClient responds instantly -- so by the time control returns
    # to this test, the one batch has already been judged.
    get_body = client.get(f"/api/jobs/{job_id}").json()
    assert get_body["job"]["judging_started_at"] is not None
    assert get_body["requirements"][0]["requirement"]["status"] == "done"
    assert get_body["requirements"][0]["verdict"] == "match"


def test_start_judging_twice_is_rejected(client, mock_llm, db_path):
    _, flow_resp = create_inventory_and_flow(client, db_path)
    flow_id = flow_resp.json()["id"]
    unit_id = add_unit(db_path)
    job_id = client.post(f"/api/flows/{flow_id}/jobs", json={"title": "t"}).json()["job"]["id"]
    mock_llm.queue("requirement_extract", json.dumps({"requirements": [{"text": "x", "weight": "high"}]}))
    mock_llm.queue("judge_batch", batch_response([("1", unit_id, "match")]))
    client.post(f"/api/jobs/{job_id}/submit-jd", json={"jd_text": "jd"})

    first = client.post(f"/api/jobs/{job_id}/start-judging")
    assert first.status_code == 200

    second = client.post(f"/api/jobs/{job_id}/start-judging")
    assert second.status_code == 409


def test_start_judging_without_a_submitted_jd_returns_400(client, db_path):
    _, flow_resp = create_inventory_and_flow(client, db_path)
    flow_id = flow_resp.json()["id"]
    job_id = client.post(f"/api/flows/{flow_id}/jobs", json={"title": "t"}).json()["job"]["id"]

    resp = client.post(f"/api/jobs/{job_id}/start-judging")
    assert resp.status_code == 400


def test_start_judging_unknown_job_returns_404(client):
    resp = client.post("/api/jobs/999/start-judging")
    assert resp.status_code == 404


def test_edits_allowed_before_judging_started(client, mock_llm, db_path):
    """Requirement #2: before Start judging, the user can delete, edit,
    and add requirements -- the existing edit endpoints, just no longer
    blocked at this stage since judging_deadline stays null."""
    _, flow_resp = create_inventory_and_flow(client, db_path)
    flow_id = flow_resp.json()["id"]
    job_id = client.post(f"/api/flows/{flow_id}/jobs", json={"title": "t"}).json()["job"]["id"]
    mock_llm.queue("requirement_extract", json.dumps({"requirements": [{"text": "original", "weight": "high"}]}))
    body = client.post(f"/api/jobs/{job_id}/submit-jd", json={"jd_text": "jd"}).json()
    requirement_id = body["requirements"][0]["requirement"]["id"]

    add_resp = client.post(f"/api/jobs/{job_id}/requirements", json={"text": "added", "weight": "low"})
    assert add_resp.status_code == 201
    assert add_resp.json()["source"] == "user"
    assert add_resp.json()["status"] == "pending"

    edit_resp = client.patch(f"/api/requirements/{requirement_id}", json={"text": "edited"})
    assert edit_resp.status_code == 200
    assert edit_resp.json()["text"] == "edited"

    delete_resp = client.delete(f"/api/requirements/{requirement_id}")
    assert delete_resp.status_code == 204


def test_edits_blocked_once_judging_started(client, mock_llm, db_path):
    _, flow_resp = create_inventory_and_flow(client, db_path)
    flow_id = flow_resp.json()["id"]
    unit_id = add_unit(db_path)
    job_id = client.post(f"/api/flows/{flow_id}/jobs", json={"title": "t"}).json()["job"]["id"]
    mock_llm.queue("requirement_extract", json.dumps({"requirements": [{"text": "x", "weight": "high"}]}))
    mock_llm.queue("judge_batch", "not valid json")  # leaves it pending, mid-window
    body = client.post(f"/api/jobs/{job_id}/submit-jd", json={"jd_text": "jd"}).json()
    requirement_id = body["requirements"][0]["requirement"]["id"]
    client.post(f"/api/jobs/{job_id}/start-judging")

    # run_judging_window closes the window instantly once it has nothing
    # left to try and the mock responds instantly -- force the deadline
    # back into the future to test the edit-block guard itself, not
    # run_judging_window's own closing logic (test_judging_window.py).
    conn = connect(db_path)
    conn.execute("UPDATE job SET judging_deadline = datetime('now', '+20 minutes') WHERE id = ?", (job_id,))
    conn.commit()
    conn.close()

    assert client.post(f"/api/jobs/{job_id}/requirements", json={"text": "x", "weight": "low"}).status_code == 409
    assert client.patch(f"/api/requirements/{requirement_id}", json={"text": "y"}).status_code == 409
    assert client.delete(f"/api/requirements/{requirement_id}").status_code == 409


def test_existing_job_with_a_judging_deadline_counts_as_started(client, db_path):
    """Requirement #5: a job that already has a judging_deadline (set the
    old way, before this review step existed) counts as started -- no
    migration needed, start-judging just refuses it."""
    _, flow_resp = create_inventory_and_flow(client, db_path)
    flow_id = flow_resp.json()["id"]
    job_id = client.post(f"/api/flows/{flow_id}/jobs", json={"title": "t"}).json()["job"]["id"]
    conn = connect(db_path)
    conn.execute(
        "UPDATE job SET jd_submitted_text = 'jd', judging_started_at = datetime('now', '-30 minutes'), "
        "judging_deadline = datetime('now', '-10 minutes') WHERE id = ?",
        (job_id,),
    )
    conn.commit()
    conn.close()

    resp = client.post(f"/api/jobs/{job_id}/start-judging")
    assert resp.status_code == 409


def test_existing_job_with_a_judged_requirement_counts_as_started(client, db_path):
    """Requirement #5's other half: a judged requirement with no
    judging_deadline at all (the defensive fallback) also counts. Keyed
    off a judgment row's model_verdict, not requirement.status='done' --
    that status also results from a purely manual action (No match,
    attach-unit, a hand-set verdict) during the review step, which must
    NOT look like judging already started."""
    _, flow_resp = create_inventory_and_flow(client, db_path)
    flow_id = flow_resp.json()["id"]
    job_id = client.post(f"/api/flows/{flow_id}/jobs", json={"title": "t"}).json()["job"]["id"]
    conn = connect(db_path)
    conn.execute("UPDATE job SET jd_submitted_text = 'jd' WHERE id = ?", (job_id,))
    conn.execute(
        "INSERT INTO requirement (job_id, text, weight, source, status, sort_order) "
        "VALUES (?, 'x', 'high', 'extracted', 'done', 0)", (job_id,),
    )
    conn.execute("INSERT INTO role (inventory_id, company, title, sort_order) VALUES (1, 'c', 't', 0)")
    conn.execute("INSERT INTO unit (role_id, text, source, sort_order) VALUES (1, 'a unit', 'manual', 0)")
    conn.commit()
    requirement_id = conn.execute("SELECT id FROM requirement WHERE job_id = ?", (job_id,)).fetchone()["id"]
    unit_id = conn.execute("SELECT id FROM unit").fetchone()["id"]
    conn.execute(
        "INSERT INTO judgment (requirement_id, unit_id, model_verdict) VALUES (?, ?, 'match')",
        (requirement_id, unit_id),
    )
    conn.commit()
    conn.close()

    resp = client.post(f"/api/jobs/{job_id}/start-judging")
    assert resp.status_code == 409


def test_a_requirement_marked_done_by_hand_before_start_does_not_count_as_started(client, mock_llm, db_path):
    """The other side of the fix above: a requirement a user has already
    completed by hand (e.g. attach-unit, or the No-match action) during
    the review step carries no model_verdict at all, so it must not block
    Start judging for the rest of the job."""
    _, flow_resp = create_inventory_and_flow(client, db_path)
    flow_id = flow_resp.json()["id"]
    job_id = client.post(f"/api/flows/{flow_id}/jobs", json={"title": "t"}).json()["job"]["id"]
    mock_llm.queue("requirement_extract", json.dumps({"requirements": [{"text": "x", "weight": "high"}]}))
    body = client.post(f"/api/jobs/{job_id}/submit-jd", json={"jd_text": "jd"}).json()
    requirement_id = body["requirements"][0]["requirement"]["id"]

    resp = client.post(f"/api/requirements/{requirement_id}/no-match")
    assert resp.status_code == 200

    mock_llm.queue("judge_batch", json.dumps({"results": []}))
    resp = client.post(f"/api/jobs/{job_id}/start-judging")
    assert resp.status_code == 200


def test_submit_jd_rejects_unchanged_text(client, mock_llm, db_path):
    _, flow_resp = create_inventory_and_flow(client, db_path)
    flow_id = flow_resp.json()["id"]
    job_id = client.post(f"/api/flows/{flow_id}/jobs", json={"title": "t"}).json()["job"]["id"]
    mock_llm.queue("requirement_extract", json.dumps({"requirements": [{"text": "x", "weight": "high"}]}))
    mock_llm.queue("judge_batch", batch_response([("1", None, "match")]))
    client.post(f"/api/jobs/{job_id}/submit-jd", json={"jd_text": "same text"})
    # The window stays "open" (now < judging_deadline) for the full 20
    # minutes regardless of finishing early -- Finish is what a real UI
    # would call once every requirement is done; do that here so this test
    # is isolated from the busy-guard and actually exercises the
    # unchanged-text check instead.
    client.post(f"/api/jobs/{job_id}/finish")

    resp = client.post(f"/api/jobs/{job_id}/submit-jd", json={"jd_text": "same text"})
    assert resp.status_code == 400


def test_submit_jd_resubmit_wipes_requirements_and_judgments_only(client, mock_llm, db_path):
    _, flow_resp = create_inventory_and_flow(client, db_path)
    flow_id = flow_resp.json()["id"]
    unit_id = add_unit(db_path)
    job_id = client.post(f"/api/flows/{flow_id}/jobs", json={"title": "t"}).json()["job"]["id"]

    mock_llm.queue("requirement_extract", json.dumps({"requirements": [{"text": "first", "weight": "high"}]}))
    mock_llm.queue("judge_batch", batch_response([("1", unit_id, "match")]))
    client.post(f"/api/jobs/{job_id}/submit-jd", json={"jd_text": "first JD"})
    first_requirement_id = client.get(f"/api/jobs/{job_id}").json()["requirements"][0]["requirement"]["id"]
    client.post(f"/api/jobs/{job_id}/finish")  # close the first window so submit-jd isn't blocked by it

    mock_llm.queue("requirement_extract", json.dumps({"requirements": [{"text": "second", "weight": "high"}]}))
    mock_llm.queue("judge_batch", batch_response([("1", unit_id, "weak")]))
    resp = client.post(f"/api/jobs/{job_id}/submit-jd", json={"jd_text": "second JD"})

    assert resp.status_code == 200
    body = client.get(f"/api/jobs/{job_id}").json()
    assert len(body["requirements"]) == 1
    assert body["requirements"][0]["requirement"]["text"] == "second"
    assert body["requirements"][0]["requirement"]["id"] != first_requirement_id

    # Units and enrichment (inventory) are untouched.
    conn = connect(db_path)
    unit_row = conn.execute("SELECT text, deleted FROM unit WHERE id = ?", (unit_id,)).fetchone()
    conn.close()
    assert unit_row["deleted"] == 0
    assert unit_row["text"] == "Fixed SDK crash bugs"


def test_resubmit_after_real_judging_resets_judging_started_so_the_button_shows_again(client, mock_llm, db_path):
    """Bug A: has_judging_started() used to keep reading the previous
    run's stale judging_deadline as "already started" on the brand-new
    requirements a resubmit creates, permanently hiding Start judging."""
    _, flow_resp = create_inventory_and_flow(client, db_path)
    flow_id = flow_resp.json()["id"]
    unit_id = add_unit(db_path)
    job_id = client.post(f"/api/flows/{flow_id}/jobs", json={"title": "t"}).json()["job"]["id"]

    mock_llm.queue("requirement_extract", json.dumps({"requirements": [{"text": "first", "weight": "high"}]}))
    mock_llm.queue("judge_batch", batch_response([("1", unit_id, "match")]))
    client.post(f"/api/jobs/{job_id}/submit-jd", json={"jd_text": "first JD"})
    client.post(f"/api/jobs/{job_id}/start-judging")  # real judging: sets judging_deadline/started_at

    body = client.get(f"/api/jobs/{job_id}").json()
    assert body["job"]["judging_deadline"] is not None
    assert body["job"]["judging_started_at"] is not None
    assert client.post(f"/api/jobs/{job_id}/start-judging").status_code == 409  # already started

    mock_llm.queue("requirement_extract", json.dumps({"requirements": [{"text": "second", "weight": "high"}]}))
    resp = client.post(f"/api/jobs/{job_id}/submit-jd", json={"jd_text": "second JD"})

    assert resp.status_code == 200
    assert resp.json()["job"]["judging_deadline"] is None
    assert resp.json()["job"]["judging_started_at"] is None

    # Start judging must be available again on the new requirements.
    mock_llm.queue("judge_batch", batch_response([("1", unit_id, "weak")]))
    resp = client.post(f"/api/jobs/{job_id}/start-judging")
    assert resp.status_code == 200


def test_resubmit_after_real_judging_deletes_the_old_judgments(client, mock_llm, db_path):
    _, flow_resp = create_inventory_and_flow(client, db_path)
    flow_id = flow_resp.json()["id"]
    unit_id = add_unit(db_path)
    job_id = client.post(f"/api/flows/{flow_id}/jobs", json={"title": "t"}).json()["job"]["id"]

    mock_llm.queue("requirement_extract", json.dumps({"requirements": [{"text": "first", "weight": "high"}]}))
    mock_llm.queue("judge_batch", batch_response([("1", unit_id, "match")]))
    client.post(f"/api/jobs/{job_id}/submit-jd", json={"jd_text": "first JD"})
    client.post(f"/api/jobs/{job_id}/start-judging")
    client.post(f"/api/jobs/{job_id}/finish")

    conn = connect(db_path)
    old_judgment_ids = {r["id"] for r in conn.execute("SELECT id FROM judgment").fetchall()}
    conn.close()
    assert old_judgment_ids  # the real judging run above wrote at least one

    mock_llm.queue("requirement_extract", json.dumps({"requirements": [{"text": "second", "weight": "high"}]}))
    client.post(f"/api/jobs/{job_id}/submit-jd", json={"jd_text": "second JD"})

    # Shortlisting the new requirement writes its own fresh judgment
    # row(s) -- what must be gone is every judgment id from the old run.
    conn = connect(db_path)
    remaining_ids = {r["id"] for r in conn.execute("SELECT id FROM judgment").fetchall()}
    conn.close()
    assert remaining_ids.isdisjoint(old_judgment_ids)


def test_submit_jd_404_for_unknown_job(client):
    resp = client.post("/api/jobs/999/submit-jd", json={"jd_text": "x"})
    assert resp.status_code == 404


def test_get_job_unknown_returns_404(client):
    resp = client.get("/api/jobs/999")
    assert resp.status_code == 404
