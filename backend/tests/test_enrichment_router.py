"""Milestone 2: the enrichment screen's listing
endpoint and the unit-patch skip-flag behavior it relies on. Rows are
inserted directly via SQL -- this endpoint only reads already-judged data,
there's nothing here that needs the real extraction/judging pipeline."""

import sqlite3

from app.db import connect


def _setup(db_path: str) -> tuple[sqlite3.Connection, int, int]:
    """One profile/inventory/role/flow/job, nothing else yet. Returns
    (conn, job_id, role_id) with the connection left open for the caller
    to add units/requirements/judgments."""
    conn = connect(db_path)
    conn.execute("INSERT INTO profile (name) VALUES ('p')")
    conn.execute("INSERT INTO inventory (profile_id, name) VALUES (1, 'inv')")
    conn.execute("INSERT INTO role (inventory_id, company, title, sort_order) VALUES (1, 'c', 't', 0)")
    conn.execute("INSERT INTO flow (profile_id, name, inventory_id) VALUES (1, 'f', 1)")
    conn.execute("INSERT INTO job (flow_id, title, jd_text) VALUES (1, 'job', 'jd')")
    job_id = conn.execute("SELECT id FROM job ORDER BY id DESC LIMIT 1").fetchone()["id"]
    conn.commit()
    return conn, job_id, 1


def _add_unit(conn: sqlite3.Connection, role_id: int, text: str, sort_order: int = 0) -> int:
    conn.execute(
        "INSERT INTO unit (role_id, text, source, sort_order) VALUES (?, ?, 'manual', ?)",
        (role_id, text, sort_order),
    )
    conn.commit()
    return conn.execute("SELECT id FROM unit ORDER BY id DESC LIMIT 1").fetchone()["id"]


def _add_requirement(conn: sqlite3.Connection, job_id: int, text: str, weight: str = "high", sort_order: int = 0) -> int:
    conn.execute(
        "INSERT INTO requirement (job_id, text, weight, source, status, sort_order) "
        "VALUES (?, ?, ?, 'extracted', 'done', ?)",
        (job_id, text, weight, sort_order),
    )
    conn.commit()
    return conn.execute("SELECT id FROM requirement ORDER BY id DESC LIMIT 1").fetchone()["id"]


def _add_judgment(
    conn: sqlite3.Connection, requirement_id: int, unit_id: int,
    model_verdict: str | None = None, user_verdict: str | None = None,
) -> None:
    conn.execute(
        "INSERT INTO judgment (requirement_id, unit_id, model_verdict, user_verdict) VALUES (?, ?, ?, ?)",
        (requirement_id, unit_id, model_verdict, user_verdict),
    )
    conn.commit()


def test_lists_only_units_with_an_effective_match_verdict(client, db_path):
    conn, job_id, role_id = _setup(db_path)
    req_id = _add_requirement(conn, job_id, "Req A")
    matched_unit = _add_unit(conn, role_id, "matched bullet")
    weak_unit = _add_unit(conn, role_id, "weak bullet", sort_order=1)
    none_unit = _add_unit(conn, role_id, "none bullet", sort_order=2)
    overridden_unit = _add_unit(conn, role_id, "user-overridden bullet", sort_order=3)
    _add_judgment(conn, req_id, matched_unit, model_verdict="match")
    _add_judgment(conn, req_id, weak_unit, model_verdict="weak")
    _add_judgment(conn, req_id, none_unit, model_verdict="none")
    # Effective verdict is user_verdict ?? model_verdict -- a user override
    # to 'match' over a model 'weak' must list the unit; model_verdict
    # itself is never touched.
    _add_judgment(conn, req_id, overridden_unit, model_verdict="weak", user_verdict="match")
    conn.close()

    resp = client.get(f"/api/jobs/{job_id}/enrichment")
    assert resp.status_code == 200
    body = resp.json()
    listed_ids = {u["unit"]["id"] for u in body["units"]}
    assert listed_ids == {matched_unit, overridden_unit}
    assert body["total_count"] == 2


def test_lists_a_unit_once_even_if_it_matches_several_requirements_and_shows_which(client, db_path):
    conn, job_id, role_id = _setup(db_path)
    req_a = _add_requirement(conn, job_id, "Req A", sort_order=0)
    req_b = _add_requirement(conn, job_id, "Req B", sort_order=1)
    unit_id = _add_unit(conn, role_id, "versatile bullet")
    _add_judgment(conn, req_a, unit_id, model_verdict="match")
    _add_judgment(conn, req_b, unit_id, model_verdict="match")
    conn.close()

    resp = client.get(f"/api/jobs/{job_id}/enrichment")
    body = resp.json()
    assert len(body["units"]) == 1
    matched = body["units"][0]["matched_requirements"]
    assert {r["id"] for r in matched} == {req_a, req_b}


def test_unit_from_a_different_job_is_not_listed(client, db_path):
    conn, job_id, role_id = _setup(db_path)
    conn.execute("INSERT INTO job (flow_id, title, jd_text) VALUES (1, 'other job', 'jd')")
    other_job_id = conn.execute("SELECT id FROM job ORDER BY id DESC LIMIT 1").fetchone()["id"]
    conn.commit()
    other_req = _add_requirement(conn, other_job_id, "Other req")
    unit_id = _add_unit(conn, role_id, "bullet for the other job")
    _add_judgment(conn, other_req, unit_id, model_verdict="match")
    conn.close()

    resp = client.get(f"/api/jobs/{job_id}/enrichment")
    assert resp.json()["units"] == []


# --- completeness: filled vs skipped vs empty ---

def test_unit_complete_only_when_every_field_filled_or_skipped(client, db_path):
    conn, job_id, role_id = _setup(db_path)
    req_id = _add_requirement(conn, job_id, "Req A")
    unit_id = _add_unit(conn, role_id, "bullet")
    _add_judgment(conn, req_id, unit_id, model_verdict="match")
    conn.close()

    # Nothing filled, nothing skipped -- incomplete.
    assert client.get(f"/api/jobs/{job_id}/enrichment").json()["units"][0]["complete"] is False

    client.patch(f"/api/units/{unit_id}", json={"context": "the situation"})
    body = client.get(f"/api/jobs/{job_id}/enrichment").json()
    assert body["units"][0]["complete"] is False  # contribution/outcome still missing
    assert body["enriched_count"] == 0

    client.patch(f"/api/units/{unit_id}", json={"contribution_skipped": True, "outcome_skipped": True})
    body = client.get(f"/api/jobs/{job_id}/enrichment").json()
    assert body["units"][0]["complete"] is True  # filled + skipped + skipped
    assert body["enriched_count"] == 1
    assert body["total_count"] == 1


def test_previously_enriched_unit_from_an_earlier_job_is_prefilled_and_counts_as_done(client, db_path):
    conn, job_id, role_id = _setup(db_path)
    req_id = _add_requirement(conn, job_id, "Req A")
    # Already enriched -- as if filled in while working on a previous job,
    # since context/contribution/outcome live on the unit, not per-job.
    conn.execute(
        "INSERT INTO unit (role_id, text, source, sort_order, context, contribution, outcome) "
        "VALUES (?, 'already enriched bullet', 'manual', 0, 'sit', 'contrib', 'result')",
        (role_id,),
    )
    conn.commit()
    unit_id = conn.execute("SELECT id FROM unit ORDER BY id DESC LIMIT 1").fetchone()["id"]
    _add_judgment(conn, req_id, unit_id, model_verdict="match")
    conn.close()

    body = client.get(f"/api/jobs/{job_id}/enrichment").json()
    assert body["units"][0]["complete"] is True
    assert body["units"][0]["unit"]["context"] == "sit"
    assert body["enriched_count"] == 1


def test_questions_come_from_settings(client, db_path):
    conn, job_id, role_id = _setup(db_path)
    conn.close()
    body = client.get(f"/api/jobs/{job_id}/enrichment").json()
    assert "Situation" in body["questions"]["context"]
    assert "Contribution" in body["questions"]["contribution"]
    assert "Result" in body["questions"]["outcome"]


def test_unknown_job_returns_404(client):
    resp = client.get("/api/jobs/999/enrichment")
    assert resp.status_code == 404


# --- saving re-embeds only the changed field ---

def test_saving_one_field_reembeds_only_that_field(client, mock_embedder, db_path):
    conn, job_id, role_id = _setup(db_path)
    req_id = _add_requirement(conn, job_id, "Req A")
    unit_id = _add_unit(conn, role_id, "bullet")
    _add_judgment(conn, req_id, unit_id, model_verdict="match")
    conn.close()

    mock_embedder.set_vector("search_document: first context", [1.0] + [0.0] * 15)
    client.patch(f"/api/units/{unit_id}", json={"context": "first context"})

    conn = connect(db_path)
    context_vector_before = conn.execute(
        "SELECT vector FROM unit_embedding WHERE unit_id = ? AND field = 'context'", (unit_id,)
    ).fetchone()["vector"]
    assert conn.execute(
        "SELECT 1 FROM unit_embedding WHERE unit_id = ? AND field = 'contribution'", (unit_id,)
    ).fetchone() is None
    conn.close()

    mock_embedder.set_vector("search_document: contribution text", [0.0, 1.0] + [0.0] * 14)
    client.patch(f"/api/units/{unit_id}", json={"contribution": "contribution text"})

    conn = connect(db_path)
    context_vector_after = conn.execute(
        "SELECT vector FROM unit_embedding WHERE unit_id = ? AND field = 'context'", (unit_id,)
    ).fetchone()["vector"]
    contribution_row = conn.execute(
        "SELECT 1 FROM unit_embedding WHERE unit_id = ? AND field = 'contribution'", (unit_id,)
    ).fetchone()
    conn.close()

    assert context_vector_after == context_vector_before  # untouched by the second save
    assert contribution_row is not None  # the changed field got embedded


def test_skip_flag_alone_does_not_trigger_an_embed(client, db_path):
    conn, job_id, role_id = _setup(db_path)
    req_id = _add_requirement(conn, job_id, "Req A")
    unit_id = _add_unit(conn, role_id, "bullet")
    _add_judgment(conn, req_id, unit_id, model_verdict="match")
    conn.close()

    client.patch(f"/api/units/{unit_id}", json={"outcome_skipped": True})

    conn = connect(db_path)
    row = conn.execute("SELECT 1 FROM unit_embedding WHERE unit_id = ?", (unit_id,)).fetchone()
    conn.close()
    assert row is None


def test_patch_unit_returns_skip_flags(client, db_path):
    conn, job_id, role_id = _setup(db_path)
    unit_id = _add_unit(conn, role_id, "bullet")
    conn.close()

    resp = client.patch(f"/api/units/{unit_id}", json={"context_skipped": True})
    assert resp.status_code == 200
    body = resp.json()
    assert body["context_skipped"] is True
    assert body["contribution_skipped"] is False
    assert body["outcome_skipped"] is False
