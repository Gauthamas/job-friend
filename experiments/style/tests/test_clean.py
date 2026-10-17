from style_exp import clean


def test_greeting_stripped_only_at_start():
    lines = ["Hi there,", "", "The body.", "Hi, random mid-text line."]
    out, removed = clean.strip_greeting(lines)
    assert out == ["", "The body.", "Hi, random mid-text line."]
    assert len(removed) == 1
    assert removed[0].rule == "greeting"


def test_greeting_not_stripped_if_absent():
    lines = ["Just the body.", "More body."]
    out, removed = clean.strip_greeting(lines)
    assert out == lines
    assert removed == []


def test_signature_stripped_from_end():
    lines = ["Body line one.", "Body line two.", "Best,", "Priya"]
    out, removed = clean.strip_signature(lines)
    assert out == ["Body line one.", "Body line two."]
    assert [r.text.strip() for r in removed] == ["Best,", "Priya"]


def test_signature_not_stripped_if_closing_word_too_far_back():
    lines = ["Best,", "a", "b", "c", "d", "e", "f", "g", "h"]
    out, removed = clean.strip_signature(lines, lookback=3)
    assert out == lines
    assert removed == []


def test_quoted_reply_header_and_everything_after_removed():
    lines = ["Real reply text.", "On Mon, Jan 1 at 9:00 AM, Alex wrote:", "> old message", "> more old message"]
    out, removed = clean.strip_quoted_replies(lines)
    assert out == ["Real reply text."]
    assert len(removed) == 3


def test_bare_quote_line_removed_without_header():
    lines = ["Real text.", "> a stray quoted line"]
    out, removed = clean.strip_quoted_replies(lines)
    assert out == ["Real text."]
    assert len(removed) == 1


def test_code_fence_block_removed():
    lines = ["before", "```", "def f(): pass", "```", "after"]
    out, removed = clean.strip_code_fences(lines)
    assert out == ["before", "after"]
    assert len(removed) == 3  # both fence markers + the code line


def test_indented_code_removed():
    lines = ["normal line", "    indented_code_line()", "another normal line"]
    out, removed = clean.strip_indented_code(lines)
    assert out == ["normal line", "another normal line"]
    assert len(removed) == 1


def test_heading_removed():
    kept, rem = clean.strip_heading("## A heading")
    assert kept is None
    assert rem.rule == "heading"
    kept, rem = clean.strip_heading("Not a heading # mid-line")
    assert kept == "Not a heading # mid-line"
    assert rem is None


def test_bullet_removed():
    for line in ["- item", "* item", "• item", "1. item"]:
        kept, rem = clean.strip_bullet(line)
        assert kept is None, line
        assert rem.rule == "bullet"


def test_whole_line_link_removed():
    new_line, removed = clean.strip_links("https://example.com/page")
    assert new_line == ""
    assert len(removed) == 1


def test_inline_link_stripped_leaves_rest_of_sentence():
    new_line, removed = clean.strip_links("See https://example.com/page for details.")
    assert "https://" not in new_line
    assert "for details." in new_line
    assert len(removed) == 1


def test_inline_code_span_stripped():
    new_line, removed = clean.strip_inline_code("Run `pytest -q` to check it.")
    assert "`" not in new_line
    assert "Run" in new_line and "to check it." in new_line
    assert len(removed) == 1


def test_clean_text_end_to_end():
    text = (
        "Hi there,\n\n"
        "## Section heading\n"
        "This is the real content with `inline_code` and a link https://example.com here.\n"
        "- a bullet point\n\n"
        "```\n"
        "code line\n"
        "```\n\n"
        "On Mon, Jan 1 at 9:00 AM, X wrote:\n"
        "> quoted stuff\n\n"
        "Best,\nPriya"
    )
    result = clean.clean_text(text)
    assert "Hi there" not in result.text
    assert "Section heading" not in result.text
    assert "`" not in result.text
    assert "https://" not in result.text
    assert "a bullet point" not in result.text
    assert "code line" not in result.text
    assert "quoted stuff" not in result.text
    assert "Best," not in result.text
    assert "real content" in result.text
    assert len(result.removed) > 0
