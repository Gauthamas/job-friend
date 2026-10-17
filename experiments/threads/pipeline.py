"""propose_threads, assign_unused, the mechanical thread->unit mapping, and
verify_thread. Statements are shown to the model as S1..S10, never as pair
ids -- the prompts this harness was tuned against were tested with plain
numbers, and pair ids would be different input the model wasn't tested on."""

from dataclasses import dataclass

from .config import Config
from .data_model import Statement, Thread, Unit, VerifyResult
from .ids import split_pair_id
from .llm_client import CallResult, LlmClient
from .prompts import DEFAULT_SYSTEM_PROMPT, fill


def assign_labels(statements: list[Statement]) -> list[Statement]:
    """S-labels go only on real statements (text is not None) -- "none"
    statements have nothing to thread and are never shown to the model."""
    real = [s for s in statements if s.text is not None]
    for i, s in enumerate(real, start=1):
        s.s_label = f"S{i}"
    return real


def render_statements_block(labeled_statements: list[Statement]) -> str:
    return "\n".join(f"{s.s_label}: {s.text}" for s in labeled_statements)


def render_threads_block(threads: list[Thread]) -> str:
    if not threads:
        return "(no threads yet)"
    return "\n".join(f"{t.label}: {t.idea}" for t in threads)


@dataclass
class ProposeResult:
    threads: list[Thread]
    call: CallResult
    dropped_unknown_ids: list[str]  # S-labels the model cited that don't exist
    dropped_under_support: int  # threads the model proposed but didn't meet min_support


def propose_threads(
    labeled_statements: list[Statement], n_threads: int, min_support: int,
    llm: LlmClient, template: str, cfg: Config,
) -> ProposeResult:
    label_to_pair = {s.s_label: s.pair_id for s in labeled_statements}
    known_labels = set(label_to_pair)

    prompt = fill(
        template, n_threads=n_threads, min_support=min_support,
        statements_block=render_statements_block(labeled_statements),
    )
    call = llm.call_json(
        system_prompt=DEFAULT_SYSTEM_PROMPT, user_message=prompt,
        temperature=cfg.temperature, max_tokens=cfg.max_tokens.propose_threads,
    )
    if not call.ok:
        return ProposeResult(threads=[], call=call, dropped_unknown_ids=[], dropped_under_support=0)

    raw_threads = call.parsed.get("threads", []) if isinstance(call.parsed, dict) else []
    threads: list[Thread] = []
    dropped_unknown: list[str] = []
    dropped_under_support = 0

    for i, raw in enumerate(raw_threads[:n_threads], start=1):
        idea = str(raw.get("idea", "")).strip()
        cited = raw.get("supporting_statement_ids", []) or []
        pair_ids = []
        seen = set()
        for label in cited:
            if label not in known_labels:
                dropped_unknown.append(str(label))
                continue
            pid = label_to_pair[label]
            if pid not in seen:
                seen.add(pid)
                pair_ids.append(pid)

        if len(pair_ids) < min_support:
            dropped_under_support += 1
            continue

        threads.append(Thread(label=f"T{i}", idea=idea, supporting_statement_ids=pair_ids))

    return ProposeResult(threads, call, dropped_unknown, dropped_under_support)


@dataclass
class AssignOutcome:
    assigned_to: str | None  # thread label, or None if left unassigned
    call: CallResult


def assign_unused(
    threads: list[Thread], labeled_statements: list[Statement],
    llm: LlmClient, template: str, cfg: Config,
) -> dict[str, AssignOutcome]:
    """Every labeled statement not already in some thread's support set
    gets offered to the model. Returns {s_label: AssignOutcome}; mutates
    `threads` in place, appending accepted assignments."""
    used_pair_ids = {pid for t in threads for pid in t.supporting_statement_ids}
    threads_block = render_threads_block(threads)
    label_to_thread = {t.label: t for t in threads}

    outcomes: dict[str, AssignOutcome] = {}
    for s in labeled_statements:
        if s.pair_id in used_pair_ids:
            continue

        prompt = fill(template, threads_block=threads_block, statement_id=s.s_label, statement_text=s.text)
        call = llm.call_json(
            system_prompt=DEFAULT_SYSTEM_PROMPT, user_message=prompt,
            temperature=cfg.temperature, max_tokens=cfg.max_tokens.assign_unused,
        )

        assigned_to = None
        if call.ok and isinstance(call.parsed, dict):
            answer = str(call.parsed.get("assignment", "none")).strip()
            if answer in label_to_thread:
                label_to_thread[answer].supporting_statement_ids.append(s.pair_id)
                assigned_to = answer

        outcomes[s.s_label] = AssignOutcome(assigned_to=assigned_to, call=call)

    return outcomes


def map_units(threads: list[Thread]) -> None:
    """Mechanical, no model call: a thread covers every unit named in any
    of its supporting pair ids."""
    for t in threads:
        units: set[str] = set()
        for pid in t.supporting_statement_ids:
            a, b = split_pair_id(pid)
            units.add(a)
            units.add(b)
        t.units = units


def verify_threads(
    threads: list[Thread], units: dict[str, Unit], llm: LlmClient, template: str, cfg: Config,
) -> tuple[list[VerifyResult], list[CallResult]]:
    results: list[VerifyResult] = []
    calls: list[CallResult] = []
    for t in threads:
        for unit_id in sorted(t.units):
            unit = units[unit_id]
            prompt = fill(template, thread_idea=t.idea, unit_title=unit.title, unit_text=unit.text)
            call = llm.call_json(
                system_prompt=DEFAULT_SYSTEM_PROMPT, user_message=prompt,
                temperature=cfg.temperature, max_tokens=cfg.max_tokens.verify_thread,
            )
            calls.append(call)

            if call.ok and isinstance(call.parsed, dict):
                verdict = str(call.parsed.get("verdict", "no")).strip().lower()
                quote = str(call.parsed.get("quote", "") or "")
            else:
                verdict, quote = "no", ""

            quote_exact = bool(quote) and quote in unit.text
            results.append(VerifyResult(t.label, unit_id, verdict, quote, quote_exact))

            if verdict == "yes":
                t.coverage_yes += 1
            elif verdict == "partly":
                t.coverage_partly += 1

    return results, calls
