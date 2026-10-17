"""Milestone 5: primary/secondary endpoints -- persistence, suggest,
swap, stale-on-delete, manual thread. No LLM calls."""

from app.config import settings
from app.db import connect
from tests.test_thread_ranking import add_pair_with_statement, add_requirement_judgment, make_model_thread, setup_job


def test_only_one_candidate_gives_only_primary(client, db_path, monkeypatch):
    monkeypatch.setattr(settings, "min_support", 1)
    job_id = setup_job(db_path)
    s1, u1a, u1b = add_pair_with_statement(db_path, job_id, "s1")
    make_model_thread(db_path, job_id, "Only one", [s1])

    resp = client.get(f"/api/jobs/{job_id}/primary-secondary")
    body = resp.json()
    assert body["primary"]["thread"] is not None
    assert body["secondary"]["thread"] is None


def test_empty_state_reason_distinguishes_no_threads_from_below_min_support(client, db_path, monkeypatch):
    job_id = setup_job(db_path)
    resp = client.get(f"/api/jobs/{job_id}/primary-secondary").json()
    assert resp["primary"]["thread"] is None
    assert "No threads" in resp["empty_reason"]

    monkeypatch.setattr(settings, "min_support", 5)
    s1, _, _ = add_pair_with_statement(db_path, job_id, "s1")
    make_model_thread(db_path, job_id, "Too small", [s1], below_min=True)
    resp2 = client.get(f"/api/jobs/{job_id}/primary-secondary").json()
    assert resp2["primary"]["thread"] is None
    assert "at least" in resp2["empty_reason"]


def test_pick_and_swap_persist_after_reload(client, db_path, monkeypatch):
    monkeypatch.setattr(settings, "min_support", 1)
    job_id = setup_job(db_path)
    s1, _, _ = add_pair_with_statement(db_path, job_id, "s1")
    s2, _, _ = add_pair_with_statement(db_path, job_id, "s2")
    t1 = make_model_thread(db_path, job_id, "First", [s1])
    conn = connect(db_path)
    run_id = conn.execute("SELECT run_id FROM thread WHERE id = ?", (t1,)).fetchone()["run_id"]
    conn.close()
    t2 = make_model_thread(db_path, job_id, "Second", [s2], run_id=run_id)

    client.get(f"/api/jobs/{job_id}/primary-secondary")  # triggers the implicit first-time suggest
    resp = client.post(f"/api/jobs/{job_id}/primary-secondary/choose", json={"thread_id": t2, "role": "secondary"})
    assert resp.json()["secondary"]["thread"]["id"] == t2

    reloaded = client.get(f"/api/jobs/{job_id}/primary-secondary").json()
    assert reloaded["secondary"]["thread"]["id"] == t2  # persisted, not recomputed away

    swapped = client.post(f"/api/jobs/{job_id}/primary-secondary/swap").json()
    assert swapped["primary"]["thread"]["id"] == t2
    reloaded2 = client.get(f"/api/jobs/{job_id}/primary-secondary").json()
    assert reloaded2["primary"]["thread"]["id"] == t2


def test_reranking_on_get_leaves_an_existing_choice_alone(client, db_path, monkeypatch):
    monkeypatch.setattr(settings, "min_support", 1)
    job_id = setup_job(db_path)
    s1, u1a, u1b = add_pair_with_statement(db_path, job_id, "s1")
    s2, u2a, u2b = add_pair_with_statement(db_path, job_id, "s2")
    add_requirement_judgment(db_path, job_id, u2a, "high", "match")  # makes thread 2 score higher
    t1 = make_model_thread(db_path, job_id, "Low score", [s1])
    conn = connect(db_path)
    run_id = conn.execute("SELECT run_id FROM thread WHERE id = ?", (t1,)).fetchone()["run_id"]
    conn.close()
    make_model_thread(db_path, job_id, "High score", [s2], run_id=run_id)

    # First load auto-suggests -- picks the higher scorer as primary.
    first = client.get(f"/api/jobs/{job_id}/primary-secondary").json()
    assert first["primary"]["thread"]["idea"] == "High score"

    # User deliberately picks the lower scorer anyway.
    client.post(f"/api/jobs/{job_id}/primary-secondary/choose", json={"thread_id": t1, "role": "primary"})

    # A plain GET (which recomputes the ranking internally) must not
    # overwrite that choice.
    again = client.get(f"/api/jobs/{job_id}/primary-secondary").json()
    assert again["primary"]["thread"]["id"] == t1


def test_suggest_again_resets_an_existing_choice(client, db_path, monkeypatch):
    monkeypatch.setattr(settings, "min_support", 1)
    job_id = setup_job(db_path)
    s1, u1a, u1b = add_pair_with_statement(db_path, job_id, "s1")
    s2, u2a, u2b = add_pair_with_statement(db_path, job_id, "s2")
    add_requirement_judgment(db_path, job_id, u2a, "high", "match")
    t1 = make_model_thread(db_path, job_id, "Low score", [s1])
    conn = connect(db_path)
    run_id = conn.execute("SELECT run_id FROM thread WHERE id = ?", (t1,)).fetchone()["run_id"]
    conn.close()
    t2 = make_model_thread(db_path, job_id, "High score", [s2], run_id=run_id)

    client.post(f"/api/jobs/{job_id}/primary-secondary/choose", json={"thread_id": t1, "role": "primary"})
    resp = client.post(f"/api/jobs/{job_id}/primary-secondary/suggest").json()
    assert resp["primary"]["thread"]["id"] == t2  # reset to the actual top candidate


def test_deleting_the_chosen_thread_flags_it_stale(client, db_path, monkeypatch):
    monkeypatch.setattr(settings, "min_support", 1)
    job_id = setup_job(db_path)
    s1, _, _ = add_pair_with_statement(db_path, job_id, "s1")
    t1 = make_model_thread(db_path, job_id, "Chosen", [s1])
    client.post(f"/api/jobs/{job_id}/primary-secondary/choose", json={"thread_id": t1, "role": "primary"})

    client.delete(f"/api/threads/{t1}")

    resp = client.get(f"/api/jobs/{job_id}/primary-secondary").json()
    assert resp["primary"]["choice_stale"] is True


def test_editing_a_statement_in_the_chosen_thread_flags_it_stale(client, db_path, monkeypatch):
    monkeypatch.setattr(settings, "min_support", 1)
    job_id = setup_job(db_path)
    s1, _, _ = add_pair_with_statement(db_path, job_id, "s1")
    t1 = make_model_thread(db_path, job_id, "Chosen", [s1])
    client.post(f"/api/jobs/{job_id}/primary-secondary/choose", json={"thread_id": t1, "role": "primary"})

    assert client.get(f"/api/jobs/{job_id}/primary-secondary").json()["primary"]["choice_stale"] is False
    client.patch(f"/api/statements/{s1}", json={"status": "written", "text": "edited"})
    assert client.get(f"/api/jobs/{job_id}/primary-secondary").json()["primary"]["choice_stale"] is True


def test_manual_thread_creation_is_usable_as_primary(client, db_path):
    job_id = setup_job(db_path)
    s1, _, _ = add_pair_with_statement(db_path, job_id, "s1")

    resp = client.post(f"/api/jobs/{job_id}/threads/manual", json={"idea": "Hand-written", "statement_ids": [s1]})
    assert resp.status_code == 201
    thread_id = resp.json()["id"]
    assert resp.json()["source"] == "user"

    chosen = client.post(
        f"/api/jobs/{job_id}/primary-secondary/choose", json={"thread_id": thread_id, "role": "primary"}
    ).json()
    assert chosen["primary"]["thread"]["id"] == thread_id
    assert chosen["primary"]["thread"]["exempt_from_min_support"] is True


def test_clear_secondary(client, db_path, monkeypatch):
    monkeypatch.setattr(settings, "min_support", 1)
    job_id = setup_job(db_path)
    s1, _, _ = add_pair_with_statement(db_path, job_id, "s1")
    s2, _, _ = add_pair_with_statement(db_path, job_id, "s2")
    t1 = make_model_thread(db_path, job_id, "A", [s1])
    conn = connect(db_path)
    run_id = conn.execute("SELECT run_id FROM thread WHERE id = ?", (t1,)).fetchone()["run_id"]
    conn.close()
    t2 = make_model_thread(db_path, job_id, "B", [s2], run_id=run_id)
    client.post(f"/api/jobs/{job_id}/primary-secondary/choose", json={"thread_id": t2, "role": "secondary"})

    resp = client.delete(f"/api/jobs/{job_id}/primary-secondary/secondary").json()
    assert resp["secondary"]["thread"] is None
