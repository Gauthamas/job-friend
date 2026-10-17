from pathlib import Path

import pytest

from style_exp.headers import HeaderError, parse_file, parse_samples, word_count


def write(tmp_path: Path, name: str, content: str) -> Path:
    p = tmp_path / name
    p.write_text(content, encoding="utf-8")
    return p


def test_valid_header_parses(tmp_path):
    p = write(tmp_path, "a.txt", "kind: email\nregister: formal\n\nDear hiring manager, thanks for your time.\n")
    f = parse_file(p)
    assert f.sample_id == "a"
    assert f.kind == "email"
    assert f.register == "formal"
    assert "Dear hiring manager" in f.body


def test_quoted_header_lines_parse(tmp_path):
    p = write(tmp_path, "a.txt", '"kind: email"\n"register: formal"\n\n\nHi there,\nBody text with enough words here.\n')
    f = parse_file(p)
    assert f.kind == "email"
    assert f.register == "formal"
    assert f.body.startswith("Hi there,")


def test_header_ends_at_dashes(tmp_path):
    p = write(tmp_path, "a.txt", "kind: email\nregister: formal\n---\nBody text here, several words long.\n")
    f = parse_file(p)
    assert f.body.strip() == "Body text here, several words long."


def test_missing_kind_raises(tmp_path):
    p = write(tmp_path, "a.txt", "register: formal\n\nSome body text with enough words in it.\n")
    with pytest.raises(HeaderError):
        parse_file(p)


def test_missing_register_raises(tmp_path):
    p = write(tmp_path, "a.txt", "kind: email\n\nSome body text with enough words in it.\n")
    with pytest.raises(HeaderError):
        parse_file(p)


def test_malformed_header_line_raises(tmp_path):
    p = write(tmp_path, "a.txt", "kind: email\nthis line has no colon\n\nBody.\n")
    with pytest.raises(HeaderError):
        parse_file(p)


def test_empty_body_raises(tmp_path):
    p = write(tmp_path, "a.txt", "kind: email\nregister: formal\n\n")
    with pytest.raises(HeaderError):
        parse_file(p)


def test_parse_samples_reads_every_txt_file(tmp_path):
    write(tmp_path, "a.txt", "kind: email\nregister: formal\n\nBody text here, several words long.\n")
    write(tmp_path, "b.txt", "kind: article\nregister: casual\n\nAnother body, also several words long.\n")
    files = parse_samples(tmp_path)
    assert {f.sample_id for f in files} == {"a", "b"}


def test_parse_samples_empty_dir_raises(tmp_path):
    with pytest.raises(HeaderError):
        parse_samples(tmp_path)


def test_word_count():
    assert word_count("one two three") == 3
    assert word_count("") == 0
