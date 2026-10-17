import sqlite3
from typing import Literal, Optional

Verdict = Literal["match", "weak", "none"]
RequirementVerdict = Literal["match", "weak", "gap"]


def effective_verdict(judgment_row: sqlite3.Row) -> Optional[Verdict]:
    """§4: "Effective verdict = user_verdict ?? model_verdict." Never
    overwrite model_verdict elsewhere — it's what measures model accuracy."""
    return judgment_row["user_verdict"] or judgment_row["model_verdict"]


def derive_requirement_verdict(judgment_rows: list[sqlite3.Row]) -> RequirementVerdict:
    """§4: derived in code, never stored. Any effective match wins; else
    any effective weak; else it's a gap (including when there are no
    judgments at all — gaps are normal, per principle #4)."""
    effective = [effective_verdict(row) for row in judgment_rows]
    if "match" in effective:
        return "match"
    if "weak" in effective:
        return "weak"
    return "gap"


def requirement_verdict(status: str, judgment_rows: list[sqlite3.Row]) -> RequirementVerdict:
    """The one place that combines requirement status with judgments into
    the verdict shown in the UI. v2 has only 'pending'/'done' statuses --
    a failed/timed-out call simply leaves the requirement 'pending' with no
    judgments written, which already reads as a gap (gaps are normal, per
    principle #4); there is no separate error status to special-case.
    `status` is kept as a parameter for the call sites that already pass it
    and so this stays the one function every API response goes through, not
    re-derived ad hoc. Every API response that surfaces a requirement-level
    verdict (GET /jobs/{id}, the SSE stream, PATCH /judgments/{id}) must go
    through this function."""
    return derive_requirement_verdict(judgment_rows)
