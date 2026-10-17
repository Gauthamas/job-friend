"""Reversible "discard" for inventory roles/units and for jobs (shown on
the Flows screen). Distinct from unit.deleted, which has no restore path.
Discarding never deletes anything; restoring brings it straight back."""

import json

from app.db import connect
from app.shortlist import shortlist_units
from tests.test_units_router import commit_two_units_same_role, make_committed_unit


def test_discarded_unit_is_not_shortlisted_restore_brings_it_back(client, mock_llm, mock_embedder, db_path):
    inventory_id, unit_id = make_committed_unit(client, mock_llm, text="a shortlistable unit")

    conn = connect(db_path)
    candidates_before = shortlist_units(conn, inventory_id, "requirement text", mock_embedder, top_k=5)
    assert unit_id in [c.unit_id for c in candidates_before]
    conn.close()

    resp = client.post(f"/api/units/{unit_id}/discard")
    assert resp.status_code == 200
    assert resp.json()["discarded_at"] is not None

    conn = connect(db_path)
    candidates_discarded = shortlist_units(conn, inventory_id, "requirement text", mock_embedder, top_k=5)
    conn.close()
    assert unit_id not in [c.unit_id for c in candidates_discarded]

    resp = client.post(f"/api/units/{unit_id}/restore")
    assert resp.status_code == 200
    assert resp.json()["discarded_at"] is None

    conn = connect(db_path)
    candidates_restored = shortlist_units(conn, inventory_id, "requirement text", mock_embedder, top_k=5)
    conn.close()
    assert unit_id in [c.unit_id for c in candidates_restored]


def test_discard_unit_404_for_unknown_unit(client):
    assert client.post("/api/units/999/discard").status_code == 404
    assert client.post("/api/units/999/restore").status_code == 404


def test_discard_role_cascades_to_its_units_restore_cascades_back(client, mock_llm):
    inventory_id, unit_a, unit_b = commit_two_units_same_role(client, mock_llm)
    role_id = client.get(f"/api/inventories/{inventory_id}").json()["roles"][0]["id"]

    resp = client.post(f"/api/roles/{role_id}/discard")
    assert resp.status_code == 200
    assert resp.json()["discarded_at"] is not None

    detail = client.get(f"/api/inventories/{inventory_id}").json()
    assert detail["roles"] == []  # hidden by default

    detail_all = client.get(f"/api/inventories/{inventory_id}?include_discarded=true").json()
    role = detail_all["roles"][0]
    assert role["discarded_at"] is not None
    assert all(u["discarded_at"] is not None for u in role["units"])

    resp = client.post(f"/api/roles/{role_id}/restore")
    assert resp.status_code == 200
    assert resp.json()["discarded_at"] is None

    detail = client.get(f"/api/inventories/{inventory_id}").json()
    assert len(detail["roles"]) == 1
    assert all(u["discarded_at"] is None for u in detail["roles"][0]["units"])


def create_inventory_and_flow(client, db_path):
    conn = connect(db_path)
    conn.execute("INSERT INTO profile (name) VALUES ('p')")
    conn.execute("INSERT INTO inventory (profile_id, name) VALUES (1, 'inv')")
    conn.commit()
    inv_id = conn.execute("SELECT id FROM inventory").fetchone()["id"]
    conn.close()
    flow_resp = client.post("/api/flows", json={"name": "My Flow", "inventory_id": inv_id})
    return inv_id, flow_resp


def test_discarded_job_is_hidden_from_the_flows_list_and_shown_under_the_toggle(client, db_path):
    _, flow_resp = create_inventory_and_flow(client, db_path)
    flow_id = flow_resp.json()["id"]
    job_id = client.post(f"/api/flows/{flow_id}/jobs", json={"title": "t"}).json()["job"]["id"]

    flows = client.get("/api/flows").json()["flows"]
    assert any(f["id"] == flow_id for f in flows)

    resp = client.post(f"/api/jobs/{job_id}/discard")
    assert resp.status_code == 200
    assert resp.json()["discarded_at"] is not None

    flows = client.get("/api/flows").json()["flows"]
    assert all(f["id"] != flow_id for f in flows)  # hidden by default

    flows_all = client.get("/api/flows?include_discarded=true").json()["flows"]
    entry = next(f for f in flows_all if f["id"] == flow_id)
    assert entry["latest_job_id"] == job_id
    assert entry["latest_job_discarded_at"] is not None

    resp = client.post(f"/api/jobs/{job_id}/restore")
    assert resp.status_code == 200
    assert resp.json()["discarded_at"] is None

    flows = client.get("/api/flows").json()["flows"]
    assert any(f["id"] == flow_id for f in flows)


def test_discard_job_blocked_while_its_window_is_open_then_works_once_closed(client, mock_llm, db_path):
    _, flow_resp = create_inventory_and_flow(client, db_path)
    flow_id = flow_resp.json()["id"]
    job_id = client.post(f"/api/flows/{flow_id}/jobs", json={"title": "t"}).json()["job"]["id"]
    mock_llm.queue("requirement_extract", json.dumps({"requirements": [{"text": "x", "weight": "high"}]}))
    mock_llm.queue("judge_batch", "not valid json")  # leaves the requirement pending
    client.post(f"/api/jobs/{job_id}/submit-jd", json={"jd_text": "jd"})

    conn = connect(db_path)
    conn.execute("UPDATE job SET judging_deadline = datetime('now', '+20 minutes') WHERE id = ?", (job_id,))
    conn.commit()
    conn.close()

    resp = client.post(f"/api/jobs/{job_id}/discard")
    assert resp.status_code == 409

    client.post(f"/api/jobs/{job_id}/finish")
    resp = client.post(f"/api/jobs/{job_id}/discard")
    assert resp.status_code == 200


def test_a_flow_with_no_jobs_always_shows(client, db_path):
    _, flow_resp = create_inventory_and_flow(client, db_path)
    flow_id = flow_resp.json()["id"]

    flows = client.get("/api/flows").json()["flows"]
    entry = next(f for f in flows if f["id"] == flow_id)
    assert entry["latest_job_id"] is None
    assert entry["latest_job_discarded_at"] is None
