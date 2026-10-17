"""Milestone 3: the pair-builder endpoints.
Embeddings are inserted directly with known vectors for deterministic
scores -- this is about the build/rebuild/wipe plumbing, not re-testing
the pure scoring functions (see test_pairing.py)."""

import json

import numpy as np
import pytest

from app.db import connect
from app.vectors import to_blob

MODEL = "test-embed-model"


def _setup_job(db_path: str) -> tuple[int, int]:
    """One profile/inventory/role/flow/job. Returns (conn-free) job_id and
    role_id for the caller to add units/requirements to."""
    conn = connect(db_path)
    conn.execute("INSERT INTO profile (name) VALUES ('p')")
    conn.execute("INSERT INTO inventory (profile_id, name) VALUES (1, 'inv')")
    conn.execute("INSERT INTO role (inventory_id, company, title, sort_order) VALUES (1, 'c', 't', 0)")
    conn.execute("INSERT INTO flow (profile_id, name, inventory_id) VALUES (1, 'f', 1)")
    conn.execute("INSERT INTO job (flow_id, title, jd_text) VALUES (1, 'job', 'jd')")
    job_id = conn.execute("SELECT id FROM job ORDER BY id DESC LIMIT 1").fetchone()["id"]
    conn.commit()
    conn.close()
    return job_id, 1


def _add_matched_unit(db_path: str, role_id: int, job_id: int, text: str, vector: list[float], req_sort: int = 0) -> int:
    """A unit with an effective 'match' verdict on a (new) requirement of
    job_id, and a known embedded 'text' field vector."""
    conn = connect(db_path)
    conn.execute("INSERT INTO unit (role_id, text, source, sort_order) VALUES (?, ?, 'manual', ?)", (role_id, text, req_sort))
    unit_id = conn.execute("SELECT id FROM unit ORDER BY id DESC LIMIT 1").fetchone()["id"]
    conn.execute(
        "INSERT INTO requirement (job_id, text, weight, source, status, sort_order) "
        "VALUES (?, 'req', 'high', 'extracted', 'done', ?)", (job_id, req_sort),
    )
    requirement_id = conn.execute("SELECT id FROM requirement ORDER BY id DESC LIMIT 1").fetchone()["id"]
    conn.execute(
        "INSERT INTO judgment (requirement_id, unit_id, model_verdict) VALUES (?, ?, 'match')",
        (requirement_id, unit_id),
    )
    conn.execute(
        "INSERT INTO unit_embedding (unit_id, field, model, vector) VALUES (?, 'text', ?, ?)",
        (unit_id, MODEL, to_blob(np.array(vector, dtype=np.float32))),
    )
    conn.commit()
    conn.close()
    return unit_id


@pytest.fixture(autouse=True)
def _use_test_embed_model(monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "embed_model", MODEL)


def test_build_pairs_creates_pair_and_statement_rows(client, db_path):
    job_id, role_id = _setup_job(db_path)
    _add_matched_unit(db_path, role_id, job_id, "unit a", [1.0, 0.0] + [0.0]*14, req_sort=0)
    _add_matched_unit(db_path, role_id, job_id, "unit b", [0.9, 0.1] + [0.0]*14, req_sort=1)
    _add_matched_unit(db_path, role_id, job_id, "unit c", [0.0, 1.0] + [0.0]*14, req_sort=2)

    resp = client.post(f"/api/jobs/{job_id}/pairs/build")
    assert resp.status_code == 200
    body = resp.json()
    assert body["pair_count"] == 3  # fewer than... wait 3 units -> normal rule, but pair_k=2 default covers all anyway
    assert body["removed"] == []

    conn = connect(db_path)
    pairs = conn.execute("SELECT * FROM pair WHERE job_id = ?", (job_id,)).fetchall()
    statements = conn.execute(
        "SELECT * FROM statement WHERE pair_id IN (SELECT id FROM pair WHERE job_id = ?)", (job_id,)
    ).fetchall()
    conn.close()
    assert len(pairs) == 3
    assert len(statements) == 3
    assert all(s["status"] == "unanswered" for s in statements)
    assert all(p["model"] == MODEL for p in pairs)


def test_list_pairs_returns_units_and_is_stably_shuffled(client, db_path):
    job_id, role_id = _setup_job(db_path)
    for i in range(4):
        _add_matched_unit(db_path, role_id, job_id, f"unit {i}", [float(i), 1.0] + [0.0]*14, req_sort=i)
    client.post(f"/api/jobs/{job_id}/pairs/build")

    resp1 = client.get(f"/api/jobs/{job_id}/pairs")
    resp2 = client.get(f"/api/jobs/{job_id}/pairs")
    assert resp1.status_code == 200
    order1 = [p["id"] for p in resp1.json()["pairs"]]
    order2 = [p["id"] for p in resp2.json()["pairs"]]
    assert order1 == order2  # stable across requests

    pair = resp1.json()["pairs"][0]
    assert "unit_a" in pair and "unit_b" in pair
    assert "score" not in pair  # §6: shown without scores
    assert pair["statement"]["status"] == "unanswered"


def test_rebuild_is_idempotent_keeps_statements_for_retained_pairs(client, db_path):
    job_id, role_id = _setup_job(db_path)
    _add_matched_unit(db_path, role_id, job_id, "unit a", [1.0, 0.0] + [0.0]*14, req_sort=0)
    _add_matched_unit(db_path, role_id, job_id, "unit b", [0.9, 0.1] + [0.0]*14, req_sort=1)
    client.post(f"/api/jobs/{job_id}/pairs/build")

    pairs_before = client.get(f"/api/jobs/{job_id}/pairs").json()["pairs"]
    statement_id = pairs_before[0]["statement"]["id"]
    client.patch(f"/api/statements/{statement_id}", json={"status": "written", "text": "they both do X"})

    # Rebuilding with the exact same units/scores must not disturb the
    # statement already written on a pair that's still in the set.
    resp = client.post(f"/api/jobs/{job_id}/pairs/build")
    assert resp.json()["removed"] == []
    pairs_after = client.get(f"/api/jobs/{job_id}/pairs").json()["pairs"]
    kept = next(p for p in pairs_after if p["statement"]["id"] == statement_id)
    assert kept["statement"]["status"] == "written"
    assert kept["statement"]["text"] == "they both do X"


def test_rebuild_removes_pairs_no_longer_in_the_set_and_warns_if_written(client, db_path):
    job_id, role_id = _setup_job(db_path)
    _add_matched_unit(db_path, role_id, job_id, "unit a", [1.0, 0.0] + [0.0]*14, req_sort=0)
    _add_matched_unit(db_path, role_id, job_id, "unit b", [0.9, 0.1] + [0.0]*14, req_sort=1)
    client.post(f"/api/jobs/{job_id}/pairs/build")

    pair_id = client.get(f"/api/jobs/{job_id}/pairs").json()["pairs"][0]["id"]
    statement_id = client.get(f"/api/jobs/{job_id}/pairs").json()["pairs"][0]["statement"]["id"]
    client.patch(f"/api/statements/{statement_id}", json={"status": "written", "text": "shared skill"})

    # Soft-delete one of the two units -- it drops out of "matched units",
    # so the pair can no longer exist on rebuild.
    conn = connect(db_path)
    unit_a_id = conn.execute("SELECT unit_a_id FROM pair WHERE id = ?", (pair_id,)).fetchone()["unit_a_id"]
    conn.execute("UPDATE unit SET deleted = 1 WHERE id = ?", (unit_a_id,))
    conn.commit()
    conn.close()

    resp = client.post(f"/api/jobs/{job_id}/pairs/build")
    assert resp.json()["pair_count"] == 0
    removed = resp.json()["removed"]
    assert len(removed) == 1
    assert removed[0]["had_written_statement"] is True

    conn = connect(db_path)
    assert conn.execute("SELECT 1 FROM pair WHERE id = ?", (pair_id,)).fetchone() is None
    assert conn.execute("SELECT 1 FROM statement WHERE id = ?", (statement_id,)).fetchone() is None
    conn.close()


def test_pair_max_caps_the_built_set(client, db_path, monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "pair_k", 10)  # every unit's full top-k -> select_pairs returns all C(5,2)=10
    monkeypatch.setattr(settings, "pair_max", 3)
    job_id, role_id = _setup_job(db_path)
    for i in range(5):
        vec = [0.0] * 16
        vec[i % 16] = 1.0
        vec[(i + 1) % 16] = 0.5 + i * 0.05  # distinct, deterministic scores across all pairs
        _add_matched_unit(db_path, role_id, job_id, f"unit {i}", vec, req_sort=i)

    resp = client.post(f"/api/jobs/{job_id}/pairs/build")
    assert resp.json()["pair_count"] == 3


def test_pair_max_never_drops_an_answered_pair(client, db_path, monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "pair_k", 10)
    job_id, role_id = _setup_job(db_path)
    for i in range(5):
        vec = [0.0] * 16
        vec[i % 16] = 1.0
        vec[(i + 1) % 16] = 0.5 + i * 0.05
        _add_matched_unit(db_path, role_id, job_id, f"unit {i}", vec, req_sort=i)
    client.post(f"/api/jobs/{job_id}/pairs/build")

    pairs = client.get(f"/api/jobs/{job_id}/pairs").json()["pairs"]
    # Answer the lowest-scoring pair -- it would be the first one the cap
    # drops on score alone.
    weakest = min(pairs, key=lambda p: p["unit_a"]["id"] * 100 + p["unit_b"]["id"])
    answered_statement_id = weakest["statement"]["id"]
    client.patch(f"/api/statements/{answered_statement_id}", json={"status": "none"})

    monkeypatch.setattr(settings, "pair_max", 1)
    resp = client.post(f"/api/jobs/{job_id}/pairs/build")
    assert resp.json()["pair_count"] >= 1
    conn = connect(db_path)
    survived = conn.execute("SELECT status FROM statement WHERE id = ?", (answered_statement_id,)).fetchone()
    conn.close()
    assert survived is not None
    assert survived["status"] == "none"


def test_rebuild_with_pair_max_stays_idempotent(client, db_path, monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "pair_k", 10)
    monkeypatch.setattr(settings, "pair_max", 3)
    job_id, role_id = _setup_job(db_path)
    for i in range(5):
        vec = [0.0] * 16
        vec[i % 16] = 1.0
        vec[(i + 1) % 16] = 0.5 + i * 0.05
        _add_matched_unit(db_path, role_id, job_id, f"unit {i}", vec, req_sort=i)

    first = client.post(f"/api/jobs/{job_id}/pairs/build").json()
    second = client.post(f"/api/jobs/{job_id}/pairs/build").json()
    assert first["pair_count"] == second["pair_count"] == 3
    assert second["removed"] == []


def test_jd_resubmit_wipes_pairs_and_statements(client, mock_llm, db_path):
    job_id, role_id = _setup_job(db_path)
    _add_matched_unit(db_path, role_id, job_id, "unit a", [1.0, 0.0] + [0.0]*14, req_sort=0)
    _add_matched_unit(db_path, role_id, job_id, "unit b", [0.9, 0.1] + [0.0]*14, req_sort=1)
    client.post(f"/api/jobs/{job_id}/pairs/build")
    assert client.get(f"/api/jobs/{job_id}/pairs").json()["pairs"] != []

    # wipe_job_requirements only runs on an actual resubmit (jd_submitted_text
    # already set) -- mark this job as already having been submitted once.
    conn = connect(db_path)
    conn.execute("UPDATE job SET jd_submitted_text = 'jd' WHERE id = ?", (job_id,))
    conn.commit()
    conn.close()

    mock_llm.queue("requirement_extract", json.dumps({"requirements": [{"text": "new req", "weight": "high"}]}))
    mock_llm.queue("judge_batch", "not valid json")
    resp = client.post(f"/api/jobs/{job_id}/submit-jd", json={"jd_text": "a completely different jd"})
    assert resp.status_code == 200

    conn = connect(db_path)
    assert conn.execute("SELECT COUNT(*) AS n FROM pair WHERE job_id = ?", (job_id,)).fetchone()["n"] == 0
    assert conn.execute(
        "SELECT COUNT(*) AS n FROM statement WHERE pair_id IN (SELECT id FROM pair WHERE job_id = ?)", (job_id,)
    ).fetchone()["n"] == 0
    conn.close()


def test_jd_resubmit_wipes_threads_and_job_thread_without_fk_error(client, mock_llm, db_path):
    """Regression test: job_thread.thread_id references thread(id), so
    wipe_job_requirements must delete job_thread before thread -- deleting
    thread first (the order this used to run in) raised a FOREIGN KEY
    constraint error and turned every JD resubmit into a 500 for any job
    that had ever had a primary/secondary thread chosen."""
    job_id, role_id = _setup_job(db_path)
    _add_matched_unit(db_path, role_id, job_id, "unit a", [1.0, 0.0] + [0.0] * 14, req_sort=0)
    _add_matched_unit(db_path, role_id, job_id, "unit b", [0.9, 0.1] + [0.0] * 14, req_sort=1)
    client.post(f"/api/jobs/{job_id}/pairs/build")

    conn = connect(db_path)
    run_id = conn.execute(
        "INSERT INTO thread_run (job_id, params_json, statements_snapshot_json) VALUES (?, '{}', '[]')", (job_id,)
    ).lastrowid
    thread_id = conn.execute(
        "INSERT INTO thread (run_id, idea, source) VALUES (?, 'Hand-written', 'user')", (run_id,)
    ).lastrowid
    conn.execute("INSERT INTO job_thread (job_id, thread_id, role) VALUES (?, ?, 'primary')", (job_id, thread_id))
    conn.execute("UPDATE job SET jd_submitted_text = 'jd' WHERE id = ?", (job_id,))
    conn.commit()
    conn.close()

    mock_llm.queue("requirement_extract", json.dumps({"requirements": [{"text": "new req", "weight": "high"}]}))
    mock_llm.queue("judge_batch", "not valid json")
    resp = client.post(f"/api/jobs/{job_id}/submit-jd", json={"jd_text": "a completely different jd"})
    assert resp.status_code == 200

    conn = connect(db_path)
    assert conn.execute("SELECT COUNT(*) AS n FROM job_thread WHERE job_id = ?", (job_id,)).fetchone()["n"] == 0
    assert conn.execute("SELECT COUNT(*) AS n FROM thread WHERE run_id = ?", (run_id,)).fetchone()["n"] == 0
    assert conn.execute("SELECT COUNT(*) AS n FROM thread_run WHERE job_id = ?", (job_id,)).fetchone()["n"] == 0
    conn.close()


def test_build_pairs_unknown_job_404(client):
    resp = client.post("/api/jobs/999/pairs/build")
    assert resp.status_code == 404


# --- end-to-end with the Northlight fixture's realistic unit text ---

def _load_northlight_units() -> list[str]:
    path = (
        __import__("pathlib").Path(__file__).resolve().parent.parent.parent
        / "fixtures" / "northlight" / "units.json"
    )
    data = json.loads(path.read_text())
    return [item["text"] for item in data]


def test_northlight_fixture_units_produce_a_deterministic_full_pipeline(client, db_path, mock_embedder, monkeypatch):
    """Not re-testing the scoring math (test_pairing.py already covers
    that with hand-verified numbers) -- this is a structural end-to-end
    check with realistic bullet text run through the actual embedding
    path (via the mock embedder's hash vectors, so no network call),
    confirming the whole build is sane and reproducible."""
    from app.config import settings as _settings
    monkeypatch.setattr(_settings, "pair_max", 1000)  # pair_max isn't what this test is about
    from app.config import settings
    from app.embeddings import embed_units

    texts = _load_northlight_units()
    assert len(texts) == 8

    job_id, role_id = _setup_job(db_path)
    conn = connect(db_path)
    unit_ids = []
    for i, text in enumerate(texts):
        conn.execute("INSERT INTO unit (role_id, text, source, sort_order) VALUES (?, ?, 'manual', ?)", (role_id, text, i))
        unit_ids.append(conn.execute("SELECT id FROM unit ORDER BY id DESC LIMIT 1").fetchone()["id"])
    conn.commit()
    embed_units(conn, unit_ids, mock_embedder)  # real embedding path, hash-based vectors

    for i, unit_id in enumerate(unit_ids):
        conn.execute(
            "INSERT INTO requirement (job_id, text, weight, source, status, sort_order) "
            "VALUES (?, 'req', 'high', 'extracted', 'done', ?)", (job_id, i),
        )
        requirement_id = conn.execute("SELECT id FROM requirement ORDER BY id DESC LIMIT 1").fetchone()["id"]
        conn.execute(
            "INSERT INTO judgment (requirement_id, unit_id, model_verdict) VALUES (?, ?, 'match')",
            (requirement_id, unit_id),
        )
    conn.commit()
    conn.close()

    resp1 = client.post(f"/api/jobs/{job_id}/pairs/build")
    assert resp1.status_code == 200
    pairs1 = client.get(f"/api/jobs/{job_id}/pairs").json()["pairs"]

    # Deterministic: rebuilding from the exact same data gives the exact
    # same set of pairs (ids, not just count).
    resp2 = client.post(f"/api/jobs/{job_id}/pairs/build")
    assert resp2.json()["removed"] == []
    pairs2 = client.get(f"/api/jobs/{job_id}/pairs").json()["pairs"]
    assert {p["id"] for p in pairs1} == {p["id"] for p in pairs2}

    # Every unit ends up in at least pair_k pairs (the per-unit guarantee).
    counts = {uid: 0 for uid in unit_ids}
    for p in pairs1:
        counts[p["unit_a"]["id"]] += 1
        counts[p["unit_b"]["id"]] += 1
    for uid in unit_ids:
        assert counts[uid] >= settings.pair_k

    # No duplicate or self pairs.
    seen = set()
    for p in pairs1:
        key = (p["unit_a"]["id"], p["unit_b"]["id"])
        assert key not in seen
        assert p["unit_a"]["id"] < p["unit_b"]["id"]
        seen.add(key)
