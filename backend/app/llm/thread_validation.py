"""Milestone 4: code-side validation for thread
discovery. The model only proposes -- every rule here runs in code, never
trusted from the model's own say-so."""

import logging

from app.llm.judge_validation import normalize_for_quote_check, quote_is_valid
from app.llm.schemas import ProposeThreadsResult

logger = logging.getLogger("job_friend.threads")

DISPLAY_TRUNCATE_WORDS = 15


def truncate_for_display(text: str, max_words: int = DISPLAY_TRUNCATE_WORDS) -> str:
    """A word-count cap must never reject a result (§7/§9) -- this is the
    only thing a long model string ever gets: shortened for display, the
    full text is still what gets validated/stored."""
    words = text.split()
    if len(words) <= max_words:
        return text
    return " ".join(words[:max_words]) + "…"


def clean_proposed_threads(
    result: ProposeThreadsResult, valid_statement_ids: set[str],
) -> list[tuple[str, list[str]]]:
    """Returns [(idea, [statement_id, ...]), ...] for threads that survive:
    unknown statement ids dropped (logged), a statement id already claimed
    by an earlier thread in this same response dropped from the later one
    (logged) -- "ids must exist and be unique across threads." Threads
    themselves are NOT dropped here for being too small; that's the
    caller's job, after assign_unused has had a chance to add more."""
    claimed: set[str] = set()
    cleaned: list[tuple[str, list[str]]] = []
    for thread in result.threads:
        kept_ids: list[str] = []
        for sid in thread.supporting_statement_ids:
            if sid not in valid_statement_ids:
                logger.info("propose_threads: dropping unknown statement id %r", sid)
                continue
            if sid in claimed:
                logger.info("propose_threads: statement id %r already claimed by another thread, dropping", sid)
                continue
            claimed.add(sid)
            kept_ids.append(sid)
        cleaned.append((thread.idea, kept_ids))
    return cleaned


def quote_or_none(quote: str, unit_text: str) -> str | None:
    """verify_thread's quote must appear verbatim in the unit text -- if
    not, treat as no quote. Never repaired/corrected."""
    if not quote:
        return None
    if not quote_is_valid(quote, normalize_for_quote_check(unit_text)):
        return None
    return quote
