import logging

from app.llm.schemas import JudgedUnit, JudgeResult
from app.llm.tasks import MAX_QUOTE_WORDS

logger = logging.getLogger("job_friend.judge_validation")

# Despite the prompt saying "never write none", the model sometimes does
# anyway -- that's a no-op (silently dropped, see validate_unit), not a
# malformed response.
ALL_VERDICT_VALUES = {"match", "weak", "none"}


def normalize_for_quote_check(text: str) -> str:
    """Lowercase, collapse all whitespace to single spaces, strip ends --
    just enough to tolerate the model's own minor whitespace/case drift,
    not a general text-matching algorithm."""
    return " ".join(text.lower().split())


def build_haystack(*fields: str | None) -> str:
    """Normalized, combined text of every field sent to the model for one
    candidate -- the quote must appear verbatim (post-normalization)
    somewhere in here, since it could come from any field sent, not just
    `text`. Pass every field in the same order build_judge_batch_message
    sends them in."""
    return normalize_for_quote_check(" ".join(f for f in fields if f))


def quote_is_valid(quote: str, haystack: str) -> bool:
    return normalize_for_quote_check(quote) in haystack


def validate_unit(
    unit: JudgedUnit, candidate_ids: set[str], haystacks: dict[str, str], seen_ids: set[str],
) -> tuple[bool, list[str]]:
    """Returns (keep, hard_errors).

    Non-empty hard_errors means the model broke the wire contract (bad id,
    duplicate id, invalid verdict value) -- the whole call/requirement must
    be retried, same as before. Free-text field length (quote, shows,
    needs) is never a rejection reason -- a verbose but otherwise valid
    answer shouldn't cost a requirement its whole result. Long text is
    truncated for display only, in judging.py's _fold_quote_into_why.

    keep=False with no hard_errors is a silent drop, never a retry
    trigger: an explicit "none" (a no-op -- omitting the unit already
    means none) or a quote that doesn't appear anywhere in what was
    actually sent for that candidate (we won't trust a verdict we can't
    verify the model actually read from).
    """
    if unit.id not in candidate_ids:
        return False, [f"unit id {unit.id!r} is not in the candidate set"]
    if unit.id in seen_ids:
        return False, [f"unit id {unit.id!r} listed more than once"]
    if unit.v not in ALL_VERDICT_VALUES:
        return False, [f"verdict {unit.v!r} for unit {unit.id!r} is not match/weak/none"]

    if len(unit.quote.split()) > MAX_QUOTE_WORDS:
        logger.info(
            "quote for unit %s exceeds %d words (log-only, not rejected): %r",
            unit.id, MAX_QUOTE_WORDS, unit.quote,
        )

    if unit.v == "none":
        return False, []

    if not quote_is_valid(unit.quote, haystacks.get(unit.id, "")):
        logger.info("quote not found in what was sent for unit %s, dropping: %r", unit.id, unit.quote)
        return False, []

    return True, []


def validate_judge(result: JudgeResult, candidate_ids: set[str], haystacks: dict[str, str]) -> list[str]:
    """Validates one requirement's result from within a batch response.
    Filters result.units down to only the kept units as a side effect --
    the caller only inspects the returned error list to decide whether
    this requirement's result is usable, so this is how a soft-dropped
    unit (bad quote, explicit "none") ends up simply absent rather than
    invalidating the whole requirement's result."""
    errors: list[str] = []
    seen_ids: set[str] = set()
    kept: list[JudgedUnit] = []

    for unit in result.units:
        keep, unit_errors = validate_unit(unit, candidate_ids, haystacks, seen_ids)
        errors.extend(unit_errors)
        seen_ids.add(unit.id)
        if keep:
            kept.append(unit)

    if not errors:
        result.units = kept
    return errors
