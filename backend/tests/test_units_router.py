import json


def make_committed_unit(client, mock_llm, text="original bullet", context=None):
    resume_response = json.dumps({
        "roles": [{
            "company": "Acme", "title": "Engineer", "start": "2019-06", "end": "2021-03",
            "section": "work", "bullets": [text],
        }]
    })
    mock_llm.queue("resume_structure", resume_response)
    draft_resp = client.post("/api/inventories", data={"name": "Resume", "text": "resume text"})
    events = [json.loads(line[len("data: "):]) for line in draft_resp.text.split("\n\n") if line.strip()]
    inventory_id = next(e for e in events if e["event"] == "done")["inventory_id"]

    commit_body = {
        "roles": [{
            "company": "Acme", "title": "Engineer", "start_date": "2019-06", "end_date": "2021-03",
            "sort_order": 0,
            "units": [{"text": text, "source": "parsed", "sort_order": 0, "context": context}],
        }]
    }
    commit_resp = client.post(f"/api/inventories/{inventory_id}/commit", json=commit_body)
    unit = commit_resp.json()["roles"][0]["units"][0]
    return inventory_id, unit["id"]


def commit_two_units_same_role(client, mock_llm):
    resume_response = json.dumps({
        "roles": [{
            "company": "Acme", "title": "Engineer", "start": "2019-06", "end": "2021-03",
            "section": "work", "bullets": ["first bullet"],
        }]
    })
    mock_llm.queue("resume_structure", resume_response)
    draft_resp = client.post("/api/inventories", data={"name": "Resume", "text": "resume text"})
    events = [json.loads(line[len("data: "):]) for line in draft_resp.text.split("\n\n") if line.strip()]
    inventory_id = next(e for e in events if e["event"] == "done")["inventory_id"]

    commit_body = {
        "roles": [{
            "company": "Acme", "title": "Engineer", "start_date": "2019-06", "end_date": "2021-03",
            "sort_order": 0,
            "units": [
                {"text": "first bullet", "source": "parsed", "sort_order": 0},
                {"text": "second bullet", "source": "parsed", "sort_order": 1},
            ],
        }]
    }
    commit_resp = client.post(f"/api/inventories/{inventory_id}/commit", json=commit_body).json()
    units = commit_resp["roles"][0]["units"]
    return inventory_id, units[0]["id"], units[1]["id"]


def test_patch_unit_updates_text_and_reembeds(client, mock_llm):
    _, unit_id = make_committed_unit(client, mock_llm)

    resp = client.patch(f"/api/units/{unit_id}", json={"text": "updated bullet text"})

    assert resp.status_code == 200
    assert resp.json()["text"] == "updated bullet text"


def test_patch_unit_404_for_unknown_unit(client):
    resp = client.patch("/api/units/999", json={"text": "x"})
    assert resp.status_code == 404


def test_patch_unit_rejects_empty_text(client, mock_llm):
    _, unit_id = make_committed_unit(client, mock_llm)
    resp = client.patch(f"/api/units/{unit_id}", json={"text": ""})
    assert resp.status_code == 400


def test_patch_unit_can_explicitly_clear_a_field(client, mock_llm):
    _, unit_id = make_committed_unit(client, mock_llm, context="some context")
    assert client.get(f"/api/units/{unit_id}").json()["context"] == "some context"

    resp = client.patch(f"/api/units/{unit_id}", json={"context": None})

    assert resp.status_code == 200
    assert resp.json()["context"] is None


def test_patch_unit_omitted_field_is_left_unchanged(client, mock_llm):
    _, unit_id = make_committed_unit(client, mock_llm, context="keep me")

    resp = client.patch(f"/api/units/{unit_id}", json={"text": "new text"})

    assert resp.status_code == 200
    assert resp.json()["context"] == "keep me"


def test_get_unit(client, mock_llm):
    _, unit_id = make_committed_unit(client, mock_llm, text="findable text")
    resp = client.get(f"/api/units/{unit_id}")
    assert resp.status_code == 200
    assert resp.json()["text"] == "findable text"


def test_delete_unit_is_soft_delete(client, mock_llm):
    _, unit_id = make_committed_unit(client, mock_llm)

    resp = client.delete(f"/api/units/{unit_id}")
    assert resp.status_code == 204

    # Now invisible via the API (soft-deleted units are excluded), but the
    # DB row itself must still exist — that's covered at the DB level in
    # test_migrations.py; here we only need the API-visible contract.
    assert client.get(f"/api/units/{unit_id}").status_code == 404


def test_delete_unit_404_for_unknown_unit(client):
    resp = client.delete("/api/units/999")
    assert resp.status_code == 404


def test_split_unit_keeps_original_id_for_first_half(client, mock_llm):
    _, unit_id = make_committed_unit(client, mock_llm, text="first part second part")
    split_at = len("first part ")

    resp = client.post(f"/api/units/{unit_id}/split", json={"split_at": split_at})

    assert resp.status_code == 200
    body = resp.json()
    assert body["original"]["id"] == unit_id
    assert body["original"]["text"] == "first part"
    assert body["new_unit"]["text"] == "second part"
    assert body["new_unit"]["id"] != unit_id


def test_split_unit_rejects_split_leaving_empty_side(client, mock_llm):
    _, unit_id = make_committed_unit(client, mock_llm, text="short")
    resp = client.post(f"/api/units/{unit_id}/split", json={"split_at": 0})
    assert resp.status_code == 400


def test_merge_combines_text_target_first(client, mock_llm):
    _, first_id, second_id = commit_two_units_same_role(client, mock_llm)

    resp = client.post(f"/api/units/{first_id}/merge", json={"other_unit_id": second_id})

    assert resp.status_code == 200
    body = resp.json()
    assert body["survivor"]["id"] == first_id
    assert body["survivor"]["text"] == "first bullet second bullet"
    assert body["merged_unit_id"] == second_id
    assert client.get(f"/api/units/{second_id}").status_code == 404


def test_merge_rejects_units_from_different_roles(client, mock_llm):
    resume_response = json.dumps({
        "roles": [
            {"company": "Acme", "title": "Eng", "start": "2019-06", "end": "2021-03", "section": "work", "bullets": ["a"]},
            {"company": "Beta", "title": "Eng", "start": "2018-01", "end": "2019-01", "section": "work", "bullets": ["b"]},
        ]
    })
    mock_llm.queue("resume_structure", resume_response)
    draft_resp = client.post("/api/inventories", data={"name": "Resume", "text": "resume text"})
    events = [json.loads(line[len("data: "):]) for line in draft_resp.text.split("\n\n") if line.strip()]
    inventory_id = next(e for e in events if e["event"] == "done")["inventory_id"]

    commit_body = {
        "roles": [
            {"company": "Acme", "title": "Eng", "start_date": "2019-06", "end_date": "2021-03", "sort_order": 0,
             "units": [{"text": "a", "source": "parsed", "sort_order": 0}]},
            {"company": "Beta", "title": "Eng", "start_date": "2018-01", "end_date": "2019-01", "sort_order": 1,
             "units": [{"text": "b", "source": "parsed", "sort_order": 0}]},
        ]
    }
    commit_resp = client.post(f"/api/inventories/{inventory_id}/commit", json=commit_body).json()
    unit_a = commit_resp["roles"][0]["units"][0]["id"]
    unit_b = commit_resp["roles"][1]["units"][0]["id"]

    resp = client.post(f"/api/units/{unit_a}/merge", json={"other_unit_id": unit_b})
    assert resp.status_code == 400


def test_merge_rejects_self_merge(client, mock_llm):
    _, unit_id = make_committed_unit(client, mock_llm)
    resp = client.post(f"/api/units/{unit_id}/merge", json={"other_unit_id": unit_id})
    assert resp.status_code == 400
