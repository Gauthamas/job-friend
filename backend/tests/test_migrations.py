import sqlite3

import pytest


def test_migration_creates_all_tables(db):
    tables = {
        row["name"]
        for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    expected = {
        "profile", "inventory", "role", "unit", "unit_embedding",
        "flow", "job", "requirement", "judgment", "schema_migrations",
    }
    assert expected <= tables


def test_migration_is_idempotent(db):
    from app.db import migrate

    count_before = db.execute("SELECT COUNT(*) AS c FROM schema_migrations").fetchone()["c"]
    migrate(db)  # running again should not error or duplicate rows
    count_after = db.execute("SELECT COUNT(*) AS c FROM schema_migrations").fetchone()["c"]
    assert count_after == count_before


def test_foreign_key_enforced(db):
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(
            "INSERT INTO inventory (profile_id, name) VALUES (999, 'x')"
        )
        db.commit()


def test_unit_source_check_constraint(db):
    db.execute("INSERT INTO profile (name) VALUES ('p')")
    db.execute("INSERT INTO inventory (profile_id, name) VALUES (1, 'inv')")
    db.execute(
        "INSERT INTO role (inventory_id, company, title, sort_order) VALUES (1, 'c', 't', 0)"
    )
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(
            "INSERT INTO unit (role_id, text, source, sort_order) VALUES (1, 'x', 'bogus', 0)"
        )
        db.commit()


def test_judgment_verdict_check_constraint(db):
    db.execute("INSERT INTO profile (name) VALUES ('p')")
    db.execute("INSERT INTO inventory (profile_id, name) VALUES (1, 'inv')")
    db.execute(
        "INSERT INTO role (inventory_id, company, title, sort_order) VALUES (1, 'c', 't', 0)"
    )
    db.execute(
        "INSERT INTO unit (role_id, text, source, sort_order) VALUES (1, 'x', 'manual', 0)"
    )
    db.execute("INSERT INTO flow (profile_id, name, inventory_id) VALUES (1, 'f', 1)")
    db.execute("INSERT INTO job (flow_id, title, jd_text) VALUES (1, 't', 'jd')")
    db.execute(
        "INSERT INTO requirement (job_id, text, weight, source, status, sort_order) "
        "VALUES (1, 'req', 'high', 'user', 'pending', 0)"
    )
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(
            "INSERT INTO judgment (requirement_id, unit_id, model_verdict) "
            "VALUES (1, 1, 'bogus')"
        )
        db.commit()


@pytest.mark.parametrize("table", ["profile", "inventory", "role", "unit", "requirement", "judgment"])
def test_ids_are_never_reused_after_deleting_the_highest_row(db, table):
    # Without AUTOINCREMENT, deleting the highest-id row in a table makes
    # SQLite reissue that id on the next insert — dangerous once other rows
    # (e.g. a judgment) hold onto an id by foreign key after a soft delete.
    db.execute("INSERT INTO profile (name) VALUES ('p1')")
    db.execute("INSERT INTO profile (name) VALUES ('p2')")
    db.execute("INSERT INTO inventory (profile_id, name) VALUES (1, 'inv1')")
    db.execute("INSERT INTO inventory (profile_id, name) VALUES (1, 'inv2')")
    db.execute("INSERT INTO role (inventory_id, company, title, sort_order) VALUES (1, 'c1', 't1', 0)")
    db.execute("INSERT INTO role (inventory_id, company, title, sort_order) VALUES (1, 'c2', 't2', 1)")
    db.execute("INSERT INTO unit (role_id, text, source, sort_order) VALUES (1, 'u1', 'manual', 0)")
    db.execute("INSERT INTO unit (role_id, text, source, sort_order) VALUES (1, 'u2', 'manual', 1)")
    db.execute("INSERT INTO flow (profile_id, name, inventory_id) VALUES (1, 'f', 1)")
    db.execute("INSERT INTO job (flow_id, title, jd_text) VALUES (1, 't', 'jd')")
    db.execute(
        "INSERT INTO requirement (job_id, text, weight, source, status, sort_order) "
        "VALUES (1, 'r1', 'high', 'user', 'pending', 0)"
    )
    db.execute(
        "INSERT INTO requirement (job_id, text, weight, source, status, sort_order) "
        "VALUES (1, 'r2', 'high', 'user', 'pending', 1)"
    )
    db.execute(
        "INSERT INTO judgment (requirement_id, unit_id, model_verdict) VALUES (1, 1, 'match')"
    )
    db.execute(
        "INSERT INTO judgment (requirement_id, unit_id, model_verdict) VALUES (1, 1, 'match')"
    )
    db.commit()

    max_id_before = db.execute(f"SELECT MAX(id) AS m FROM {table}").fetchone()["m"]
    db.execute(f"DELETE FROM {table} WHERE id = ?", (max_id_before,))
    db.commit()

    # Re-insert the same kind of row and confirm the freed id isn't reused.
    if table == "profile":
        db.execute("INSERT INTO profile (name) VALUES ('p3')")
    elif table == "inventory":
        db.execute("INSERT INTO inventory (profile_id, name) VALUES (1, 'inv3')")
    elif table == "role":
        db.execute("INSERT INTO role (inventory_id, company, title, sort_order) VALUES (1, 'c3', 't3', 2)")
    elif table == "unit":
        db.execute("INSERT INTO unit (role_id, text, source, sort_order) VALUES (1, 'u3', 'manual', 2)")
    elif table == "requirement":
        db.execute(
            "INSERT INTO requirement (job_id, text, weight, source, status, sort_order) "
            "VALUES (1, 'r3', 'high', 'user', 'pending', 2)"
        )
    elif table == "judgment":
        db.execute(
            "INSERT INTO judgment (requirement_id, unit_id, model_verdict) VALUES (1, 1, 'match')"
        )
    db.commit()

    new_max_id = db.execute(f"SELECT MAX(id) AS m FROM {table}").fetchone()["m"]
    assert new_max_id > max_id_before


def test_unit_deleted_defaults_to_zero(db):
    db.execute("INSERT INTO profile (name) VALUES ('p')")
    db.execute("INSERT INTO inventory (profile_id, name) VALUES (1, 'inv')")
    db.execute("INSERT INTO role (inventory_id, company, title, sort_order) VALUES (1, 'c', 't', 0)")
    db.execute("INSERT INTO unit (role_id, text, source, sort_order) VALUES (1, 'x', 'manual', 0)")
    db.commit()
    row = db.execute("SELECT deleted, merged_into FROM unit WHERE id = 1").fetchone()
    assert row["deleted"] == 0
    assert row["merged_into"] is None


def test_unit_soft_delete_and_merge_tracking(db):
    db.execute("INSERT INTO profile (name) VALUES ('p')")
    db.execute("INSERT INTO inventory (profile_id, name) VALUES (1, 'inv')")
    db.execute("INSERT INTO role (inventory_id, company, title, sort_order) VALUES (1, 'c', 't', 0)")
    db.execute("INSERT INTO unit (role_id, text, source, sort_order) VALUES (1, 'survivor', 'manual', 0)")
    db.execute("INSERT INTO unit (role_id, text, source, sort_order) VALUES (1, 'loser', 'manual', 1)")
    db.commit()

    survivor_id, loser_id = 1, 2
    db.execute(
        "UPDATE unit SET deleted = 1, merged_into = ? WHERE id = ?", (survivor_id, loser_id)
    )
    db.commit()

    loser = db.execute("SELECT deleted, merged_into FROM unit WHERE id = ?", (loser_id,)).fetchone()
    assert loser["deleted"] == 1
    assert loser["merged_into"] == survivor_id


def test_unit_merged_into_rejects_nonexistent_unit(db):
    db.execute("INSERT INTO profile (name) VALUES ('p')")
    db.execute("INSERT INTO inventory (profile_id, name) VALUES (1, 'inv')")
    db.execute("INSERT INTO role (inventory_id, company, title, sort_order) VALUES (1, 'c', 't', 0)")
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(
            "INSERT INTO unit (role_id, text, source, sort_order, merged_into) "
            "VALUES (1, 'x', 'manual', 0, 999)"
        )
        db.commit()


def test_unit_embedding_accepts_skills_field(db):
    db.execute("INSERT INTO profile (name) VALUES ('p')")
    db.execute("INSERT INTO inventory (profile_id, name) VALUES (1, 'inv')")
    db.execute("INSERT INTO role (inventory_id, company, title, sort_order) VALUES (1, 'c', 't', 0)")
    db.execute("INSERT INTO unit (role_id, text, source, sort_order) VALUES (1, 'x', 'manual', 0)")
    db.execute(
        "INSERT INTO unit_embedding (unit_id, field, model, vector) VALUES (1, 'skills', 'm1', x'00')"
    )
    db.commit()
    row = db.execute("SELECT field FROM unit_embedding WHERE unit_id = 1").fetchone()
    assert row["field"] == "skills"


def test_unit_embedding_still_rejects_unknown_field(db):
    db.execute("INSERT INTO profile (name) VALUES ('p')")
    db.execute("INSERT INTO inventory (profile_id, name) VALUES (1, 'inv')")
    db.execute("INSERT INTO role (inventory_id, company, title, sort_order) VALUES (1, 'c', 't', 0)")
    db.execute("INSERT INTO unit (role_id, text, source, sort_order) VALUES (1, 'x', 'manual', 0)")
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(
            "INSERT INTO unit_embedding (unit_id, field, model, vector) VALUES (1, 'bogus', 'm1', x'00')"
        )
        db.commit()


def test_unit_embedding_unique_per_unit_field_model(db):
    db.execute("INSERT INTO profile (name) VALUES ('p')")
    db.execute("INSERT INTO inventory (profile_id, name) VALUES (1, 'inv')")
    db.execute(
        "INSERT INTO role (inventory_id, company, title, sort_order) VALUES (1, 'c', 't', 0)"
    )
    db.execute(
        "INSERT INTO unit (role_id, text, source, sort_order) VALUES (1, 'x', 'manual', 0)"
    )
    db.execute(
        "INSERT INTO unit_embedding (unit_id, field, model, vector) VALUES (1, 'text', 'm1', x'00')"
    )
    db.commit()
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(
            "INSERT INTO unit_embedding (unit_id, field, model, vector) VALUES (1, 'text', 'm1', x'01')"
        )
        db.commit()
