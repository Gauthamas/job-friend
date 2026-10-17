"""Loads prompt templates and fills named placeholders safely.

Not plain str.format(): these prompts likely show a JSON output shape as an
example (e.g. {"verdict": "yes"}), and .format() chokes on any brace it
wasn't told about. This only replaces {name} when name is one of the
placeholders passed in -- every other brace in the file is left alone."""

import re
from pathlib import Path

_PLACEHOLDER_RE = re.compile(r"\{(\w+)\}")

DEFAULT_SYSTEM_PROMPT = (
    "Output JSON only. No markdown, no commentary, no text outside the JSON "
    "object the user message asks for."
)


def load_prompt(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def fill(template: str, **values) -> str:
    def _sub(m: re.Match) -> str:
        key = m.group(1)
        if key in values:
            return str(values[key])
        return m.group(0)  # unknown {word} -- leave untouched, not an error

    return _PLACEHOLDER_RE.sub(_sub, template)
