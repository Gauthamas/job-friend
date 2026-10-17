"""Milestone 6: the writing view. Everything
here is mechanical -- no model call builds, edits, or suggests any letter
text. Pointers are proposed as plain strings (one per line, like the
reference page's textarea), never a generated sentence."""

import json
import re
import sqlite3
from typing import Optional

from app.config import settings
from app.thread_ranking import get_choice, thread_unit_ids
from app.verdicts import effective_verdict

WEIGHT_ORDER = {"high": 0, "medium": 1, "low": 2}
MAX_POINTER_WORDS = 10


#  No name is stored anywhere in this app today (profile.name is always
# the literal string "Default"; there's no settings key for a person's
# name either) -- so the second line stays empty for the user to type,
# per the default below.
DEFAULT_SIGNOFF = "Thanking you,\n"


def get_or_create_letter(conn: sqlite3.Connection, job_id: int) -> sqlite3.Row:
    """On first creation, seeds a default greeting only when the job has a
    company set ("Dear <company> hiring team") -- otherwise greeting stays
    NULL, exactly as before this existed -- and a default two-line sign-off
    (DEFAULT_SIGNOFF). The user can edit or clear either like any other
    field; this never overwrites an already-created letter row."""
    row = conn.execute("SELECT * FROM letter WHERE job_id = ?", (job_id,)).fetchone()
    if row:
        return row
    job = conn.execute("SELECT company FROM job WHERE id = ?", (job_id,)).fetchone()
    default_greeting = f"Dear {job['company']} hiring team" if job and job["company"] else None
    conn.execute(
        "INSERT INTO letter (job_id, sections_json, greeting, signoff) VALUES (?, '{}', ?, ?)",
        (job_id, default_greeting, DEFAULT_SIGNOFF),
    )
    conn.commit()
    return conn.execute("SELECT * FROM letter WHERE job_id = ?", (job_id,)).fetchone()


def _sections(letter_row: sqlite3.Row) -> dict:
    try:
        return json.loads(letter_row["sections_json"]) or {}
    except (json.JSONDecodeError, TypeError):
        return {}


def _section_entry(sections: dict, key: str) -> dict:
    entry = sections.get(str(key)) or {}
    return {
        "text": entry.get("text") or "",
        "pointers_edited": entry.get("pointers_edited"),
        "skipped": bool(entry.get("skipped", False)),
    }


def save_section(conn: sqlite3.Connection, job_id: int, key: str, **updates) -> None:
    letter = get_or_create_letter(conn, job_id)
    sections = _sections(letter)
    entry = _section_entry(sections, key)
    entry.update(updates)
    sections[str(key)] = entry
    conn.execute(
        "UPDATE letter SET sections_json = ?, updated_at = datetime('now') WHERE job_id = ?",
        (json.dumps(sections), job_id),
    )
    conn.commit()


def primary_secondary_unit_ids(conn: sqlite3.Connection, job_id: int) -> tuple[set[int], set[int]]:
    primary = get_choice(conn, job_id, "primary")
    secondary = get_choice(conn, job_id, "secondary")
    primary_ids = thread_unit_ids(conn, primary["thread_id"]) if primary else set()
    secondary_ids = thread_unit_ids(conn, secondary["thread_id"]) if secondary else set()
    return primary_ids, secondary_ids


def _extract_quote(why: Optional[str]) -> Optional[str]:
    """judgment.why is composed as '"<quote>" — Shows: ... Needs: ...' --
    pull the leading quoted span back out, if any."""
    if not why or not why.startswith('"'):
        return None
    m = re.match(r'^"([^"]*)"', why)
    return m.group(1) if m and m.group(1) else None


def _first_words(text: str, max_words: int = 8) -> str:
    words = text.split()
    if len(words) <= max_words:
        return text
    return " ".join(words[:max_words]) + "\u2026"


def _pointer_line(unit_row: sqlite3.Row, verdict: str, why: Optional[str]) -> str:
    """"<unit first words> (<verdict>)" plus the quote if any -- nothing
    generated (§10 point 7)."""
    line = f"{_first_words(unit_row['text'], MAX_POINTER_WORDS)} ({verdict})"
    quote = _extract_quote(why)
    if quote:
        line += f': "{quote}"'
    return line


def requirement_judgments(conn: sqlite3.Connection, requirement_id: int) -> list[sqlite3.Row]:
    return conn.execute("SELECT * FROM judgment WHERE requirement_id = ?", (requirement_id,)).fetchall()


def _ordered_unit_judgments(
    judgments: list[sqlite3.Row], verdict: str, primary_ids: set[int], secondary_ids: set[int],
) -> list[sqlite3.Row]:
    """§10 point 3: primary-thread units, then secondary-thread units,
    then by the stored requirement-to-unit score (desc), then unit id.
    One row per unit -- a unit can have more than one judgment row on the
    same requirement (e.g. shortlisted and then also manually attached),
    which would otherwise produce a duplicate pointer for the same unit."""
    matching = [j for j in judgments if effective_verdict(j) == verdict]
    best_by_unit: dict[int, sqlite3.Row] = {}
    for j in matching:
        existing = best_by_unit.get(j["unit_id"])
        if existing is None or (j["score"] or 0.0) > (existing["score"] or 0.0):
            best_by_unit[j["unit_id"]] = j

    def sort_key(j: sqlite3.Row):
        unit_id = j["unit_id"]
        return (
            0 if unit_id in primary_ids else 1,
            0 if unit_id in secondary_ids else 1,
            -(j["score"] or 0.0),
            unit_id,
        )

    return sorted(best_by_unit.values(), key=sort_key)


def pointers_for(
    conn: sqlite3.Connection, judgments: list[sqlite3.Row], verdict: str, primary_ids: set[int], secondary_ids: set[int],
) -> list[dict]:
    ordered = _ordered_unit_judgments(judgments, verdict, primary_ids, secondary_ids)
    out = []
    for j in ordered:
        unit_row = conn.execute("SELECT * FROM unit WHERE id = ?", (j["unit_id"],)).fetchone()
        out.append({
            "unit_id": j["unit_id"],
            "verdict": verdict,
            "quote": _extract_quote(j["why"]),
            "line": _pointer_line(unit_row, verdict, j["why"]),
            "is_primary": j["unit_id"] in primary_ids,
            "is_secondary": j["unit_id"] in secondary_ids,
        })
    return out


def proposed_pointer_text(pointers: list[dict]) -> str:
    return "\n".join(p["line"] for p in pointers)


def rank_matched_requirements(conn: sqlite3.Connection, job_id: int) -> list[sqlite3.Row]:
    """§10 point 2: requirements with an effective match on >=1 unit,
    ranked by (weight, covered by primary thread, covered by secondary
    thread, matched unit count desc, position)."""
    primary_ids, secondary_ids = primary_secondary_unit_ids(conn, job_id)
    requirements = conn.execute(
        "SELECT * FROM requirement WHERE job_id = ? AND deleted = 0 ORDER BY sort_order", (job_id,)
    ).fetchall()

    scored = []
    for req in requirements:
        judgments = requirement_judgments(conn, req["id"])
        matched = [j for j in judgments if effective_verdict(j) == "match"]
        if not matched:
            continue
        matched_unit_ids = {j["unit_id"] for j in matched}
        covered_primary = bool(matched_unit_ids & primary_ids)
        covered_secondary = bool(matched_unit_ids & secondary_ids)
        # Distinct units, not judgment rows -- a unit can have more than
        # one judgment row on the same requirement (see
        # _ordered_unit_judgments), which would otherwise inflate this.
        scored.append((req, len(matched_unit_ids), covered_primary, covered_secondary))

    scored.sort(key=lambda t: (
        WEIGHT_ORDER.get(t[0]["weight"], 99), 0 if t[2] else 1, 0 if t[3] else 1, -t[1], t[0]["sort_order"],
    ))
    return [t[0] for t in scored]


def weak_requirements(conn: sqlite3.Connection, job_id: int) -> list[sqlite3.Row]:
    """§10 point 4: best verdict is weak, no match anywhere."""
    requirements = conn.execute(
        "SELECT * FROM requirement WHERE job_id = ? AND deleted = 0 ORDER BY sort_order", (job_id,)
    ).fetchall()
    out = []
    for req in requirements:
        judgments = requirement_judgments(conn, req["id"])
        effective = [effective_verdict(j) for j in judgments]
        if "match" not in effective and "weak" in effective:
            out.append(req)
    return out


OPENING_HINT_QUESTION = "Which one moment from this thread would make them want to read on?"
CLOSE_HINT_QUESTION = "What do you want them to do after reading this, and why this company?"


def _strongest_primary_statement(conn: sqlite3.Connection, job_id: int) -> tuple[Optional[str], Optional[str]]:
    """(statement_text, quote) for the primary thread's single strongest
    supporting statement -- "strongest" by its pair's stored similarity
    score, the one numeric strength signal already computed for pairs
    (no model call here, no new ranking). None/None if there's no
    primary thread, or it has no statement with real text."""
    primary = get_choice(conn, job_id, "primary")
    if not primary:
        return None, None
    row = conn.execute(
        "SELECT s.text AS text, p.unit_a_id AS unit_a_id, p.unit_b_id AS unit_b_id "
        "FROM thread_statement ts "
        "JOIN statement s ON s.id = ts.statement_id "
        "JOIN pair p ON p.id = s.pair_id "
        "WHERE ts.thread_id = ? AND s.text IS NOT NULL AND s.text != '' "
        "ORDER BY p.score DESC, ts.id "
        "LIMIT 1",
        (primary["thread_id"],),
    ).fetchone()
    if not row:
        return None, None
    quote_row = conn.execute(
        "SELECT quote FROM thread_unit WHERE thread_id = ? AND unit_id IN (?, ?) AND quote IS NOT NULL "
        "ORDER BY unit_id LIMIT 1",
        (primary["thread_id"], row["unit_a_id"], row["unit_b_id"]),
    ).fetchone()
    return row["text"], (quote_row["quote"] if quote_row else None)


def opening_hint(conn: sqlite3.Connection, job_id: int) -> dict:
    """§10's Opening hint box: display-only context for the user, never
    inserted into the section text. Everything here is the user's own
    stored data or fixed question text -- nothing generated."""
    job = conn.execute("SELECT company, role_title FROM job WHERE id = ?", (job_id,)).fetchone()
    statement_text, statement_quote = _strongest_primary_statement(conn, job_id)
    return {
        "company": job["company"] if job else None,
        "role_title": job["role_title"] if job else None,
        "statement_text": statement_text,
        "statement_quote": statement_quote,
        "question": OPENING_HINT_QUESTION,
    }


def close_hint(conn: sqlite3.Connection, job_id: int) -> dict:
    """§10's Close hint box: requirements no unit covers at all
    (gap_requirements), sorted high weight first."""
    uncovered = sorted(gap_requirements(conn, job_id), key=lambda r: WEIGHT_ORDER.get(r["weight"], 99))
    return {
        "uncovered": [{"id": r["id"], "text": r["text"], "weight": r["weight"]} for r in uncovered],
        "question": CLOSE_HINT_QUESTION,
    }


def gap_requirements(conn: sqlite3.Connection, job_id: int) -> list[sqlite3.Row]:
    """§10 point 5: no match, no weak -- a visible gap."""
    requirements = conn.execute(
        "SELECT * FROM requirement WHERE job_id = ? AND deleted = 0 ORDER BY sort_order", (job_id,)
    ).fetchall()
    out = []
    for req in requirements:
        judgments = requirement_judgments(conn, req["id"])
        effective = [effective_verdict(j) for j in judgments]
        if "match" not in effective and "weak" not in effective:
            out.append(req)
    return out


def build_sections(conn: sqlite3.Connection, job_id: int) -> dict:
    """Everything the writing view needs: section order, per-section
    jd/pointer/gap data, and the matched-requirement count for the
    "showing X of Y" header (§10 point 2)."""
    letter = get_or_create_letter(conn, job_id)
    sections_stored = _sections(letter)
    primary_ids, secondary_ids = primary_secondary_unit_ids(conn, job_id)

    all_matched = rank_matched_requirements(conn, job_id)
    shown_matched = all_matched[: settings.matched_sections]
    weak_reqs = weak_requirements(conn, job_id)
    gap_reqs = gap_requirements(conn, job_id)

    def req_section(req: sqlite3.Row, verdict: str) -> dict:
        judgments = requirement_judgments(conn, req["id"])
        pointers = pointers_for(conn, judgments, verdict, primary_ids, secondary_ids)
        entry = _section_entry(sections_stored, req["id"])
        proposed = proposed_pointer_text(pointers)
        return {
            "key": str(req["id"]),
            "kind": "requirement",
            "requirement_id": req["id"],
            "requirement_text": req["text"],
            "weight": req["weight"],
            "verdict": verdict,
            "pointers": pointers,
            "proposed_pointer_text": proposed,
            "pointer_text": entry["pointers_edited"] if entry["pointers_edited"] is not None else proposed,
            "pointers_edited": entry["pointers_edited"] is not None,
            "text": entry["text"],
            "skipped": entry["skipped"],
        }

    sections = []
    open_entry = _section_entry(sections_stored, "open")
    sections.append({"key": "open", "kind": "plain", "text": open_entry["text"], "skipped": open_entry["skipped"]})

    for req in shown_matched:
        sections.append(req_section(req, "match"))

    if weak_reqs:
        # §10 point 4: "for each [requirement], the posting line and its
        # weak units as pointers" -- grouped per requirement for display.
        # The SAME unit can legitimately be a weak pointer on more than
        # one requirement here, so pointers are keyed by requirement_id
        # for rendering, not flattened into one list by unit_id alone.
        groups = []
        all_pointers = []
        for req in weak_reqs:
            req_pointers = pointers_for(conn, requirement_judgments(conn, req["id"]), "weak", primary_ids, secondary_ids)
            groups.append({"id": req["id"], "text": req["text"], "weight": req["weight"], "pointers": req_pointers})
            all_pointers.extend(req_pointers)
        entry = _section_entry(sections_stored, "weak")
        proposed = proposed_pointer_text(all_pointers)
        sections.append({
            "key": "weak", "kind": "weak",
            "requirements": groups,
            "proposed_pointer_text": proposed,
            "pointer_text": entry["pointers_edited"] if entry["pointers_edited"] is not None else proposed,
            "pointers_edited": entry["pointers_edited"] is not None,
            "text": entry["text"], "skipped": entry["skipped"],
        })

    if gap_reqs:
        entry = _section_entry(sections_stored, "gaps")
        sections.append({
            "key": "gaps", "kind": "gaps",
            "requirements": [{"id": r["id"], "text": r["text"], "weight": r["weight"]} for r in gap_reqs],
            "text": entry["text"], "skipped": entry["skipped"],
        })

    close_entry = _section_entry(sections_stored, "close")
    sections.append({"key": "close", "kind": "plain", "text": close_entry["text"], "skipped": close_entry["skipped"]})

    return {
        "sections": sections,
        "matched_shown": len(shown_matched),
        "matched_total": len(all_matched),
        "matched_sections_setting": settings.matched_sections,
    }


def generate_letter_text(conn: sqlite3.Connection, job_id: int) -> str:
    """§11 point 13: joins greeting, Opening, the middle section texts in
    displayed order (skipping skipped/empty/unrendered ones), Close, and
    sign-off with blank lines between. Nothing added, removed, or
    reworded -- exactly the stored text, verbatim."""
    letter = get_or_create_letter(conn, job_id)
    built = build_sections(conn, job_id)
    sections = built["sections"]

    parts = []
    if letter["greeting"] and letter["greeting"].strip():
        parts.append(letter["greeting"].strip())

    open_section = next(s for s in sections if s["key"] == "open")
    close_section = next(s for s in sections if s["key"] == "close")
    middle = [s for s in sections if s["key"] not in ("open", "close")]

    def include(s: dict) -> bool:
        return not s["skipped"] and bool(s["text"] and s["text"].strip())

    if include(open_section):
        parts.append(open_section["text"].strip())
    for s in middle:
        if include(s):
            parts.append(s["text"].strip())
    if include(close_section):
        parts.append(close_section["text"].strip())

    if letter["signoff"] and letter["signoff"].strip():
        parts.append(letter["signoff"].strip())

    text = "\n\n".join(parts)
    conn.execute(
        "UPDATE letter SET assembled_text = ?, updated_at = datetime('now') WHERE job_id = ?", (text, job_id)
    )
    conn.commit()
    return text
