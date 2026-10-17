"""Cleaning rules, each a small function so every rule can be unit-tested on
its own. clean_text() composes them in a fixed order and returns both the
cleaned text and a log of what was removed, so 02_clean.py can report it."""

import re
from dataclasses import dataclass, field

GREETING_RE = re.compile(r"^(hi|hello|dear)\b.*,?\s*$", re.IGNORECASE)
CLOSING_WORD_RE = re.compile(r"^(best|thanks|thank you|regards|cheers|sincerely|warmly)[,.]?\s*$", re.IGNORECASE)
QUOTE_HEADER_RE = re.compile(r"^on .+ wrote:\s*$", re.IGNORECASE)
QUOTE_LINE_RE = re.compile(r"^>")
URL_RE = re.compile(r"https?://\S+")
BULLET_RE = re.compile(r"^\s*([-*•]|\d+\.)\s+")
HEADING_RE = re.compile(r"^\s*#{1,6}\s+")
CODE_FENCE_RE = re.compile(r"^```")
INDENTED_CODE_RE = re.compile(r"^(?: {4}|\t)")
INLINE_CODE_RE = re.compile(r"`[^`]*`")

SIGNATURE_LOOKBACK = 6  # how many trailing non-blank lines to scan for a closing word


@dataclass
class Removed:
    rule: str
    text: str


@dataclass
class CleanResult:
    text: str
    removed: list[Removed] = field(default_factory=list)


def strip_code_fences(lines: list[str]) -> tuple[list[str], list[Removed]]:
    out, removed = [], []
    in_fence = False
    for line in lines:
        if CODE_FENCE_RE.match(line.strip()):
            in_fence = not in_fence
            removed.append(Removed("code_fence", line))
            continue
        if in_fence:
            removed.append(Removed("code", line))
            continue
        out.append(line)
    return out, removed


def strip_indented_code(lines: list[str]) -> tuple[list[str], list[Removed]]:
    out, removed = [], []
    for line in lines:
        if line.strip() and INDENTED_CODE_RE.match(line):
            removed.append(Removed("code", line))
            continue
        out.append(line)
    return out, removed


def strip_quoted_replies(lines: list[str]) -> tuple[list[str], list[Removed]]:
    out, removed = [], []
    in_quote = False
    for line in lines:
        if not in_quote and QUOTE_HEADER_RE.match(line.strip()):
            in_quote = True
            removed.append(Removed("quoted_reply", line))
            continue
        if in_quote:
            removed.append(Removed("quoted_reply", line))
            continue
        if QUOTE_LINE_RE.match(line.strip()):
            removed.append(Removed("quoted_reply", line))
            continue
        out.append(line)
    return out, removed


def strip_greeting(lines: list[str]) -> tuple[list[str], list[Removed]]:
    """Only the greeting line at the very start of the file, not anywhere
    a line happens to start with "Hi"."""
    out = list(lines)
    i = 0
    while i < len(out) and not out[i].strip():
        i += 1
    if i < len(out) and GREETING_RE.match(out[i].strip()):
        removed = [Removed("greeting", out[i])]
        del out[i]
        return out, removed
    return out, []


def strip_signature(lines: list[str], lookback: int = SIGNATURE_LOOKBACK) -> tuple[list[str], list[Removed]]:
    """Only a closing word found within the last `lookback` non-blank lines,
    and everything from there to the end of the file."""
    out = list(lines)
    end = len(out)
    while end > 0 and not out[end - 1].strip():
        end -= 1
    start_scan = max(0, end - lookback)
    closing_idx = None
    for idx in range(start_scan, end):
        if CLOSING_WORD_RE.match(out[idx].strip()):
            closing_idx = idx
            break
    if closing_idx is None:
        return out, []
    removed = [Removed("signature", l) for l in out[closing_idx:end] if l.strip()]
    return out[:closing_idx], removed


def strip_heading(line: str) -> tuple[str | None, Removed | None]:
    if HEADING_RE.match(line):
        return None, Removed("heading", line)
    return line, None


def strip_bullet(line: str) -> tuple[str | None, Removed | None]:
    if BULLET_RE.match(line):
        return None, Removed("bullet", line)
    return line, None


def strip_links(line: str) -> tuple[str, list[Removed]]:
    if URL_RE.fullmatch(line.strip()):
        return "", [Removed("link", line)]
    removed: list[Removed] = []

    def _sub(m: re.Match) -> str:
        removed.append(Removed("link", m.group(0)))
        return ""

    return URL_RE.sub(_sub, line), removed


def strip_inline_code(line: str) -> tuple[str, list[Removed]]:
    removed: list[Removed] = []

    def _sub(m: re.Match) -> str:
        removed.append(Removed("inline_code", m.group(0)))
        return ""

    return INLINE_CODE_RE.sub(_sub, line), removed


def clean_text(text: str) -> CleanResult:
    lines = text.split("\n")
    removed: list[Removed] = []

    lines, r = strip_code_fences(lines)
    removed += r
    lines, r = strip_indented_code(lines)
    removed += r
    lines, r = strip_quoted_replies(lines)
    removed += r
    lines, r = strip_greeting(lines)
    removed += r
    lines, r = strip_signature(lines)
    removed += r

    out_lines: list[str] = []
    for line in lines:
        line2, rem = strip_heading(line)
        if rem:
            removed.append(rem)
            continue
        line2, rem = strip_bullet(line2)
        if rem:
            removed.append(rem)
            continue
        line2, r2 = strip_links(line2)
        removed += r2
        line2, r2 = strip_inline_code(line2)
        removed += r2
        out_lines.append(line2)

    cleaned = "\n".join(out_lines)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip("\n")
    return CleanResult(text=cleaned, removed=removed)
