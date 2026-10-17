from app.llm.judge_validation import (
    build_haystack,
    normalize_for_quote_check,
    quote_is_valid,
    validate_judge,
)
from app.llm.schemas import JudgeResult
from app.llm.tasks import MAX_QUOTE_WORDS


def make_result(units, reason="short reason"):
    return JudgeResult(req_id="R3", units=units, reason=reason)


def unit(id, v, shows="short shows", needs="short needs", quote=""):
    # quote="" trivially satisfies the substring check regardless of
    # haystacks -- tests that care about quote behavior set it explicitly.
    return {"id": id, "quote": quote, "shows": shows, "needs": needs, "v": v}


def test_valid_response_has_no_errors_and_keeps_units():
    result = make_result([unit("U12", "match"), unit("U27", "weak")])
    errors = validate_judge(result, candidate_ids={"U12", "U27", "U30"}, haystacks={})
    assert errors == []
    assert {u.id for u in result.units} == {"U12", "U27"}


def test_empty_units_is_valid():
    result = make_result([])
    assert validate_judge(result, candidate_ids={"U12", "U27"}, haystacks={}) == []


def test_extra_id_not_in_candidate_set():
    result = make_result([unit("U99", "match")])
    errors = validate_judge(result, candidate_ids={"U12", "U27"}, haystacks={})
    assert any("U99" in e for e in errors)


def test_duplicate_id_is_invalid():
    result = make_result([unit("U12", "match"), unit("U12", "weak")])
    errors = validate_judge(result, candidate_ids={"U12", "U27"}, haystacks={})
    assert any("more than once" in e for e in errors)


def test_bad_verdict_value_is_invalid():
    result = make_result([unit("U12", "strong")])
    errors = validate_judge(result, candidate_ids={"U12"}, haystacks={})
    assert any("verdict" in e for e in errors)


def test_explicit_none_is_dropped_not_rejected():
    # Batch mode has no response_format forcing the model's hand, so it may
    # write "none" despite the prompt saying not to -- that's a no-op
    # (already implied by omission), not a malformed response.
    result = make_result([unit("U12", "none"), unit("U27", "match")])
    errors = validate_judge(result, candidate_ids={"U12", "U27"}, haystacks={})
    assert errors == []
    assert {u.id for u in result.units} == {"U27"}


def test_reason_over_20_words_is_still_valid():
    # Only a prompt-level nudge (tasks.py), not an enforced rejection -- a
    # long reason is a quality issue to improve the prompt for, not a
    # malformed response worth burning a retry attempt on.
    long_reason = " ".join(["word"] * 50)
    result = make_result([], reason=long_reason)
    assert validate_judge(result, candidate_ids={"U12"}, haystacks={}) == []


def test_long_shows_is_never_rejected():
    long_shows = " ".join(["word"] * 50)
    result = make_result([unit("U12", "match", shows=long_shows)])
    assert validate_judge(result, candidate_ids={"U12"}, haystacks={}) == []
    assert result.units[0].shows == long_shows  # kept in full -- truncated for display only, not here


def test_long_needs_is_never_rejected():
    long_needs = " ".join(["word"] * 50)
    result = make_result([unit("U12", "match", needs=long_needs)])
    assert validate_judge(result, candidate_ids={"U12"}, haystacks={}) == []
    assert result.units[0].needs == long_needs


# --- quote (§A: folded into why for storage, validated here) ---


def test_quote_found_in_haystack_is_kept():
    result = make_result([unit("U12", "match", quote="Built an SDK")])
    haystacks = {"U12": normalize_for_quote_check("Built an SDK used by partner teams")}
    errors = validate_judge(result, candidate_ids={"U12"}, haystacks=haystacks)
    assert errors == []
    assert [u.id for u in result.units] == ["U12"]


def test_quote_not_in_haystack_is_dropped_not_rejected():
    result = make_result([unit("U12", "match", quote="totally unrelated words")])
    haystacks = {"U12": normalize_for_quote_check("Built an SDK used by partner teams")}
    errors = validate_judge(result, candidate_ids={"U12"}, haystacks=haystacks)
    assert errors == []  # dropped silently, not a rejection
    assert result.units == []


def test_quote_check_is_case_and_whitespace_normalized():
    assert quote_is_valid("  BUILT   an sdk  ", normalize_for_quote_check("Built an SDK for partners"))


def test_quote_over_word_cap_is_log_only_not_dropped():
    long_quote = " ".join(["word"] * (MAX_QUOTE_WORDS + 5))
    haystack = normalize_for_quote_check(long_quote)
    result = make_result([unit("U12", "match", quote=long_quote)])
    errors = validate_judge(result, candidate_ids={"U12"}, haystacks={"U12": haystack})
    assert errors == []
    assert [u.id for u in result.units] == ["U12"]  # kept despite exceeding the cap


def test_build_haystack_combines_and_normalizes_all_fields():
    haystack = build_haystack("Built an SDK", "Context here", None, "Shipped it", "Python, Kotlin")
    assert "built an sdk" in haystack
    assert "shipped it" in haystack
    assert "python, kotlin" in haystack
