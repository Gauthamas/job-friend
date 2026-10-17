"""Parses the "key: value" header block every sample file starts with, e.g.

    kind: email
    register: formal

    Dear hiring manager, ...

The header block ends at the first blank line or a line that is exactly
"---". Every key becomes a field on ParsedFile; "kind" and "register" are
required, nothing else is assumed. The body is whatever text follows,
unmodified -- cleaning happens in clean.py, not here.
"""

from dataclasses import dataclass
from pathlib import Path

REQUIRED_KEYS = ("kind", "register")


class HeaderError(ValueError):
    pass


@dataclass
class ParsedFile:
    path: Path
    sample_id: str
    kind: str
    register: str
    body: str
    headers: dict[str, str]


def _strip_wrapping_quotes(line: str) -> str:
    """'"kind: email"' -> 'kind: email'. Only strips a matching pair at the
    very start and end of the line, so a quote inside the value is left
    alone."""
    if len(line) >= 2 and line[0] == line[-1] and line[0] in ('"', "'"):
        return line[1:-1]
    return line


def parse_file(path: Path) -> ParsedFile:
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()

    headers: dict[str, str] = {}
    i = 0
    while i < len(lines):
        line = _strip_wrapping_quotes(lines[i].strip())
        if not line or line == "---":
            i += 1
            break
        if ":" not in line:
            raise HeaderError(f"{path.name}: expected a 'key: value' header line, got {line!r}")
        key, _, value = line.partition(":")
        headers[key.strip().lower()] = value.strip().strip("\"'")
        i += 1

    missing = [k for k in REQUIRED_KEYS if k not in headers]
    if missing:
        raise HeaderError(f"{path.name}: missing header(s) {missing} (found {list(headers)})")

    body = "\n".join(lines[i:]).strip("\n")
    if not body.strip():
        raise HeaderError(f"{path.name}: no body text after the header")

    return ParsedFile(
        path=path, sample_id=path.stem, kind=headers["kind"], register=headers["register"],
        body=body, headers=headers,
    )


def parse_samples(samples_dir: Path) -> list[ParsedFile]:
    files = sorted(samples_dir.glob("*.txt"))
    if not files:
        raise HeaderError(f"No .txt files found in {samples_dir}")
    return [parse_file(f) for f in files]


def word_count(text: str) -> int:
    return len(text.split())
