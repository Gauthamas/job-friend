"""Add role" reuses the exact commit path resume import uses (no model
call), with one role and no units -- units are added afterward through
the existing add-unit flow (no new endpoint for either)."""

import json

from tests.test_inventories_route import parse_events

RESUME_STRUCTURE_RESPONSE = json.dumps({
    "roles": [{
        "company": "Seed Co", "title": "Seed Role", "start": "2019-06", "end": "2021-03",
        "section": "work", "bullets": ["a seed bullet"],
    }]
})


def make_inventory(client, mock_llm) -> int:
    mock_llm.queue("resume_structure", RESUME_STRUCTURE_RESPONSE)
    draft_resp = client.post("/api/inventories", data={"name": "My Resume", "text": "some resume text"})
    done = next(e for e in parse_events(draft_resp) if e["event"] == "done")
    return done["inventory_id"]


def test_add_role_saves_with_no_units_then_a_unit_can_be_added(client, mock_llm):
    inventory_id = make_inventory(client, mock_llm)

    commit_body = {
        "roles": [{
            "company": "Acme Corp", "title": "Hand-typed Role",
            "start_date": "2022", "end_date": "",
            "sort_order": 1, "units": [],
        }]
    }
    resp = client.post(f"/api/inventories/{inventory_id}/commit", json=commit_body)

    assert resp.status_code == 200
    role = resp.json()["roles"][0]
    assert role["company"] == "Acme Corp"
    assert role["title"] == "Hand-typed Role"
    assert role["start_date"] == "2022"
    assert role["end_date"] == ""
    assert role["units"] == []
    role_id = role["id"]

    detail = client.get(f"/api/inventories/{inventory_id}").json()
    saved_role = next(r for r in detail["roles"] if r["id"] == role_id)
    assert saved_role["units"] == []

    add_resp = client.post(f"/api/roles/{role_id}/units", json={"text": "a hand-typed bullet"})
    assert add_resp.status_code == 201
    assert add_resp.json()["text"] == "a hand-typed bullet"

    detail = client.get(f"/api/inventories/{inventory_id}").json()
    saved_role = next(r for r in detail["roles"] if r["id"] == role_id)
    assert len(saved_role["units"]) == 1
    assert saved_role["units"][0]["text"] == "a hand-typed bullet"


def test_add_role_makes_no_model_call(client, mock_llm):
    inventory_id = make_inventory(client, mock_llm)
    calls_before = len(mock_llm.calls)

    commit_body = {
        "roles": [{"company": "C", "title": "T", "start_date": "", "end_date": "", "sort_order": 1, "units": []}]
    }
    resp = client.post(f"/api/inventories/{inventory_id}/commit", json=commit_body)

    assert resp.status_code == 200
    assert len(mock_llm.calls) == calls_before
