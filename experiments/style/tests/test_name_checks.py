"""Tests the step-9 validity checks without calling any model."""

from style_exp.name_clusters import build_prompt, parse_response, validate_name

SENTENCES = ["I built the thing quickly.", "I shipped it fast."]


def test_valid_name_passes():
    name = "The author favors short, direct sentences with concrete verbs."
    assert validate_name(name, SENTENCES, max_words=25) == []


def test_name_must_start_with_the_author():
    errors = validate_name("This author favors short sentences.", SENTENCES, max_words=25)
    assert any("start with" in e for e in errors)


def test_name_must_not_exceed_max_words():
    long_name = "The author " + " ".join(["word"] * 30)
    errors = validate_name(long_name, SENTENCES, max_words=25)
    assert any("longer than" in e for e in errors)


def test_name_exactly_at_word_limit_passes():
    name = "The author " + " ".join(["word"] * 23)  # 25 words total
    assert len(name.split()) == 25
    assert validate_name(name, SENTENCES, max_words=25) == []


def test_name_must_not_repeat_a_source_sentence():
    name = "The author writes things like I built the thing quickly."
    errors = validate_name(name, SENTENCES, max_words=25)
    assert any("repeats" in e for e in errors)


def test_name_repeat_check_is_case_and_whitespace_insensitive():
    name = "The author would write   I Built The Thing Quickly.  verbatim sometimes."
    errors = validate_name(name, SENTENCES, max_words=25)
    assert any("repeats" in e for e in errors)


def test_multiple_errors_can_be_reported_together():
    bad = "This is not valid at all and " + " ".join(["word"] * 30)
    errors = validate_name(bad, SENTENCES, max_words=25)
    assert len(errors) >= 2


def test_parse_response_extracts_name_and_flag():
    name, flag = parse_response("The author writes short, punchy sentences.\nstyle\n")
    assert name == "The author writes short, punchy sentences."
    assert flag == "style"


def test_parse_response_accepts_flag_on_any_later_line():
    name, flag = parse_response("The author favors formal phrasing.\n\nFlag: topic")
    assert name == "The author favors formal phrasing."
    assert flag == "invalid"  # "Flag: topic" isn't exactly "topic" -- correctly rejected


def test_parse_response_missing_flag_is_invalid():
    name, flag = parse_response("The author writes short sentences.")
    assert name == "The author writes short sentences."
    assert flag == "invalid"


def test_parse_response_empty_text():
    name, flag = parse_response("")
    assert name == ""
    assert flag == "invalid"


def test_build_prompt_numbers_every_sentence_and_names_the_author():
    prompt = build_prompt(SENTENCES)
    assert "1. I built the thing quickly." in prompt
    assert "2. I shipped it fast." in prompt
    assert "The author" in prompt
