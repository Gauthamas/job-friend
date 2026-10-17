"""Pure metric functions for scripts/benchmark.py -- no LLM call, no I/O,
so every one of these is directly testable. The only app code reused here
is clean_proposed_threads (app.llm.thread_validation), which is itself
pure/deterministic -- reusing it keeps the valid-support metric honest
against whatever validation rule the app actually enforces, instead of a
second copy that could drift from it.
"""

from __future__ import annotations

import re
import statistics
from collections import Counter
from datetime import datetime
from itertools import combinations
from typing import Optional


# --- Thread stability (Jaccard, best-match grouping) ---

def jaccard(a: set, b: set) -> float:
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def best_match_average_jaccard(groups_a: list[set], groups_b: list[set]) -> float:
    """For each group in groups_a, its best (highest-Jaccard) match among
    groups_b; returns the average over groups_a. Directional -- call twice
    (both ways) and average for a symmetric score, which pairwise_stability
    does."""
    if not groups_a:
        return 1.0  # nothing in A to have failed to match
    if not groups_b:
        return 0.0  # everything in A has no match in B
    return sum(max(jaccard(ga, gb) for gb in groups_b) for ga in groups_a) / len(groups_a)


def pairwise_stability(all_run_groups: list[list[set]]) -> float:
    """Average, over every pair of repeats, of the symmetric best-match
    Jaccard overlap between their statement groupings. 1.0 for zero or one
    run (nothing to compare)."""
    if len(all_run_groups) < 2:
        return 1.0
    scores = []
    for a, b in combinations(all_run_groups, 2):
        scores.append((best_match_average_jaccard(a, b) + best_match_average_jaccard(b, a)) / 2)
    return sum(scores) / len(scores)


# --- Valid-support rate (reuses the app's own validation) ---

def valid_support_rate(proposed, valid_ids: set[str]) -> dict:
    """`proposed` is a ProposeThreadsResult (or any object with a `.threads`
    list of objects exposing `.idea`/`.supporting_statement_ids`). Returns
    counts plus the rate -- cleaned ids divided by raw proposed ids, 1.0
    when nothing was proposed (vacuously valid, not a divide-by-zero)."""
    from app.llm.thread_validation import clean_proposed_threads

    cleaned = clean_proposed_threads(proposed, valid_ids)
    raw_total = sum(len(t.supporting_statement_ids) for t in proposed.threads)
    cleaned_total = sum(len(ids) for _, ids in cleaned)
    rate = (cleaned_total / raw_total) if raw_total else 1.0
    return {"raw_total": raw_total, "cleaned_total": cleaned_total, "rate": rate}


# --- verify_thread verdict mix / quote-found share ---

def verdict_mix(verdicts: list[str]) -> dict[str, float]:
    n = len(verdicts)
    if n == 0:
        return {"yes": 0.0, "partly": 0.0, "no": 0.0}
    counts = Counter(verdicts)
    return {k: counts.get(k, 0) / n for k in ("yes", "partly", "no")}


def quote_found_share(quotes: list[Optional[str]]) -> float:
    if not quotes:
        return 0.0
    return sum(1 for q in quotes if q) / len(quotes)


# --- Judging agreement: override rate + confusion matrix ---

def override_rate(rows: list[dict]) -> dict:
    """`rows`: [{"model_verdict": ..., "user_verdict": ...}, ...] for every
    non-added-by-user judgment. A null user_verdict means "not changed",
    not "reviewed and accepted" -- this is a lower bound on disagreement,
    documented again in the report itself."""
    total = len(rows)
    overridden = sum(1 for r in rows if r.get("user_verdict") is not None)
    return {"total": total, "overridden": overridden, "rate": (overridden / total) if total else 0.0}


def confusion_matrix(rows: list[dict]) -> dict[str, dict[str, int]]:
    """{model_verdict: {user_verdict: count}} over only the rows where the
    user actually set a verdict (the only cells we have ground truth for)."""
    verdicts = ("match", "weak", "none")
    matrix = {m: {u: 0 for u in verdicts} for m in verdicts}
    for r in rows:
        m, u = r.get("model_verdict"), r.get("user_verdict")
        if m in verdicts and u in verdicts:
            matrix[m][u] += 1
    return matrix


def verdict_shares(verdicts: list[Optional[str]]) -> dict[str, float]:
    verdicts = [v for v in verdicts if v is not None]
    n = len(verdicts)
    if n == 0:
        return {"match": 0.0, "weak": 0.0, "none": 0.0}
    counts = Counter(verdicts)
    return {k: counts.get(k, 0) / n for k in ("match", "weak", "none")}


def error_type(last_error: str) -> str:
    """Buckets a requirement's last_error into a short category, for a
    readable breakdown instead of one row per unique message."""
    if last_error is None:
        return "none"
    text = last_error.lower()
    if "not in the candidate set" in text:
        return "id not in candidate set"
    if "cut off" in text or "not included in the batch response" in text:
        return "cut off / missing from batch response"
    if "listed more than once" in text:
        return "duplicate id"
    if "not match/weak" in text:
        return "invalid verdict value"
    if "unexpected error" in text:
        return "unexpected exception"
    if "timed out" in text:
        return "model call timed out"
    if "exceeds" in text and "word" in text:
        return "field too long (legacy rule, no longer rejected)"
    return "other"


def status_breakdown(statuses: list[str]) -> dict[str, int]:
    return dict(Counter(statuses))


def error_type_breakdown(errors: list[str]) -> dict[str, int]:
    return dict(Counter(error_type(e) for e in errors))


# --- Timing aggregation ---

_DT_FORMATS = ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S")


def parse_dt(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    for fmt in _DT_FORMATS:
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    return None


def stage_span(timestamps: list[Optional[str]]) -> Optional[float]:
    """Seconds between the earliest and latest of `timestamps`, ignoring
    unparseable/missing ones. None if fewer than two parse."""
    parsed = sorted(dt for dt in (parse_dt(t) for t in timestamps) if dt is not None)
    if len(parsed) < 2:
        return None
    return (parsed[-1] - parsed[0]).total_seconds()


def duration_or_none(seconds: Optional[float]) -> Optional[float]:
    """A negative duration means the underlying timestamps are mutually
    inconsistent (seen in this dev DB on a few jobs whose judging_deadline
    predates judging_started_at -- almost certainly stale data from early
    manual testing, not a real elapsed time) -- never worth reporting as
    if it were a real duration."""
    if seconds is None or seconds < 0:
        return None
    return seconds


def median(values: list[float]) -> Optional[float]:
    values = [v for v in values if v is not None]
    return statistics.median(values) if values else None


# "job 47: batch of requirements [466, 467] (start=...) -> 1 written (2
# valid results), finish_reason=stop, prompt_tokens=1770,
# completion_tokens=544, reasoning_tokens=0, seconds_total=257.94, ...
# tokens_per_s=4.53"
_LOG_LINE_RE = re.compile(
    r"job (?P<job_id>\d+): batch of requirements .* "
    r"prompt_tokens=(?P<prompt_tokens>\S+), completion_tokens=(?P<completion_tokens>\S+), "
    r"reasoning_tokens=(?P<reasoning_tokens>\S+), seconds_total=(?P<seconds_total>[\d.]+),.*"
    r"tokens_per_s=(?P<tokens_per_s>\S+)"
)


def parse_judging_log_line(line: str) -> Optional[dict]:
    m = _LOG_LINE_RE.search(line)
    if not m:
        return None

    def _num(s: str) -> Optional[float]:
        return None if s in ("None", "") else float(s)

    return {
        "job_id": int(m["job_id"]),
        "prompt_tokens": _num(m["prompt_tokens"]),
        "completion_tokens": _num(m["completion_tokens"]),
        "reasoning_tokens": _num(m["reasoning_tokens"]),
        "seconds_total": _num(m["seconds_total"]),
        "tokens_per_s": _num(m["tokens_per_s"]),
    }


def aggregate_log_metrics(lines: list[str], job_id: int) -> dict:
    """Completion-tokens-per-second for one job, across every batch call
    logged for it: total completion tokens over total generation seconds
    (not an average of per-call rates, which would weight a tiny batch the
    same as a huge one)."""
    rows = [r for r in (parse_judging_log_line(ln) for ln in lines) if r and r["job_id"] == job_id]
    total_completion = sum(r["completion_tokens"] or 0 for r in rows)
    total_seconds = sum(r["seconds_total"] or 0 for r in rows)
    return {
        "batches": len(rows),
        "total_completion_tokens": total_completion,
        "total_seconds": total_seconds,
        "completion_tokens_per_second": (total_completion / total_seconds) if total_seconds else None,
    }
