import sqlite3

from fastapi import APIRouter, Depends, HTTPException

from app.api_schemas import (
    CloseHintOut,
    GenerateResponse,
    LetterOut,
    LetterPatchRequest,
    LetterSectionOut,
    OpeningHintOut,
    PointerOut,
    PointerPatchRequest,
    RequirementRefOut,
    SectionPatchRequest,
    ThreadBarOut,
)
from app.config import settings
from app.deps import get_db
from app.letter import build_sections, close_hint, generate_letter_text, get_or_create_letter, opening_hint, save_section
from app.thread_ranking import get_choice

router = APIRouter(prefix="/api/jobs", tags=["letter"])


def _fetch_job_or_404(conn: sqlite3.Connection, job_id: int) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM job WHERE id = ?", (job_id,)).fetchone()
    if not row:
        raise HTTPException(404, "Job not found")
    return row


def _words(text: str) -> int:
    return len(text.split()) if text and text.strip() else 0


def _thread_bar(conn: sqlite3.Connection, job_id: int, role: str) -> ThreadBarOut:
    choice = get_choice(conn, job_id, role)
    if not choice:
        return ThreadBarOut()
    thread_row = conn.execute("SELECT * FROM thread WHERE id = ?", (choice["thread_id"],)).fetchone()
    if not thread_row:
        return ThreadBarOut()
    statements = conn.execute(
        "SELECT s.text FROM thread_statement ts JOIN statement s ON s.id = ts.statement_id "
        "WHERE ts.thread_id = ? ORDER BY ts.id",
        (thread_row["id"],),
    ).fetchall()
    return ThreadBarOut(
        thread_id=thread_row["id"], idea=thread_row["idea"], edited_idea=thread_row["edited_idea"],
        statements=[s["text"] for s in statements if s["text"]],
    )


def _section_out(s: dict) -> LetterSectionOut:
    return LetterSectionOut(
        key=s["key"], kind=s["kind"], text=s.get("text", ""), skipped=s.get("skipped", False),
        word_count=_words(s.get("text", "")),
        requirement_id=s.get("requirement_id"), requirement_text=s.get("requirement_text"),
        weight=s.get("weight"), verdict=s.get("verdict"),
        pointers=[PointerOut(**p) for p in s.get("pointers", [])],
        proposed_pointer_text=s.get("proposed_pointer_text"), pointer_text=s.get("pointer_text"),
        pointers_edited=s.get("pointers_edited", False),
        requirements=[RequirementRefOut(**r) for r in s.get("requirements", [])],
    )


def _letter_out(conn: sqlite3.Connection, job_id: int) -> LetterOut:
    letter = get_or_create_letter(conn, job_id)
    built = build_sections(conn, job_id)
    sections = [_section_out(s) for s in built["sections"]]
    total_words = sum(s.word_count for s in sections if not s.skipped)
    return LetterOut(
        job_id=job_id, sections=sections, matched_shown=built["matched_shown"],
        matched_total=built["matched_total"], matched_sections_setting=built["matched_sections_setting"],
        total_word_count=total_words, section_char_limit=settings.section_char_limit,
        greeting=letter["greeting"], signoff=letter["signoff"],
        assembled_text=letter["assembled_text"], finished=bool(letter["finished"]),
        primary=_thread_bar(conn, job_id, "primary"), secondary=_thread_bar(conn, job_id, "secondary"),
        opening_hint=OpeningHintOut(**opening_hint(conn, job_id)),
        close_hint=CloseHintOut(**close_hint(conn, job_id)),
    )


@router.get("/{job_id}/letter", response_model=LetterOut)
def get_letter(job_id: int, conn: sqlite3.Connection = Depends(get_db)):
    _fetch_job_or_404(conn, job_id)
    return _letter_out(conn, job_id)


@router.patch("/{job_id}/letter", response_model=LetterOut)
def patch_letter(job_id: int, body: LetterPatchRequest, conn: sqlite3.Connection = Depends(get_db)):
    """Greeting/sign-off text boxes -- optional, never touched by a model."""
    _fetch_job_or_404(conn, job_id)
    get_or_create_letter(conn, job_id)
    updates = {}
    if "greeting" in body.model_fields_set:
        updates["greeting"] = body.greeting
    if "signoff" in body.model_fields_set:
        updates["signoff"] = body.signoff
    if updates:
        set_clause = ", ".join(f"{k} = ?" for k in updates)
        conn.execute(f"UPDATE letter SET {set_clause}, updated_at = datetime('now') WHERE job_id = ?", (*updates.values(), job_id))
        conn.commit()
    return _letter_out(conn, job_id)


@router.patch("/{job_id}/letter/sections/{key}", response_model=LetterOut)
def patch_section(job_id: int, key: str, body: SectionPatchRequest, conn: sqlite3.Connection = Depends(get_db)):
    """Debounced autosave target for a section's text box, and the
    skip toggle (§10 point 6)."""
    _fetch_job_or_404(conn, job_id)
    updates = {}
    if "text" in body.model_fields_set:
        updates["text"] = body.text or ""
    if "skipped" in body.model_fields_set:
        updates["skipped"] = bool(body.skipped)
    if updates:
        save_section(conn, job_id, key, **updates)
    return _letter_out(conn, job_id)


@router.patch("/{job_id}/letter/pointers/{key}", response_model=LetterOut)
def patch_pointers(job_id: int, key: str, body: PointerPatchRequest, conn: sqlite3.Connection = Depends(get_db)):
    """§10 point 7: edit the pointer text block, or Reset (text=null)
    back to the proposed one."""
    _fetch_job_or_404(conn, job_id)
    save_section(conn, job_id, key, pointers_edited=body.text)
    return _letter_out(conn, job_id)


@router.post("/{job_id}/letter/generate", response_model=GenerateResponse)
def generate(job_id: int, conn: sqlite3.Connection = Depends(get_db)):
    """§11: Generate assembles the letter verbatim -- no model call,
    nothing added, removed, or reworded."""
    _fetch_job_or_404(conn, job_id)
    text = generate_letter_text(conn, job_id)
    return GenerateResponse(assembled_text=text, word_count=_words(text))


@router.post("/{job_id}/letter/finish", response_model=LetterOut)
def finish(job_id: int, conn: sqlite3.Connection = Depends(get_db)):
    """§11 point 14: "This is the one" -- copying to the clipboard is a
    frontend action on the already-generated text; this just records it."""
    _fetch_job_or_404(conn, job_id)
    get_or_create_letter(conn, job_id)
    conn.execute("UPDATE letter SET finished = 1, updated_at = datetime('now') WHERE job_id = ?", (job_id,))
    conn.execute("UPDATE job SET finished_at = datetime('now') WHERE id = ?", (job_id,))
    conn.commit()
    return _letter_out(conn, job_id)
