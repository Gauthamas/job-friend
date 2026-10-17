"""Manual "No match": a plain DB write, no model call. Keeps every
candidate judgment row -- only sets each one's user_verdict to 'none'
("no selection"), preserving model_verdict/why/score -- and marks the
requirement done with no match, which reads as a gap. Re-selecting a unit
(the existing chip-cycle/attach-unit UI) restores a normal matched state.
Allowed exactly where every other edit is (§3's edit block); blocked
while the job's own window is open."""

import json

from app.db import connect
from app.judging import has_judging_started
from tests.test_edit_block import setup_job_with_pending_requirement
from tests.test_requirements_router import setup_job_with_requirement


def test_mark_no_match_keeps_candidate_rows_and_clears_selections(client, mock_llm, db_path):
    job_id, requirement_id = setup_job_with_requirement(client, mock_llm, db_path)
    conn = connect(db_path)
    conn.execute("INSERT INTO role (inventory_id, company, title, sort_order) VALUES (1, 'c', 't', 0)")
    conn.execute("INSERT INTO unit (role_id, text, source, sort_order) VALUES (1, 'a unit', 'manual', 0)")
    conn.commit()
    unit_id = conn.execute("SELECT id FROM unit").fetchone()["id"]
    conn.execute(
        "INSERT INTO judgment (requirement_id, unit_id, model_verdict, why) VALUES (?, ?, 'match', 'Shows: x. Needs: y.')",
        (requirement_id, unit_id),
    )
    conn.commit()
    conn.close()
    # No "judge_batch" response queued -- if this made a model call it would raise.
    calls_before = len(mock_llm.calls)

    resp = client.post(f"/api/requirements/{requirement_id}/no-match")

    assert resp.status_code == 200
    body = resp.json()
    assert len(body["judgments"]) == 1
    assert body["judgments"][0]["user_verdict"] == "none"
    assert body["judgments"][0]["model_verdict"] == "match"  # preserved
    assert body["judgments"][0]["why"] == "Shows: x. Needs: y."  # preserved
    assert body["verdict"] == "gap"
    assert body["requirement"]["status"] == "done"
    assert body["requirement"]["reason"] == "marked by user"
    assert len(mock_llm.calls) == calls_before

    conn = connect(db_path)
    row = conn.execute(
        "SELECT * FROM judgment WHERE requirement_id = ?", (requirement_id,)
    ).fetchone()
    conn.close()
    assert row is not None  # row kept, not deleted
    assert row["user_verdict"] == "none"
    assert row["model_verdict"] == "match"
    assert row["why"] == "Shows: x. Needs: y."


def test_reselecting_a_unit_after_no_match_restores_matched_state(client, mock_llm, db_path):
    job_id, requirement_id = setup_job_with_requirement(client, mock_llm, db_path)
    conn = connect(db_path)
    conn.execute("INSERT INTO role (inventory_id, company, title, sort_order) VALUES (1, 'c', 't', 0)")
    conn.execute("INSERT INTO unit (role_id, text, source, sort_order) VALUES (1, 'a unit', 'manual', 0)")
    conn.commit()
    unit_id = conn.execute("SELECT id FROM unit").fetchone()["id"]
    conn.execute(
        "INSERT INTO judgment (requirement_id, unit_id, model_verdict, why) VALUES (?, ?, 'match', 'x')",
        (requirement_id, unit_id),
    )
    conn.commit()
    judgment_id = conn.execute(
        "SELECT id FROM judgment WHERE requirement_id = ?", (requirement_id,)
    ).fetchone()["id"]
    conn.close()

    no_match_resp = client.post(f"/api/requirements/{requirement_id}/no-match")
    assert no_match_resp.json()["verdict"] == "gap"

    # The existing chip-cycle UI (PATCH /api/judgments/{id}) is all it
    # takes to undo -- no dedicated "re-judge" action.
    resp = client.patch(f"/api/judgments/{judgment_id}", json={"user_verdict": "match"})

    assert resp.status_code == 200
    assert resp.json()["judgment"]["user_verdict"] == "match"
    assert resp.json()["requirement_verdict"] == "match"

    body = client.get(f"/api/jobs/{job_id}").json()
    entry = next(r for r in body["requirements"] if r["requirement"]["id"] == requirement_id)
    assert entry["verdict"] == "match"
    assert entry["judgments"][0]["user_verdict"] == "match"


def test_has_judging_started_stays_true_after_judging_even_with_a_no_match_mark(client, mock_llm, db_path):
    job_id, requirement_id = setup_job_with_requirement(client, mock_llm, db_path)
    # setup_job_with_requirement's batch call already set a real
    # model_verdict (even with an empty shortlist, judge_batch ran) --
    # marking it away afterward must not erase that signal.
    client.post(f"/api/requirements/{requirement_id}/no-match")

    conn = connect(db_path)
    started = has_judging_started(conn, job_id)
    conn.close()
    assert started is True


def test_has_judging_started_stays_false_when_nothing_was_judged_even_with_no_match_marks(client, mock_llm, db_path):
    conn = connect(db_path)
    conn.execute("INSERT INTO profile (name) VALUES ('p')")
    conn.execute("INSERT INTO inventory (profile_id, name) VALUES (1, 'inv')")
    conn.commit()
    inv_id = conn.execute("SELECT id FROM inventory").fetchone()["id"]
    conn.close()

    flow_id = client.post("/api/flows", json={"name": "f", "inventory_id": inv_id}).json()["id"]
    job_id = client.post(f"/api/flows/{flow_id}/jobs", json={"title": "t"}).json()["job"]["id"]
    mock_llm.queue("requirement_extract", json.dumps({"requirements": [{"text": "x", "weight": "high"}]}))
    body = client.post(f"/api/jobs/{job_id}/submit-jd", json={"jd_text": "jd"}).json()
    requirement_id = body["requirements"][0]["requirement"]["id"]

    # Marked away during the review step -- no judging call has ever run.
    resp = client.post(f"/api/requirements/{requirement_id}/no-match")
    assert resp.status_code == 200

    conn = connect(db_path)
    started = has_judging_started(conn, job_id)
    conn.close()
    assert started is False


def test_mark_no_match_unknown_requirement_returns_404(client):
    resp = client.post("/api/requirements/999/no-match")
    assert resp.status_code == 404


def test_mark_no_match_409_while_window_open_then_works_once_closed(client, mock_llm, db_path):
    job_id, requirement_id, _ = setup_job_with_pending_requirement(client, mock_llm, db_path)

    resp = client.post(f"/api/requirements/{requirement_id}/no-match")
    assert resp.status_code == 409

    client.post(f"/api/jobs/{job_id}/finish")
    resp = client.post(f"/api/requirements/{requirement_id}/no-match")
    assert resp.status_code == 200
    assert resp.json()["requirement"]["status"] == "done"


def test_requirement_marked_before_start_is_never_sent_to_the_model(client, mock_llm, db_path):
    conn = connect(db_path)
    conn.execute("INSERT INTO profile (name) VALUES ('p')")
    conn.execute("INSERT INTO inventory (profile_id, name) VALUES (1, 'inv')")
    conn.commit()
    inv_id = conn.execute("SELECT id FROM inventory").fetchone()["id"]
    conn.close()

    flow_id = client.post("/api/flows", json={"name": "f", "inventory_id": inv_id}).json()["id"]
    job_id = client.post(f"/api/flows/{flow_id}/jobs", json={"title": "t"}).json()["job"]["id"]

    mock_llm.queue("requirement_extract", json.dumps({
        "requirements": [
            {"text": "Marked-away requirement, unmistakable text", "weight": "high"},
            {"text": "Remaining requirement to judge", "weight": "high"},
        ]
    }))
    resp = client.post(f"/api/jobs/{job_id}/submit-jd", json={"jd_text": "jd"})
    requirements = resp.json()["requirements"]
    marked_id = requirements[0]["requirement"]["id"]
    remaining_id = requirements[1]["requirement"]["id"]

    # Review step: mark one away before Start -- no model call yet.
    mark_resp = client.post(f"/api/requirements/{marked_id}/no-match")
    assert mark_resp.status_code == 200

    # Only the remaining requirement's own small_id ("1", since it's alone
    # in its batch) is queued -- if the marked one were included too, the
    # batch would ask for two results and this response would be short.
    mock_llm.queue("judge_batch", json.dumps({
        "results": [{"req_id": "1", "units": [], "reason": "no candidates"}]
    }))
    client.post(f"/api/jobs/{job_id}/start-judging")
    client.post(f"/api/jobs/{job_id}/finish")

    judge_batch_calls = [msg for name, msg in mock_llm.calls if name == "judge_batch"]
    assert len(judge_batch_calls) == 1
    assert "Remaining requirement to judge" in judge_batch_calls[0]
    assert "Marked-away requirement" not in judge_batch_calls[0]

    body = client.get(f"/api/jobs/{job_id}").json()
    by_id = {r["requirement"]["id"]: r for r in body["requirements"]}
    assert by_id[marked_id]["requirement"]["reason"] == "marked by user"
    assert by_id[marked_id]["judgments"] == []
    assert by_id[remaining_id]["requirement"]["status"] == "done"
