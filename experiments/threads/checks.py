"""Every automatic check from the plan. Pure functions over the data_model
types -- no I/O, no model calls, so these are all directly unit-testable."""

from dataclasses import dataclass

from .config import Config
from .data_model import Statement, Thread, VerifyResult
from .llm_client import LlmClient
from .pipeline import assign_labels, propose_threads


def quote_exactness(results: list[VerifyResult]) -> float:
    if not results:
        return 0.0
    return sum(1 for r in results if r.quote_exact) / len(results)


def statement_ids_exist(threads: list[Thread], known_pair_ids: set[str]) -> dict[str, list[str]]:
    """{thread_label: [dangling pair ids]} -- empty dict means every cited
    id is real. The model produced these ids; this re-checks independently
    of whatever propose_threads/assign_unused already filtered."""
    bad = {}
    for t in threads:
        missing = [pid for pid in t.supporting_statement_ids if pid not in known_pair_ids]
        if missing:
            bad[t.label] = missing
    return bad


def is_strong(thread: Thread) -> bool:
    """Counts supporting ids AFTER assign_unused has run, not the initial
    propose_threads output -- a thread that only reaches 3 statements once
    assign_unused attaches a 3rd one is still strong."""
    return len(thread.supporting_statement_ids) >= 3 and thread.coverage_yes >= 4


def jaccard(a: set, b: set) -> float:
    if not a and not b:
        return 1.0
    union = a | b
    if not union:
        return 1.0
    return len(a & b) / len(union)


def match_threads_by_overlap(threads_a: list[Thread], threads_b: list[Thread]) -> list[tuple[Thread, Thread, float]]:
    """Greedy maximum-overlap matching: highest Jaccard pairs claimed
    first, each thread used at most once on either side."""
    candidates = []
    for ta in threads_a:
        for tb in threads_b:
            j = jaccard(set(ta.supporting_statement_ids), set(tb.supporting_statement_ids))
            candidates.append((j, ta, tb))
    candidates.sort(key=lambda c: -c[0])

    used_a, used_b, matches = set(), set(), []
    for j, ta, tb in candidates:
        if ta.label in used_a or tb.label in used_b:
            continue
        used_a.add(ta.label)
        used_b.add(tb.label)
        matches.append((ta, tb, j))
    return matches


def mean_stability(runs_threads: list[list[Thread]]) -> float:
    """Mean Jaccard across every matched thread pair, across every pair of
    runs. 0.0 if there's only one run (nothing to compare)."""
    scores = []
    for i in range(len(runs_threads)):
        for j in range(i + 1, len(runs_threads)):
            for _, _, score in match_threads_by_overlap(runs_threads[i], runs_threads[j]):
                scores.append(score)
    return sum(scores) / len(scores) if scores else 0.0


@dataclass
class ControlOutcome:
    passed: bool  # True = correctly found no thread
    threads: list[Thread]


def control_result(
    control_statements: list[Statement], cfg: Config, llm: LlmClient, template: str,
) -> ControlOutcome:
    """Runs propose_threads on an isolated control set, using the SAME
    n_threads/min_support as the real run -- a stricter setting here would
    test a different condition than the actual pipeline runs under."""
    labeled = assign_labels(list(control_statements))  # copy: don't mutate the caller's statements
    result = propose_threads(labeled, cfg.n_threads, cfg.min_support, llm, template, cfg)
    return ControlOutcome(passed=len(result.threads) == 0, threads=result.threads)


def agreement_with_expected(expected_threads: dict[str, str], run_threads: list[Thread]) -> float:
    """expected_threads: {pair_id: expected_label}. Pairwise agreement rate
    (the same idea as a Rand index, done in plain Python): for every pair of
    expected pair-ids, do the expected labels agree, and does the run's
    grouping agree? Fraction where both answer the same way."""
    ids = list(expected_threads.keys())
    if len(ids) < 2:
        return 1.0

    run_group: dict[str, str] = {}
    for t in run_threads:
        for pid in t.supporting_statement_ids:
            run_group[pid] = t.label

    agree, total = 0, 0
    for i in range(len(ids)):
        for j in range(i + 1, len(ids)):
            a, b = ids[i], ids[j]
            expected_same = expected_threads[a] == expected_threads[b]
            run_same = a in run_group and run_group.get(a) == run_group.get(b)
            if expected_same == run_same:
                agree += 1
            total += 1
    return agree / total if total else 1.0
