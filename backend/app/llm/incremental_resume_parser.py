import json
from dataclasses import dataclass, field
from typing import Optional

from app.llm.dates import normalize_month

_decoder = json.JSONDecoder()

# Order matters: matches RoleBullets' field order, and "bullets" must be
# handled separately (last) since it's an array, not a bare scalar value.
_META_FIELDS = ["company", "title", "start", "end", "section"]


@dataclass
class ParserEvent:
    kind: str  # "role_meta" | "bullet" | "role_done"
    role_index: int
    data: dict = field(default_factory=dict)


class IncrementalResumeParser:
    """Best-effort incremental reader for resume_structure's streamed JSON
    output: {"roles": [{"company", "title", "start", "end", "section",
    "bullets": [...]}]}.

    Not a general JSON parser — it only knows this one shape. It leans on
    stdlib json.JSONDecoder.raw_decode() to parse each individual value
    (string, array) the moment that value's closing token has arrived, so
    all string-escaping/unicode correctness comes from the stdlib, not
    hand-rolled scanning; this class only locates where the next value starts.

    This exists purely to drive live UI updates as roles/bullets arrive.
    The authoritative result is always the final full-document parse done
    by the LLM runner — if this parser misses or misparses something, the
    only consequence is a UI hiccup, never bad data being committed.
    """

    def __init__(self):
        self._buffer = ""
        self._pos = 0
        self._role_index = -1
        self._meta_field_index = 0
        self._current: dict = {}
        self._bullets: list[str] = []
        self._in_bullets = False
        self._searching_for_role = True

    def feed(self, delta: str) -> list[ParserEvent]:
        self._buffer += delta
        events: list[ParserEvent] = []
        while True:
            pos_before = self._pos
            event = self._advance()
            if event is not None:
                events.append(event)
            if self._pos == pos_before:
                break
        return events

    def _skip_ws(self) -> None:
        while self._pos < len(self._buffer) and self._buffer[self._pos] in " \t\r\n,":
            self._pos += 1

    def _advance(self) -> Optional[ParserEvent]:
        self._skip_ws()

        if self._searching_for_role:
            idx = self._buffer.find("{", self._pos)
            if idx == -1:
                return None
            self._pos = idx + 1
            self._role_index += 1
            self._current = {}
            self._bullets = []
            self._meta_field_index = 0
            self._in_bullets = False
            self._searching_for_role = False
            return None

        if not self._in_bullets and self._meta_field_index < len(_META_FIELDS):
            return self._advance_meta_field()

        if not self._in_bullets:
            key_idx = self._buffer.find('"bullets"', self._pos)
            if key_idx == -1:
                return None
            bracket_idx = self._buffer.find("[", key_idx)
            if bracket_idx == -1:
                return None
            self._pos = bracket_idx + 1
            self._in_bullets = True
            return None

        return self._advance_bullet()

    def _advance_meta_field(self) -> Optional[ParserEvent]:
        field_name = _META_FIELDS[self._meta_field_index]
        key_idx = self._buffer.find(f'"{field_name}"', self._pos)
        if key_idx == -1:
            return None
        colon_idx = self._buffer.find(":", key_idx)
        if colon_idx == -1:
            return None
        value_start = colon_idx + 1
        while value_start < len(self._buffer) and self._buffer[value_start] in " \t\r\n":
            value_start += 1
        if value_start >= len(self._buffer):
            return None

        try:
            value, end = _decoder.raw_decode(self._buffer, value_start)
        except json.JSONDecodeError:
            return None

        # Normalize here too so the live preview matches the final result —
        # the model streams dates as "Apr 2020" etc; ResumeStructureResult's
        # field_validator normalizes them at the end, but without this the
        # live UI would show the raw form until "done" arrives, then flip.
        if field_name in ("start", "end"):
            value = normalize_month(value)

        self._current[field_name] = value
        self._pos = end
        self._meta_field_index += 1

        if self._meta_field_index == len(_META_FIELDS):
            return ParserEvent(kind="role_meta", role_index=self._role_index, data=dict(self._current))
        return None

    def _advance_bullet(self) -> Optional[ParserEvent]:
        self._skip_ws()
        if self._pos < len(self._buffer) and self._buffer[self._pos] == "]":
            self._pos += 1
            role_data = dict(self._current)
            role_data["bullets"] = list(self._bullets)
            self._searching_for_role = True
            return ParserEvent(kind="role_done", role_index=self._role_index, data=role_data)

        try:
            value, end = _decoder.raw_decode(self._buffer, self._pos)
        except json.JSONDecodeError:
            return None

        self._bullets.append(value)
        self._pos = end
        return ParserEvent(
            kind="bullet",
            role_index=self._role_index,
            data={"bullet_index": len(self._bullets) - 1, "text": value},
        )
