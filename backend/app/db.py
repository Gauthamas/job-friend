import shutil
import sqlite3
from datetime import datetime
from pathlib import Path

MIGRATIONS_DIR = Path(__file__).parent / "migrations"


def connect(db_path: str) -> sqlite3.Connection:
    # check_same_thread=False: FastAPI resolves a yield-dependency's setup
    # and the route body as two separate threadpool calls, which can land on
    # different worker threads under concurrent requests -- a connection
    # created in one and used in the other would otherwise raise
    # sqlite3.ProgrammingError. Each connection is still only ever used by
    # one request at a time, never by two threads simultaneously, so this
    # is safe.
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.row_factory = sqlite3.Row
    return conn


def _pending_migrations(conn: sqlite3.Connection) -> list[Path]:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version TEXT PRIMARY KEY,
            applied_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
        """
    )
    applied = {row["version"] for row in conn.execute("SELECT version FROM schema_migrations")}
    return [path for path in sorted(MIGRATIONS_DIR.glob("*.sql")) if path.name not in applied]


def _backup_db_file(db_path: str) -> None:
    """Copies the live db file aside before running any pending migration --
    a migration that rebuilds tables (DROP TABLE/RENAME) has no automatic
    undo, so this is the safety net if one goes wrong partway through."""
    path = Path(db_path)
    if not path.is_file():
        return  # nothing to back up (fresh/in-memory db)
    stamp = datetime.now().strftime("%Y%m%d%H%M%S")
    backup_path = path.with_name(f"{path.name}.bak-{stamp}")
    shutil.copy2(path, backup_path)


def migrate(conn: sqlite3.Connection, db_path: str | None = None) -> None:
    pending = _pending_migrations(conn)
    if not pending:
        return
    if db_path is not None:
        _backup_db_file(db_path)

    for path in pending:
        conn.executescript(path.read_text())
        conn.execute("INSERT INTO schema_migrations (version) VALUES (?)", (path.name,))
        conn.commit()


def init_db(db_path: str) -> sqlite3.Connection:
    conn = connect(db_path)
    migrate(conn, db_path)
    return conn
