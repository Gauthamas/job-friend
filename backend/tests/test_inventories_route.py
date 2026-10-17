import json

RESUME_STRUCTURE_RESPONSE = json.dumps({
    "roles": [{
        "company": "Nimbus Retail",
        "title": "Software Engineer II",
        "start": "2019-06",
        "end": "2021-03",
        "section": "work",
        "bullets": [
            "Led mobile checkout efforts across search, cart, and rewards teams",
            "Cut app crash rate by 35% by building a new crash-reporting pipeline",
        ],
    }]
})


def parse_events(resp) -> list[dict]:
    # SSE framing: "data: {json}\n\n" per event.
    return [json.loads(block[len("data: "):]) for block in resp.text.split("\n\n") if block.strip()]


def test_create_inventory_from_pasted_text_streams_role_and_bullet_events(client, mock_llm):
    mock_llm.queue("resume_structure", RESUME_STRUCTURE_RESPONSE)

    resp = client.post(
        "/api/inventories",
        data={"name": "My Resume", "text": "some resume text"},
    )

    assert resp.status_code == 200
    events = parse_events(resp)
    kinds = [e["event"] for e in events]
    assert "role_meta" in kinds
    assert "bullet" in kinds
    assert "role_done" in kinds
    assert kinds[-1] == "done"

    role_meta = next(e for e in events if e["event"] == "role_meta")
    assert role_meta["company"] == "Nimbus Retail"
    assert role_meta["section"] == "work"

    bullets = [e for e in events if e["event"] == "bullet"]
    assert len(bullets) == 2
    assert bullets[0]["text"] == "Led mobile checkout efforts across search, cart, and rewards teams"

    done = events[-1]
    assert done["inventory_id"] > 0
    assert done["draft"]["roles"][0]["company"] == "Nimbus Retail"
    assert len(done["draft"]["roles"][0]["bullets"]) == 2


def test_create_inventory_requires_file_or_text(client):
    resp = client.post("/api/inventories", data={"name": "My Resume"})
    assert resp.status_code == 400


def test_create_inventory_rejects_both_file_and_text(client):
    resp = client.post(
        "/api/inventories",
        data={"name": "My Resume", "text": "some text"},
        files={"file": ("resume.pdf", b"%PDF-1.4 fake", "application/pdf")},
    )
    assert resp.status_code == 400


def test_extraction_failure_emits_error_event_and_leaves_no_orphan_inventory(client, mock_llm, tmp_path):
    mock_llm.queue("resume_structure", "not valid json")

    resp = client.post(
        "/api/inventories",
        data={"name": "My Resume", "text": "some resume text"},
    )
    assert resp.status_code == 200
    events = parse_events(resp)
    assert events[-1]["event"] == "error"

    from app.db import connect
    conn = connect(str(tmp_path / "test.db"))
    count = conn.execute("SELECT COUNT(*) AS c FROM inventory").fetchone()["c"]
    conn.close()
    assert count == 0


def test_commit_persists_roles_and_units_with_permanent_ids(client, mock_llm):
    mock_llm.queue("resume_structure", RESUME_STRUCTURE_RESPONSE)
    draft_resp = client.post(
        "/api/inventories",
        data={"name": "My Resume", "text": "some resume text"},
    )
    done = next(e for e in parse_events(draft_resp) if e["event"] == "done")
    inventory_id = done["inventory_id"]

    commit_body = {
        "roles": [{
            "company": "Nimbus Retail",
            "title": "Software Engineer II",
            "start_date": "2019-06",
            "end_date": "2021-03",
            "sort_order": 0,
            "units": [
                {"text": "Led mobile checkout efforts", "source": "parsed", "sort_order": 0},
                {"text": "Cut app crash rate by 35%", "source": "parsed", "sort_order": 1},
            ],
        }]
    }

    resp = client.post(f"/api/inventories/{inventory_id}/commit", json=commit_body)

    assert resp.status_code == 200
    body = resp.json()
    assert body["inventory_id"] == inventory_id
    role = body["roles"][0]
    assert role["id"] > 0
    assert len(role["units"]) == 2
    assert role["units"][0]["id"] != role["units"][1]["id"]
    assert all(u["id"] > 0 for u in role["units"])


def test_commit_unknown_inventory_returns_404(client):
    resp = client.post("/api/inventories/999/commit", json={"roles": []})
    assert resp.status_code == 404


def test_discard_removes_empty_inventory(client, mock_llm):
    mock_llm.queue("resume_structure", RESUME_STRUCTURE_RESPONSE)
    draft_resp = client.post("/api/inventories", data={"name": "Abandoned draft", "text": "resume text"})
    inventory_id = next(e for e in parse_events(draft_resp) if e["event"] == "done")["inventory_id"]

    resp = client.delete(f"/api/inventories/{inventory_id}")
    assert resp.status_code == 204

    assert client.get(f"/api/inventories/{inventory_id}").status_code == 404
    ids = [i["id"] for i in client.get("/api/inventories").json()["inventories"]]
    assert inventory_id not in ids


def test_discard_rejects_inventory_with_saved_data(client, mock_llm):
    mock_llm.queue("resume_structure", RESUME_STRUCTURE_RESPONSE)
    draft_resp = client.post("/api/inventories", data={"name": "Committed", "text": "resume text"})
    inventory_id = next(e for e in parse_events(draft_resp) if e["event"] == "done")["inventory_id"]

    commit_body = {
        "roles": [{
            "company": "Nimbus Retail", "title": "Software Engineer II",
            "start_date": "2019-06", "end_date": "2021-03", "sort_order": 0,
            "units": [{"text": "bullet", "source": "parsed", "sort_order": 0}],
        }]
    }
    client.post(f"/api/inventories/{inventory_id}/commit", json=commit_body)

    resp = client.delete(f"/api/inventories/{inventory_id}")
    assert resp.status_code == 400
    assert client.get(f"/api/inventories/{inventory_id}").status_code == 200


def test_discard_unknown_inventory_returns_404(client):
    resp = client.delete("/api/inventories/999")
    assert resp.status_code == 404
