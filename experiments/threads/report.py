"""Renders report.md from already-computed numbers. Kept separate from
run.py's orchestration so the rendering itself is easy to test."""

from dataclasses import dataclass
from typing import Optional


@dataclass
class StrategyReport:
    strategy: str
    runs: int
    threads_found_avg: float
    strong_threads_avg: float
    quote_exactness_pct: float
    control_pass: str  # "k/R"
    stability: float
    coverage_avg: float  # mean yes-coverage per thread
    total_seconds: float
    total_prompt_tokens: int
    total_completion_tokens: int
    human_statement_count: int
    model_statement_count: int
    agreement_with_expected: Optional[float]  # None unless statement_source == "human"
    truncated_count: int = 0  # calls that hit finish_reason == "length" on any attempt
    parse_failed_count: int = 0  # calls that ended ok=False for a reason other than truncation


def render_report(reports: list[StrategyReport]) -> str:
    lines = ["# Thread-finding experiment report\n"]
    lines.append(
        "| strategy | runs | threads (avg) | strong (avg) | quote exact % | control pass "
        "| stability | coverage (avg yes/thread) | time (s) | tokens (prompt/completion) "
        "| statements (human/model) | agreement | truncated | parse failed |"
    )
    lines.append("|---|---|---|---|---|---|---|---|---|---|---|---|---|---|")
    for r in reports:
        agreement_str = f"{r.agreement_with_expected:.2f}" if r.agreement_with_expected is not None else "n/a"
        lines.append(
            f"| {r.strategy} | {r.runs} | {r.threads_found_avg:.1f} | {r.strong_threads_avg:.1f} "
            f"| {r.quote_exactness_pct * 100:.1f}% | {r.control_pass} | {r.stability:.2f} "
            f"| {r.coverage_avg:.1f} | {r.total_seconds:.1f} "
            f"| {r.total_prompt_tokens}/{r.total_completion_tokens} "
            f"| {r.human_statement_count}/{r.model_statement_count} | {agreement_str} "
            f"| {r.truncated_count} | {r.parse_failed_count} |"
        )
    return "\n".join(lines) + "\n"
