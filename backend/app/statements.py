"""Milestone 3: fresh-vs-autofill
choice and the per-pair "what do these two have in common" answers. No
model call anywhere, no check on what the user writes."""

import sqlite3


def reset_to_fresh(conn: sqlite3.Connection, job_id: int) -> None:
    """"Start fresh": every pair for this job goes back to unanswered,
    undoing any previous autofill (confirmed or not)."""
    conn.execute(
        "UPDATE statement SET status = 'unanswered', text = NULL, autofilled_from_job_id = NULL, "
        "confirmed = 1, updated_at = datetime('now') "
        "WHERE pair_id IN (SELECT id FROM pair WHERE job_id = ?)",
        (job_id,),
    )
    conn.commit()


def autofill_statements(conn: sqlite3.Connection, job_id: int) -> int:
    """For each of this job's pairs, find the most recently written (or
    explicitly "none") statement on the same two units in any OTHER job,
    and copy it in as an unconfirmed autofilled statement. Pairs with no
    such earlier statement stay unanswered. Copies, not links -- later
    edits to the source job's statement never reach this copy. Returns
    how many pairs got autofilled."""
    pairs = conn.execute("SELECT id, unit_a_id, unit_b_id FROM pair WHERE job_id = ?", (job_id,)).fetchall()
    filled = 0
    for pair in pairs:
        source = conn.execute(
            "SELECT s.status, s.text, p.job_id AS source_job_id FROM statement s "
            "JOIN pair p ON p.id = s.pair_id "
            "WHERE p.unit_a_id = ? AND p.unit_b_id = ? AND p.job_id != ? AND s.status != 'unanswered' "
            "ORDER BY s.updated_at DESC LIMIT 1",
            (pair["unit_a_id"], pair["unit_b_id"], job_id),
        ).fetchone()
        if source is None:
            continue
        conn.execute(
            "UPDATE statement SET status = ?, text = ?, autofilled_from_job_id = ?, confirmed = 0, "
            "updated_at = datetime('now') WHERE pair_id = ?",
            (source["status"], source["text"], source["source_job_id"], pair["id"]),
        )
        filled += 1
    conn.commit()
    return filled


def confirm_all(conn: sqlite3.Connection, job_id: int) -> None:
    """"Confirm all": every autofilled statement for this job counts as
    written from here on, without the user having edited it by hand. The
    "autofilled from" chip is shown "until the user edits or confirms" it
    (§6), so confirming clears the marker same as an edit would."""
    conn.execute(
        "UPDATE statement SET confirmed = 1, autofilled_from_job_id = NULL, updated_at = datetime('now') "
        "WHERE pair_id IN (SELECT id FROM pair WHERE job_id = ?) AND confirmed = 0",
        (job_id,),
    )
    conn.commit()
