"""Milestone 3: fresh vs autofill,
per-pair answers, confirm-all, and the Continue gate. No model calls."""

import numpy as np
import pytest

from app.config import settings
from app.db import connect
from app.vectors import to_blob

MODEL = "test-embed-model"


@pytest.fixture(autouse=True)
def _use_test_embed_model(monkeypatch):
    monkeypatch.setattr(settings, "embed_model", MODEL)


def _setup_job(db_path: str, title: str = "job") -> int:
    conn = connect(db_path)
    if not conn.execute("SELECT 1 FROM profile").fetchone():
        conn.execute("INSERT INTO profile (name) VALUES ('p')")
        conn.execute("INSERT INTO inventory (profile_id, name) VALUES (1, 'inv')")
        conn.execute("INSERT INTO role (inventory_id, company, title, sort_order) VALUES (1, 'c', 't', 0)")
        conn.execute("INSERT INTO flow (profile_id, name, inventory_id) VALUES (1, 'f', 1)")
    else:
        conn.execute("INSERT INTO flow (profile_id, name, inventory_id) VALUES (1, 'f', 1)")
    flow_id = conn.execute("SELECT id FROM flow ORDER BY id DESC LIMIT 1").fetchone()["id"]
    conn.execute("INSERT INTO job (flow_id, title, jd_text) VALUES (?, ?, 'jd')", (flow_id, title))
    job_id = conn.execute("SELECT id FROM job ORDER BY id DESC LIMIT 1").fetchone()["id"]
    conn.commit()
    conn.close()
    return job_id


def _add_matched_unit(db_path: str, job_id: int, text: str, vector: list[float], sort: int = 0) -> int:
    conn = connect(db_path)
    conn.execute("INSERT INTO unit (role_id, text, source, sort_order) VALUES (1, ?, 'manual', ?)", (text, sort))
    unit_id = conn.execute("SELECT id FROM unit ORDER BY id DESC LIMIT 1").fetchone()["id"]
    conn.execute(
        "INSERT INTO requirement (job_id, text, weight, source, status, sort_order) "
        "VALUES (?, 'req', 'high', 'extracted', 'done', ?)", (job_id, sort),
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


def _vec(a: float, b: float) -> list[float]:
    return [a, b] + [0.0] * 14


def test_fresh_build_leaves_every_pair_unanswered(client, db_path):
    job_id = _setup_job(db_path)
    _add_matched_unit(db_path, job_id, "unit a", _vec(1.0, 0.0), 0)
    _add_matched_unit(db_path, job_id, "unit b", _vec(0.9, 0.1), 1)
    client.post(f"/api/jobs/{job_id}/pairs/build")

    pairs = client.get(f"/api/jobs/{job_id}/pairs").json()["pairs"]
    assert all(p["statement"]["status"] == "unanswered" for p in pairs)
    assert all(p["statement"]["autofilled_from_job_id"] is None for p in pairs)


def test_autofill_copies_the_latest_statement_and_leaves_new_pairs_blank(client, db_path):
    # Job A: a pair with a written statement.
    job_a = _setup_job(db_path, title="Earlier job")
    unit_1 = _add_matched_unit(db_path, job_a, "shared unit one", _vec(1.0, 0.0), 0)
    unit_2 = _add_matched_unit(db_path, job_a, "shared unit two", _vec(0.9, 0.1), 1)
    client.post(f"/api/jobs/{job_a}/pairs/build")
    pair_a = client.get(f"/api/jobs/{job_a}/pairs").json()["pairs"][0]
    client.patch(f"/api/statements/{pair_a['statement']['id']}", json={"status": "written", "text": "both are Android"})

    # Job B: the SAME two units paired again, plus a brand new third unit
    # that was never paired with anything before.
    job_b = _setup_job(db_path, title="Later job")
    conn = connect(db_path)
    for rid in (unit_1, unit_2):
        conn.execute(
            "INSERT INTO requirement (job_id, text, weight, source, status, sort_order) "
            "VALUES (?, 'req', 'high', 'extracted', 'done', 0)", (job_b,),
        )
        requirement_id = conn.execute("SELECT id FROM requirement ORDER BY id DESC LIMIT 1").fetchone()["id"]
        conn.execute("INSERT INTO judgment (requirement_id, unit_id, model_verdict) VALUES (?, ?, 'match')", (requirement_id, rid))
    conn.commit()
    conn.close()
    unit_3 = _add_matched_unit(db_path, job_b, "brand new unit", _vec(0.0, 1.0), 2)

    client.post(f"/api/jobs/{job_b}/pairs/build")
    resp = client.post(f"/api/jobs/{job_b}/pairs/autofill")
    assert resp.json()["autofilled_count"] == 1  # only the (unit_1, unit_2) pair had history

    pairs_b = client.get(f"/api/jobs/{job_b}/pairs").json()["pairs"]
    old_pair = next(p for p in pairs_b if {p["unit_a"]["id"], p["unit_b"]["id"]} == {unit_1, unit_2})
    new_pair = next(p for p in pairs_b if unit_3 in (p["unit_a"]["id"], p["unit_b"]["id"]))

    assert old_pair["statement"]["status"] == "written"
    assert old_pair["statement"]["text"] == "both are Android"
    assert old_pair["statement"]["autofilled_from_job_id"] == job_a
    assert old_pair["statement"]["confirmed"] is False  # unconfirmed until Confirm all or an edit

    assert new_pair["statement"]["status"] == "unanswered"
    assert new_pair["statement"]["autofilled_from_job_id"] is None


def test_later_edit_to_the_source_job_statement_does_not_change_the_autofilled_copy(client, db_path):
    job_a = _setup_job(db_path, title="Earlier job")
    unit_1 = _add_matched_unit(db_path, job_a, "unit one", _vec(1.0, 0.0), 0)
    unit_2 = _add_matched_unit(db_path, job_a, "unit two", _vec(0.9, 0.1), 1)
    client.post(f"/api/jobs/{job_a}/pairs/build")
    pair_a = client.get(f"/api/jobs/{job_a}/pairs").json()["pairs"][0]
    client.patch(f"/api/statements/{pair_a['statement']['id']}", json={"status": "written", "text": "original sentence"})

    job_b = _setup_job(db_path, title="Later job")
    conn = connect(db_path)
    for rid in (unit_1, unit_2):
        conn.execute(
            "INSERT INTO requirement (job_id, text, weight, source, status, sort_order) "
            "VALUES (?, 'req', 'high', 'extracted', 'done', 0)", (job_b,),
        )
        requirement_id = conn.execute("SELECT id FROM requirement ORDER BY id DESC LIMIT 1").fetchone()["id"]
        conn.execute("INSERT INTO judgment (requirement_id, unit_id, model_verdict) VALUES (?, ?, 'match')", (requirement_id, rid))
    conn.commit()
    conn.close()
    client.post(f"/api/jobs/{job_b}/pairs/build")
    client.post(f"/api/jobs/{job_b}/pairs/autofill")
    copy_statement_id = client.get(f"/api/jobs/{job_b}/pairs").json()["pairs"][0]["statement"]["id"]

    # Edit the OLD job's statement after the copy was made.
    client.patch(f"/api/statements/{pair_a['statement']['id']}", json={"status": "written", "text": "edited later"})

    copy_after = client.get(f"/api/jobs/{job_b}/pairs").json()["pairs"][0]["statement"]
    assert copy_after["text"] == "original sentence"  # unchanged -- a copy, not a link
    assert copy_after["id"] == copy_statement_id


def test_fresh_reset_undoes_autofill(client, db_path):
    job_a = _setup_job(db_path, title="Earlier job")
    unit_1 = _add_matched_unit(db_path, job_a, "unit one", _vec(1.0, 0.0), 0)
    unit_2 = _add_matched_unit(db_path, job_a, "unit two", _vec(0.9, 0.1), 1)
    client.post(f"/api/jobs/{job_a}/pairs/build")
    pair_a = client.get(f"/api/jobs/{job_a}/pairs").json()["pairs"][0]
    client.patch(f"/api/statements/{pair_a['statement']['id']}", json={"status": "written", "text": "x"})

    job_b = _setup_job(db_path, title="Later job")
    conn = connect(db_path)
    for rid in (unit_1, unit_2):
        conn.execute(
            "INSERT INTO requirement (job_id, text, weight, source, status, sort_order) "
            "VALUES (?, 'req', 'high', 'extracted', 'done', 0)", (job_b,),
        )
        requirement_id = conn.execute("SELECT id FROM requirement ORDER BY id DESC LIMIT 1").fetchone()["id"]
        conn.execute("INSERT INTO judgment (requirement_id, unit_id, model_verdict) VALUES (?, ?, 'match')", (requirement_id, rid))
    conn.commit()
    conn.close()
    client.post(f"/api/jobs/{job_b}/pairs/build")
    client.post(f"/api/jobs/{job_b}/pairs/autofill")
    assert client.get(f"/api/jobs/{job_b}/pairs").json()["pairs"][0]["statement"]["status"] == "written"

    client.post(f"/api/jobs/{job_b}/pairs/fresh")
    statement = client.get(f"/api/jobs/{job_b}/pairs").json()["pairs"][0]["statement"]
    assert statement["status"] == "unanswered"
    assert statement["text"] is None
    assert statement["autofilled_from_job_id"] is None


def test_confirm_all_marks_autofilled_statements_confirmed_and_clears_chip(client, db_path):
    job_a = _setup_job(db_path, title="Earlier job")
    unit_1 = _add_matched_unit(db_path, job_a, "unit one", _vec(1.0, 0.0), 0)
    unit_2 = _add_matched_unit(db_path, job_a, "unit two", _vec(0.9, 0.1), 1)
    client.post(f"/api/jobs/{job_a}/pairs/build")
    pair_a = client.get(f"/api/jobs/{job_a}/pairs").json()["pairs"][0]
    client.patch(f"/api/statements/{pair_a['statement']['id']}", json={"status": "written", "text": "x"})

    job_b = _setup_job(db_path, title="Later job")
    conn = connect(db_path)
    for rid in (unit_1, unit_2):
        conn.execute(
            "INSERT INTO requirement (job_id, text, weight, source, status, sort_order) "
            "VALUES (?, 'req', 'high', 'extracted', 'done', 0)", (job_b,),
        )
        requirement_id = conn.execute("SELECT id FROM requirement ORDER BY id DESC LIMIT 1").fetchone()["id"]
        conn.execute("INSERT INTO judgment (requirement_id, unit_id, model_verdict) VALUES (?, ?, 'match')", (requirement_id, rid))
    conn.commit()
    conn.close()
    client.post(f"/api/jobs/{job_b}/pairs/build")
    client.post(f"/api/jobs/{job_b}/pairs/autofill")

    before = client.get(f"/api/jobs/{job_b}/pairs").json()
    assert before["all_ready"] is False  # unconfirmed autofill blocks Continue

    client.post(f"/api/jobs/{job_b}/statements/confirm-all")
    after = client.get(f"/api/jobs/{job_b}/pairs").json()
    assert after["all_ready"] is True
    statement = after["pairs"][0]["statement"]
    assert statement["confirmed"] is True
    assert statement["autofilled_from_job_id"] is None  # chip clears on confirm


def test_continue_gating_blocked_by_unanswered_pair(client, db_path):
    job_id = _setup_job(db_path)
    _add_matched_unit(db_path, job_id, "unit a", _vec(1.0, 0.0), 0)
    _add_matched_unit(db_path, job_id, "unit b", _vec(0.9, 0.1), 1)
    client.post(f"/api/jobs/{job_id}/pairs/build")
    assert client.get(f"/api/jobs/{job_id}/pairs").json()["all_ready"] is False


def test_continue_gating_allowed_once_every_pair_is_written_or_none(client, db_path):
    job_id = _setup_job(db_path)
    _add_matched_unit(db_path, job_id, "unit a", _vec(1.0, 0.0), 0)
    _add_matched_unit(db_path, job_id, "unit b", _vec(0.9, 0.1), 1)
    client.post(f"/api/jobs/{job_id}/pairs/build")
    statement_id = client.get(f"/api/jobs/{job_id}/pairs").json()["pairs"][0]["statement"]["id"]

    client.patch(f"/api/statements/{statement_id}", json={"status": "none"})
    assert client.get(f"/api/jobs/{job_id}/pairs").json()["all_ready"] is True


def test_patch_statement_written_and_none_and_unknown_statement_404(client, db_path):
    job_id = _setup_job(db_path)
    _add_matched_unit(db_path, job_id, "unit a", _vec(1.0, 0.0), 0)
    _add_matched_unit(db_path, job_id, "unit b", _vec(0.9, 0.1), 1)
    client.post(f"/api/jobs/{job_id}/pairs/build")
    statement_id = client.get(f"/api/jobs/{job_id}/pairs").json()["pairs"][0]["statement"]["id"]

    resp = client.patch(f"/api/statements/{statement_id}", json={"status": "written", "text": "a shared sentence"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "written"
    assert resp.json()["text"] == "a shared sentence"

    resp = client.patch(f"/api/statements/{statement_id}", json={"status": "none"})
    assert resp.json()["status"] == "none"
    assert resp.json()["text"] is None

    assert client.patch("/api/statements/999999", json={"status": "none"}).status_code == 404
