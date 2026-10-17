from app.db import connect


def setup_requirement_and_judgment(db_path):
    conn = connect(db_path)
    conn.execute("INSERT INTO profile (name) VALUES ('p')")
    conn.execute("INSERT INTO inventory (profile_id, name) VALUES (1, 'inv')")
    conn.execute("INSERT INTO role (inventory_id, company, title, sort_order) VALUES (1, 'c', 't', 0)")
    conn.execute("INSERT INTO unit (role_id, text, source, sort_order) VALUES (1, 'x', 'manual', 0)")
    conn.execute("INSERT INTO flow (profile_id, name, inventory_id) VALUES (1, 'f', 1)")
    conn.execute("INSERT INTO job (flow_id, title, jd_text) VALUES (1, 't', 'jd')")
    conn.execute(
        "INSERT INTO requirement (job_id, text, weight, source, status, sort_order) "
        "VALUES (1, 'req', 'high', 'extracted', 'done', 0)"
    )
    conn.execute(
        "INSERT INTO judgment (requirement_id, unit_id, model_verdict) VALUES (1, 1, 'weak')"
    )
    conn.commit()
    judgment_id = conn.execute("SELECT id FROM judgment").fetchone()["id"]
    conn.close()
    return judgment_id


def test_patch_judgment_sets_user_verdict(client, db_path):
    judgment_id = setup_requirement_and_judgment(db_path)

    resp = client.patch(f"/api/judgments/{judgment_id}", json={"user_verdict": "match"})

    assert resp.status_code == 200
    body = resp.json()
    assert body["judgment"]["user_verdict"] == "match"
    assert body["judgment"]["model_verdict"] == "weak"  # never overwritten
    # The backend hands back the derived requirement verdict too -- the
    # frontend must never compute match/weak/gap itself.
    assert body["requirement_verdict"] == "match"


def test_patch_judgment_unknown_returns_404(client):
    resp = client.patch("/api/judgments/999", json={"user_verdict": "match"})
    assert resp.status_code == 404


def test_patch_judgment_invalid_verdict_returns_422_not_500(client, db_path):
    judgment_id = setup_requirement_and_judgment(db_path)
    resp = client.patch(f"/api/judgments/{judgment_id}", json={"user_verdict": "sort-of"})
    assert resp.status_code == 422


def test_patch_judgment_can_clear_user_verdict(client, db_path):
    judgment_id = setup_requirement_and_judgment(db_path)
    client.patch(f"/api/judgments/{judgment_id}", json={"user_verdict": "match"})

    resp = client.patch(f"/api/judgments/{judgment_id}", json={"user_verdict": None})

    assert resp.status_code == 200
    assert resp.json()["judgment"]["user_verdict"] is None
    assert resp.json()["requirement_verdict"] == "weak"  # falls back to model_verdict
