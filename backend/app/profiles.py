import sqlite3

DEFAULT_PROFILE_NAME = "Default"


def get_or_create_default_profile(conn: sqlite3.Connection) -> int:
    row = conn.execute(
        "SELECT id FROM profile WHERE name = ?", (DEFAULT_PROFILE_NAME,)
    ).fetchone()
    if row:
        return row["id"]

    cursor = conn.execute(
        "INSERT INTO profile (name) VALUES (?)", (DEFAULT_PROFILE_NAME,)
    )
    conn.commit()
    return cursor.lastrowid
