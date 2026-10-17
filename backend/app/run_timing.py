import sqlite3
from typing import Optional


def record_run_timing(
    conn: sqlite3.Connection,
    phase: str,
    model: str,
    thinking: bool,
    prompt_version: str,
    items: int,
    seconds_total: float,
    mode: Optional[str] = None,
    batch_size: Optional[int] = None,
    seconds_to_first_result: Optional[float] = None,
) -> None:
    conn.execute(
        "INSERT INTO run_timing (phase, mode, model, thinking, prompt_version, batch_size, items, "
        "seconds_to_first_result, seconds_total) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            phase, mode, model, int(thinking), prompt_version, batch_size, items,
            seconds_to_first_result, seconds_total,
        ),
    )
    conn.commit()


def average_seconds(conn: sqlite3.Connection, phase: str, model: Optional[str] = None, limit: int = 20) -> dict:
    """Recent-average timing for a phase, across up to `limit` of the most
    recent matching rows. Filtered by model when given (estimates swing a
    lot across models), but deliberately NOT by mode/thinking/prompt_version
    -- filtering on everything would make the estimate disappear the moment
    any of those changes, which defeats the point of a rough "typically
    ~X" figure. Returns {} if there's no history yet."""
    if model:
        rows = conn.execute(
            "SELECT seconds_total, seconds_to_first_result FROM run_timing "
            "WHERE phase = ? AND model = ? ORDER BY id DESC LIMIT ?",
            (phase, model, limit),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT seconds_total, seconds_to_first_result FROM run_timing WHERE phase = ? "
            "ORDER BY id DESC LIMIT ?",
            (phase, limit),
        ).fetchall()
    if not rows:
        return {}

    totals = [r["seconds_total"] for r in rows]
    first_results = [r["seconds_to_first_result"] for r in rows if r["seconds_to_first_result"] is not None]
    return {
        "avg_seconds_total": sum(totals) / len(totals),
        "avg_seconds_to_first_result": (sum(first_results) / len(first_results)) if first_results else None,
        "sample_size": len(rows),
    }
