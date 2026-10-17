"""Milestone 7 part A: settings persistence. Defaults stay in code; a row
in app_setting overrides a key at startup and via PATCH /api/settings; a
delete restores the default."""

from app.config import settings
from app.db import connect
from app.settings_store import DEFAULTS, InvalidSettingValue, load_settings_from_db, reset_setting, set_setting


def test_set_then_reload_from_db_survives(db_path):
    conn = connect(db_path)
    set_setting(conn, "min_support", 7)
    conn.close()

    settings.min_support = DEFAULTS["min_support"]  # simulate a fresh process before reload
    conn = connect(db_path)
    load_settings_from_db(conn)
    conn.close()

    assert settings.min_support == 7
    settings.min_support = DEFAULTS["min_support"]


def test_invalid_value_is_rejected(db_path):
    conn = connect(db_path)
    try:
        set_setting(conn, "min_support", -1)
        assert False, "expected InvalidSettingValue"
    except InvalidSettingValue:
        pass
    conn.close()


def test_invalid_stored_value_falls_back_to_default_on_load(db_path):
    conn = connect(db_path)
    conn.execute(
        "INSERT INTO app_setting (key, value_json) VALUES ('min_support', '-5')"
    )
    conn.commit()
    load_settings_from_db(conn)
    conn.close()

    assert settings.min_support == DEFAULTS["min_support"]


def test_unknown_stored_key_is_ignored(db_path):
    conn = connect(db_path)
    conn.execute("INSERT INTO app_setting (key, value_json) VALUES ('not_a_real_setting', '1')")
    conn.commit()
    load_settings_from_db(conn)  # must not raise
    conn.close()


def test_reset_restores_default(db_path):
    conn = connect(db_path)
    set_setting(conn, "n_threads", 9)
    assert settings.n_threads == 9
    reset_setting(conn, "n_threads")
    conn.close()

    assert settings.n_threads == DEFAULTS["n_threads"]


def test_pair_n_accepts_none(db_path):
    conn = connect(db_path)
    set_setting(conn, "pair_n", 5)
    assert settings.pair_n == 5
    set_setting(conn, "pair_n", None)
    conn.close()

    assert settings.pair_n is None
    conn = connect(db_path)
    reset_setting(conn, "pair_n")
    conn.close()


def test_get_and_patch_endpoints(client, db_path):
    resp = client.get("/api/settings")
    assert resp.status_code == 200
    body = resp.json()
    keys = {s["key"] for s in body["settings"]}
    assert "min_support" in keys
    assert "matched_sections" in keys

    resp = client.patch("/api/settings", json={"values": {"min_support": 5}})
    assert resp.status_code == 200
    updated = next(s for s in resp.json()["settings"] if s["key"] == "min_support")
    assert updated["value"] == 5
    assert updated["is_default"] is False

    resp = client.patch("/api/settings", json={"values": {"min_support": -1}})
    assert resp.status_code == 400

    resp = client.delete("/api/settings/min_support")
    assert resp.status_code == 200
    restored = next(s for s in resp.json()["settings"] if s["key"] == "min_support")
    assert restored["is_default"] is True


def test_legacy_matched_sections_alias_still_works(client, db_path):
    resp = client.patch("/api/settings/matched-sections", json={"value": 4})
    assert resp.status_code == 200
    assert resp.json()["value"] == 4
    assert client.get("/api/settings/matched-sections").json()["value"] == 4
