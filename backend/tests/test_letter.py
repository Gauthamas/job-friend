"""Milestone 6: the writing view. No model
calls anywhere -- every assertion here is about mechanical ranking,
pointer proposal, and the Generate/Finish actions."""

from app.config import settings
from app.db import connect
from app.letter import build_sections, generate_letter_text, rank_matched_requirements
from tests.test_thread_ranking import add_pair_with_statement, make_model_thread, setup_job


def add_requirement(db_path: str, job_id: int, text: str, weight: str, sort_order: int) -> int:
    conn = connect(db_path)
    conn.execute(
        "INSERT INTO requirement (job_id, text, weight, source, status, sort_order) "
        "VALUES (?, ?, ?, 'extracted', 'done', ?)", (job_id, text, weight, sort_order),
    )
    requirement_id = conn.execute("SELECT id FROM requirement ORDER BY id DESC LIMIT 1").fetchone()["id"]
    conn.commit()
    conn.close()
    return requirement_id


def add_judgment(db_path: str, requirement_id: int, unit_id: int, model_verdict: str, score: float = 0.5, why: str | None = None):
    conn = connect(db_path)
    conn.execute(
        "INSERT INTO judgment (requirement_id, unit_id, model_verdict, score, why) VALUES (?, ?, ?, ?, ?)",
        (requirement_id, unit_id, model_verdict, score, why),
    )
    conn.commit()
    conn.close()


def add_unit(db_path: str, text: str) -> int:
    conn = connect(db_path)
    conn.execute("INSERT INTO unit (role_id, text, source, sort_order) VALUES (1, ?, 'manual', 0)", (text,))
    unit_id = conn.execute("SELECT id FROM unit ORDER BY id DESC LIMIT 1").fetchone()["id"]
    conn.commit()
    conn.close()
    return unit_id


def setup_job_with_role(db_path: str) -> int:
    job_id = setup_job(db_path)
    return job_id


def choose_primary(db_path: str, job_id: int, thread_id: int):
    conn = connect(db_path)
    conn.execute("INSERT INTO job_thread (job_id, thread_id, role) VALUES (?, ?, 'primary')", (job_id, thread_id))
    conn.commit()
    conn.close()


def choose_secondary(db_path: str, job_id: int, thread_id: int):
    conn = connect(db_path)
    conn.execute("INSERT INTO job_thread (job_id, thread_id, role) VALUES (?, ?, 'secondary')", (job_id, thread_id))
    conn.commit()
    conn.close()


# --- requirement ranking (weight, primary, secondary, match count, position) ---

def test_ranking_by_weight_then_primary_then_match_count_then_position(db_path):
    job_id = setup_job_with_role(db_path)
    unit_hi = add_unit(db_path, "unit high")
    unit_med = add_unit(db_path, "unit medium")
    unit_lo = add_unit(db_path, "unit low")

    req_low = add_requirement(db_path, job_id, "low weight req", "low", 0)
    add_judgment(db_path, req_low, unit_lo, "match")
    req_high = add_requirement(db_path, job_id, "high weight req", "high", 1)
    add_judgment(db_path, req_high, unit_hi, "match")
    req_med_first = add_requirement(db_path, job_id, "medium req first, 2 matches", "medium", 2)
    add_judgment(db_path, req_med_first, unit_med, "match")
    add_judgment(db_path, req_med_first, unit_lo, "match")
    req_med_second = add_requirement(db_path, job_id, "medium req second, 1 match", "medium", 3)
    add_judgment(db_path, req_med_second, unit_med, "match")

    conn = connect(db_path)
    ranked = rank_matched_requirements(conn, job_id)
    conn.close()

    assert [r["id"] for r in ranked] == [req_high, req_med_first, req_med_second, req_low]


def test_ranking_prefers_primary_then_secondary_thread_coverage(db_path):
    job_id = setup_job_with_role(db_path)
    s1, u1a, u1b = add_pair_with_statement(db_path, job_id, "s1")
    s2, u2a, u2b = add_pair_with_statement(db_path, job_id, "s2")
    t1 = make_model_thread(db_path, job_id, "Primary thread", [s1])
    conn = connect(db_path)
    run_id = conn.execute("SELECT run_id FROM thread WHERE id = ?", (t1,)).fetchone()["run_id"]
    conn.close()
    t2 = make_model_thread(db_path, job_id, "Secondary thread", [s2], run_id=run_id)
    choose_primary(db_path, job_id, t1)
    choose_secondary(db_path, job_id, t2)

    # Both "medium" weight, same match count (1) -- only thread coverage
    # and position differ. req_secondary is covered by the secondary
    # thread's unit (u2a); req_primary by the primary thread's unit (u1a).
    # Give req_secondary an earlier position so position alone would rank
    # it first if thread coverage weren't applied.
    req_secondary = add_requirement(db_path, job_id, "covered by secondary", "medium", 0)
    add_judgment(db_path, req_secondary, u2a, "match")
    req_primary = add_requirement(db_path, job_id, "covered by primary", "medium", 1)
    add_judgment(db_path, req_primary, u1a, "match")

    conn = connect(db_path)
    ranked = rank_matched_requirements(conn, job_id)
    conn.close()
    assert [r["id"] for r in ranked] == [req_primary, req_secondary]


# --- N (matched_sections) ---

def test_matched_sections_setting_controls_how_many_are_shown(client, db_path, monkeypatch):
    job_id = setup_job_with_role(db_path)
    units = [add_unit(db_path, f"unit {i}") for i in range(3)]
    reqs = [add_requirement(db_path, job_id, f"req {i}", "high", i) for i in range(3)]
    for req, unit in zip(reqs, units):
        add_judgment(db_path, req, unit, "match")

    monkeypatch.setattr(settings, "matched_sections", 2)
    body = client.get(f"/api/jobs/{job_id}/letter").json()
    assert body["matched_shown"] == 2
    assert body["matched_total"] == 3
    shown_keys = [s["key"] for s in body["sections"] if s["kind"] == "requirement"]
    assert len(shown_keys) == 2

    monkeypatch.setattr(settings, "matched_sections", 3)
    body2 = client.get(f"/api/jobs/{job_id}/letter").json()
    assert body2["matched_shown"] == 3

    monkeypatch.setattr(settings, "matched_sections", 10)
    body3 = client.get(f"/api/jobs/{job_id}/letter").json()
    assert body3["matched_shown"] == 3  # raising beyond available changes nothing
    assert body3["matched_total"] == 3


# --- Weak and Gaps ---

def test_weak_and_gaps_sections_contain_the_right_requirements(client, db_path):
    job_id = setup_job_with_role(db_path)
    unit_w = add_unit(db_path, "weak unit")
    req_weak = add_requirement(db_path, job_id, "weak req", "medium", 0)
    add_judgment(db_path, req_weak, unit_w, "weak")
    req_gap = add_requirement(db_path, job_id, "gap req", "low", 1)
    add_judgment(db_path, req_gap, unit_w, "none")

    body = client.get(f"/api/jobs/{job_id}/letter").json()
    weak_section = next(s for s in body["sections"] if s["key"] == "weak")
    gaps_section = next(s for s in body["sections"] if s["key"] == "gaps")
    assert [r["id"] for r in weak_section["requirements"]] == [req_weak]
    assert [r["id"] for r in gaps_section["requirements"]] == [req_gap]


def test_weak_section_groups_pointers_per_requirement_same_unit_twice_is_not_a_collision(client, db_path):
    """Regression: the same unit can be a weak pointer on two different
    requirements. A flat, unit-id-keyed pointer list for the whole Weak
    section would collide (and crashed the real writing view) -- pointers
    must be grouped per requirement instead."""
    job_id = setup_job_with_role(db_path)
    unit_id = add_unit(db_path, "unit weak on two requirements")
    req_a = add_requirement(db_path, job_id, "weak req A", "medium", 0)
    add_judgment(db_path, req_a, unit_id, "weak")
    req_b = add_requirement(db_path, job_id, "weak req B", "low", 1)
    add_judgment(db_path, req_b, unit_id, "weak")

    body = client.get(f"/api/jobs/{job_id}/letter").json()
    weak_section = next(s for s in body["sections"] if s["key"] == "weak")
    groups = {r["id"]: r["pointers"] for r in weak_section["requirements"]}
    assert set(groups.keys()) == {req_a, req_b}
    assert [p["unit_id"] for p in groups[req_a]] == [unit_id]
    assert [p["unit_id"] for p in groups[req_b]] == [unit_id]


def test_weak_and_gaps_hidden_when_empty(client, db_path):
    job_id = setup_job_with_role(db_path)
    unit_id = add_unit(db_path, "unit")
    req = add_requirement(db_path, job_id, "req", "high", 0)
    add_judgment(db_path, req, unit_id, "match")

    body = client.get(f"/api/jobs/{job_id}/letter").json()
    keys = [s["key"] for s in body["sections"]]
    assert "weak" not in keys
    assert "gaps" not in keys


# --- pointer ordering and chips ---

def test_pointer_order_puts_primary_then_secondary_thread_units_first(db_path):
    job_id = setup_job_with_role(db_path)
    s1, u_primary, _ = add_pair_with_statement(db_path, job_id, "s1")
    s2, u_secondary, _ = add_pair_with_statement(db_path, job_id, "s2")
    u_plain = add_unit(db_path, "plain unit, highest score")
    t1 = make_model_thread(db_path, job_id, "P", [s1])
    conn = connect(db_path)
    run_id = conn.execute("SELECT run_id FROM thread WHERE id = ?", (t1,)).fetchone()["run_id"]
    conn.close()
    t2 = make_model_thread(db_path, job_id, "S", [s2], run_id=run_id)
    choose_primary(db_path, job_id, t1)
    choose_secondary(db_path, job_id, t2)

    req = add_requirement(db_path, job_id, "req", "high", 0)
    add_judgment(db_path, req, u_plain, "match", score=0.99)  # highest score, but no thread
    add_judgment(db_path, req, u_secondary, "match", score=0.1)
    add_judgment(db_path, req, u_primary, "match", score=0.1)

    conn = connect(db_path)
    built = build_sections(conn, job_id)
    conn.close()
    section = next(s for s in built["sections"] if s.get("requirement_id") == req)
    unit_order = [p["unit_id"] for p in section["pointers"]]
    assert unit_order == [u_primary, u_secondary, u_plain]
    assert section["pointers"][0]["is_primary"] is True
    assert section["pointers"][1]["is_secondary"] is True
    assert section["pointers"][2]["is_primary"] is False and section["pointers"][2]["is_secondary"] is False


# --- pointer edit / reset ---

def test_pointer_edit_persists_and_reset_restores(client, db_path):
    job_id = setup_job_with_role(db_path)
    unit_id = add_unit(db_path, "unit")
    req = add_requirement(db_path, job_id, "req", "high", 0)
    add_judgment(db_path, req, unit_id, "match")

    before = client.get(f"/api/jobs/{job_id}/letter").json()
    section = next(s for s in before["sections"] if s["key"] == str(req))
    proposed = section["proposed_pointer_text"]
    assert section["pointers_edited"] is False

    client.patch(f"/api/jobs/{job_id}/letter/pointers/{req}", json={"text": "my own pointer line"})
    after_edit = client.get(f"/api/jobs/{job_id}/letter").json()
    section2 = next(s for s in after_edit["sections"] if s["key"] == str(req))
    assert section2["pointer_text"] == "my own pointer line"
    assert section2["pointers_edited"] is True

    client.patch(f"/api/jobs/{job_id}/letter/pointers/{req}", json={})
    after_reset = client.get(f"/api/jobs/{job_id}/letter").json()
    section3 = next(s for s in after_reset["sections"] if s["key"] == str(req))
    assert section3["pointer_text"] == proposed
    assert section3["pointers_edited"] is False


# --- section text autosave / reload ---

def test_section_text_autosaves_and_survives_reload(client, db_path):
    job_id = setup_job_with_role(db_path)
    client.patch(f"/api/jobs/{job_id}/letter/sections/open", json={"text": "Dear hiring manager,"})
    reloaded = client.get(f"/api/jobs/{job_id}/letter").json()
    open_section = next(s for s in reloaded["sections"] if s["key"] == "open")
    assert open_section["text"] == "Dear hiring manager,"
    assert open_section["word_count"] == 3


# --- Generate / skip / finish ---

def test_skipped_sections_excluded_from_generate(client, db_path):
    job_id = setup_job_with_role(db_path)
    client.patch(f"/api/jobs/{job_id}/letter/sections/open", json={"text": "Opening text", "skipped": False})
    client.patch(f"/api/jobs/{job_id}/letter/sections/close", json={"text": "Closing text", "skipped": True})

    resp = client.post(f"/api/jobs/{job_id}/letter/generate").json()
    assert "Opening text" in resp["assembled_text"]
    assert "Closing text" not in resp["assembled_text"]


def test_generate_joins_in_order_without_modifying_text(client, db_path):
    job_id = setup_job_with_role(db_path)
    unit_id = add_unit(db_path, "unit")
    req = add_requirement(db_path, job_id, "req", "high", 0)
    add_judgment(db_path, req, unit_id, "match")

    client.patch(f"/api/jobs/{job_id}/letter", json={"greeting": "Dear team,"})
    client.patch(f"/api/jobs/{job_id}/letter/sections/open", json={"text": "OPEN"})
    client.patch(f"/api/jobs/{job_id}/letter/sections/{req}", json={"text": "MIDDLE"})
    client.patch(f"/api/jobs/{job_id}/letter/sections/close", json={"text": "CLOSE"})
    client.patch(f"/api/jobs/{job_id}/letter", json={"signoff": "Best, Me"})

    resp = client.post(f"/api/jobs/{job_id}/letter/generate").json()
    assert resp["assembled_text"] == "Dear team,\n\nOPEN\n\nMIDDLE\n\nCLOSE\n\nBest, Me"

    # The source section text itself must be untouched by Generate.
    reloaded = client.get(f"/api/jobs/{job_id}/letter").json()
    open_section = next(s for s in reloaded["sections"] if s["key"] == "open")
    assert open_section["text"] == "OPEN"


def test_default_greeting_uses_the_company_when_set(client, db_path):
    job_id = setup_job_with_role(db_path)
    client.patch(f"/api/jobs/{job_id}", json={"company": "Acme"})

    resp = client.get(f"/api/jobs/{job_id}/letter").json()

    assert resp["greeting"] == "Dear Acme hiring team"


def test_default_greeting_stays_empty_without_a_company(client, db_path):
    job_id = setup_job_with_role(db_path)

    resp = client.get(f"/api/jobs/{job_id}/letter").json()

    assert resp["greeting"] is None


def test_setting_company_after_the_letter_already_exists_does_not_change_greeting(client, db_path):
    job_id = setup_job_with_role(db_path)
    client.get(f"/api/jobs/{job_id}/letter")  # creates the letter row first, with no company set

    client.patch(f"/api/jobs/{job_id}", json={"company": "Acme"})
    resp = client.get(f"/api/jobs/{job_id}/letter").json()

    assert resp["greeting"] is None  # unchanged -- never overwrites an existing letter row


def test_user_can_still_edit_the_default_greeting(client, db_path):
    job_id = setup_job_with_role(db_path)
    client.patch(f"/api/jobs/{job_id}", json={"company": "Acme"})
    client.get(f"/api/jobs/{job_id}/letter")  # seeds "Dear Acme hiring team"

    resp = client.patch(f"/api/jobs/{job_id}/letter", json={"greeting": "Hi there,"}).json()

    assert resp["greeting"] == "Hi there,"


def test_new_letters_default_signoff_has_a_line_break_for_the_name(client, db_path):
    job_id = setup_job_with_role(db_path)

    resp = client.get(f"/api/jobs/{job_id}/letter").json()

    assert resp["signoff"] == "Thanking you,\n"
    assert "\n" in resp["signoff"]


def test_an_existing_saved_signoff_is_unchanged(client, db_path):
    job_id = setup_job_with_role(db_path)
    client.get(f"/api/jobs/{job_id}/letter")  # creates the letter row, seeding the default
    client.patch(f"/api/jobs/{job_id}/letter", json={"signoff": "Best,\nJane Doe"})

    # Re-fetching must not re-seed or otherwise touch the already-saved value.
    resp = client.get(f"/api/jobs/{job_id}/letter").json()

    assert resp["signoff"] == "Best,\nJane Doe"


def test_finish_sets_letter_and_job_flags(client, db_path):
    job_id = setup_job_with_role(db_path)
    client.post(f"/api/jobs/{job_id}/letter/generate")
    resp = client.post(f"/api/jobs/{job_id}/letter/finish").json()
    assert resp["finished"] is True

    conn = connect(db_path)
    job_row = conn.execute("SELECT finished_at FROM job WHERE id = ?", (job_id,)).fetchone()
    conn.close()
    assert job_row["finished_at"] is not None


def test_letter_wiped_on_jd_resubmit(client, mock_llm, db_path):
    job_id = setup_job_with_role(db_path)
    client.patch(f"/api/jobs/{job_id}/letter/sections/open", json={"text": "something"})
    conn = connect(db_path)
    conn.execute("UPDATE job SET jd_submitted_text = 'jd' WHERE id = ?", (job_id,))
    conn.commit()
    conn.close()

    import json as jsonlib
    mock_llm.queue("requirement_extract", jsonlib.dumps({"requirements": [{"text": "new req", "weight": "high"}]}))
    mock_llm.queue("judge_batch", "not valid json")
    resp = client.post(f"/api/jobs/{job_id}/submit-jd", json={"jd_text": "a different jd text"})
    assert resp.status_code == 200

    conn = connect(db_path)
    assert conn.execute("SELECT COUNT(*) AS n FROM letter WHERE job_id = ?", (job_id,)).fetchone()["n"] == 0
    conn.close()


def test_a_unit_with_two_judgment_rows_on_the_same_requirement_appears_once(db_path):
    """Regression: a unit shortlisted AND also manually attached to the
    same requirement gets two judgment rows -- the pointer list (and the
    matched-unit count used for ranking) must still only count it once.
    A duplicate key here crashed the whole writing view client-side."""
    job_id = setup_job_with_role(db_path)
    unit_id = add_unit(db_path, "unit with two judgment rows")
    req = add_requirement(db_path, job_id, "req", "high", 0)
    add_judgment(db_path, req, unit_id, "match", score=0.5)
    add_judgment(db_path, req, unit_id, "match", score=0.9)  # e.g. also manually attached

    conn = connect(db_path)
    built = build_sections(conn, job_id)
    conn.close()

    section = next(s for s in built["sections"] if s.get("requirement_id") == req)
    assert len(section["pointers"]) == 1
    assert section["pointers"][0]["unit_id"] == unit_id


# --- Opening/Close hints (§10 additions) -- display only, no model call ---

def test_opening_hint_includes_company_role_and_strongest_statement(client, db_path):
    job_id = setup_job_with_role(db_path)
    client.patch(f"/api/jobs/{job_id}", json={"company": "Acme", "role_title": "Engineer"})

    s_weak, _, _ = add_pair_with_statement(db_path, job_id, "weaker statement")
    s_strong, u_strong_a, _ = add_pair_with_statement(db_path, job_id, "stronger statement")
    conn = connect(db_path)
    conn.execute("UPDATE pair SET score = 0.2 WHERE id = (SELECT pair_id FROM statement WHERE id = ?)", (s_weak,))
    conn.execute("UPDATE pair SET score = 0.9 WHERE id = (SELECT pair_id FROM statement WHERE id = ?)", (s_strong,))
    conn.commit()
    conn.close()

    thread_id = make_model_thread(db_path, job_id, "Idea", [s_weak, s_strong])
    choose_primary(db_path, job_id, thread_id)

    conn = connect(db_path)
    conn.execute(
        "INSERT INTO thread_unit (thread_id, unit_id, model_verdict, quote) VALUES (?, ?, 'yes', 'the verified quote')",
        (thread_id, u_strong_a),
    )
    conn.commit()
    conn.close()

    hint = client.get(f"/api/jobs/{job_id}/letter").json()["opening_hint"]

    assert hint["company"] == "Acme"
    assert hint["role_title"] == "Engineer"
    assert hint["statement_text"] == "stronger statement"  # higher pair score wins, not insertion order
    assert hint["statement_quote"] == "the verified quote"
    assert hint["question"] == "Which one moment from this thread would make them want to read on?"


def test_opening_hint_omits_parts_with_no_data(client, db_path):
    job_id = setup_job_with_role(db_path)

    hint = client.get(f"/api/jobs/{job_id}/letter").json()["opening_hint"]

    assert hint["company"] is None
    assert hint["role_title"] is None
    assert hint["statement_text"] is None
    assert hint["statement_quote"] is None
    assert hint["question"] == "Which one moment from this thread would make them want to read on?"


def test_close_hint_lists_uncovered_requirements_sorted_by_weight(client, db_path):
    job_id = setup_job_with_role(db_path)
    unit_id = add_unit(db_path, "unit")
    req_low = add_requirement(db_path, job_id, "low gap", "low", 0)
    req_high = add_requirement(db_path, job_id, "high gap", "high", 1)
    req_matched = add_requirement(db_path, job_id, "matched req", "high", 2)
    add_judgment(db_path, req_matched, unit_id, "match")  # covered -- not a gap
    req_weak = add_requirement(db_path, job_id, "weak req", "high", 3)
    add_judgment(db_path, req_weak, unit_id, "weak")  # weak, not an uncovered gap

    hint = client.get(f"/api/jobs/{job_id}/letter").json()["close_hint"]

    assert [r["id"] for r in hint["uncovered"]] == [req_high, req_low]
    assert [r["text"] for r in hint["uncovered"]] == ["high gap", "low gap"]
    assert hint["question"] == "What do you want them to do after reading this, and why this company?"


def test_close_hint_empty_when_nothing_uncovered(client, db_path):
    job_id = setup_job_with_role(db_path)

    hint = client.get(f"/api/jobs/{job_id}/letter").json()["close_hint"]

    assert hint["uncovered"] == []
    assert hint["question"] == "What do you want them to do after reading this, and why this company?"
