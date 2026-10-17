"""Entry point: python -m experiments.threads.run --config config.yaml

For each strategy in cfg.strategies, runs the full pipeline cfg.runs times,
writes every raw/parsed call to out/<strategy>/run<N>/, then writes one
out/report.md comparing all strategies.
"""

import argparse
import json
import sys
from pathlib import Path

from .checks import (
    agreement_with_expected, control_result, is_strong, mean_stability,
    quote_exactness, statement_ids_exist,
)
from .config import Config, load_config
from .data_model import Statement, Unit
from .ids import split_pair_id
from .llm_client import LlmClient
from .pairs import embedding_pairs, fixed_pairs, random_cycle_pairs
from .pipeline import assign_labels, assign_unused, map_units, propose_threads, verify_threads
from .prompts import fill, load_prompt
from .report import StrategyReport, render_report
from .serialize import statement_to_dict, thread_to_dict, verify_result_to_dict
from .statements import source_statements


def load_units(data_dir: Path) -> dict[str, Unit]:
    raw = json.loads((data_dir / "units.json").read_text(encoding="utf-8"))
    return {u["id"]: Unit(id=u["id"], title=u.get("title", ""), text=u["text"]) for u in raw}


def load_human_map(data_dir: Path) -> dict:
    return json.loads((data_dir / "statements.json").read_text(encoding="utf-8"))


def load_expected(data_dir: Path) -> dict | None:
    path = data_dir / "expected.json"
    if not path.exists():
        return None
    raw = json.loads(path.read_text(encoding="utf-8"))
    return raw or None  # {} means "no expected threads yet", not a real answer key


def load_controls(data_dir: Path, human_map: dict) -> dict[str, list[Statement]]:
    """controls.json: {"control_name": ["U5-U6", "U8-U9", "U3-U4"]} -- pair
    ids pulled straight from the human-authored statements.json, regardless
    of the run's own strategy/statement_source. Rejects any control that
    references a missing or "none" pair, since a control diluted with
    non-statements passes without testing anything."""
    path = data_dir / "controls.json"
    if not path.exists():
        return {}
    raw = json.loads(path.read_text(encoding="utf-8"))

    controls: dict[str, list[Statement]] = {}
    for name, pair_ids in raw.items():
        statements = []
        for pid in pair_ids:
            if pid not in human_map:
                raise ValueError(f"controls.json[{name!r}] references {pid!r}, not in statements.json")
            text = human_map[pid]
            if text is None:
                raise ValueError(
                    f"controls.json[{name!r}] references {pid!r}, which is \"none\" -- "
                    "a control needs real statements, not gaps"
                )
            a, b = pid.split("-", 1)
            statements.append(Statement(pair_id=pid, unit_a=a, unit_b=b, text=text, source="human"))
        controls[name] = statements
    return controls


def load_prompt_templates(data_dir: Path) -> dict[str, str]:
    prompts_dir = data_dir / "prompts"
    names = ["propose_threads", "assign_unused", "verify_thread", "suggest_similarity"]
    return {name: load_prompt(prompts_dir / f"{name}.txt") for name in names}


# Maps this harness's strategy names to the keys pairs_file uses -- "random"
# reads shorter than "random_cycle" and matches what people actually write
# by hand in a pair-sets file.
STRATEGY_TO_PAIR_SET_KEY = {"fixed": "fixed", "random_cycle": "random", "embedding": "embedding"}


def load_pair_sets(path: Path) -> dict[str, list[str]]:
    return json.loads(path.read_text(encoding="utf-8"))


def validate_pair_sets_have_sentences(pair_sets: dict[str, list[str]], strategies: list[str], human_map: dict) -> None:
    """statement_source: human looks up each pair's sentence by id -- a pair
    missing from statements.json, or recorded there as None, has no sentence
    to show the model, so fail loudly up front rather than silently skipping
    it mid-run (pairs_file pairs are meant to be used exactly, not sampled
    around gaps)."""
    missing = sorted({
        pid
        for strategy in strategies
        for pid in pair_sets.get(STRATEGY_TO_PAIR_SET_KEY[strategy], [])
        if human_map.get(pid) is None
    })
    if missing:
        raise ValueError(f"pairs_file pairs with no sentence in statements.json: {missing}")


def build_pairs(
    strategy: str, units: dict[str, Unit], human_map: dict, llm: LlmClient, cfg: Config, seed: int,
    pair_sets: dict[str, list[str]] | None = None,
) -> list[tuple[str, str]]:
    if pair_sets is not None:
        return [split_pair_id(pid) for pid in pair_sets.get(STRATEGY_TO_PAIR_SET_KEY[strategy], [])]
    unit_ids = list(units.keys())
    if strategy == "fixed":
        return fixed_pairs(list(human_map.keys()))
    if strategy == "random_cycle":
        return random_cycle_pairs(unit_ids, seed)
    if strategy == "embedding":
        texts = [f"search_document: {units[uid].text}" for uid in unit_ids]
        vectors = llm.embed(texts)
        embeddings = dict(zip(unit_ids, vectors))
        return embedding_pairs(unit_ids, embeddings, cfg.pairs_per_unit)
    raise ValueError(f"unknown strategy {strategy!r}")


def run_one(
    strategy: str, run_idx: int, cfg: Config, units: dict[str, Unit], human_map: dict,
    prompts: dict[str, str], llm: LlmClient, out_dir: Path,
    pair_sets: dict[str, list[str]] | None = None,
) -> dict:
    """Runs the pipeline once, writes every call to out_dir, returns a
    summary dict used by the aggregation step in main()."""
    seed = cfg.seed + run_idx
    out_dir.mkdir(parents=True, exist_ok=True)

    pairs = build_pairs(strategy, units, human_map, llm, cfg, seed, pair_sets)
    (out_dir / "pairs.json").write_text(json.dumps([list(p) for p in pairs], indent=2), encoding="utf-8")

    def render_suggest_similarity(a: str, b: str) -> str:
        ua, ub = units[a], units[b]
        return fill(
            prompts["suggest_similarity"],
            unit_a_title=ua.title, unit_a_text=ua.text, unit_b_title=ub.title, unit_b_text=ub.text,
        )

    statements, statement_logs = source_statements(pairs, cfg, human_map, llm, render_suggest_similarity)
    (out_dir / "statements.json").write_text(
        json.dumps([statement_to_dict(s) for s in statements], indent=2), encoding="utf-8",
    )
    (out_dir / "statement_calls.json").write_text(
        json.dumps(
            [{"pair_id": log.pair_id, "call": log.call.to_dict() if log.call else None} for log in statement_logs],
            indent=2,
        ),
        encoding="utf-8",
    )

    labeled = assign_labels(statements)
    propose_result = propose_threads(labeled, cfg.n_threads, cfg.min_support, llm, prompts["propose_threads"], cfg)
    (out_dir / "propose_threads_call.json").write_text(
        json.dumps(propose_result.call.to_dict(), indent=2), encoding="utf-8",
    )

    assign_outcomes = assign_unused(propose_result.threads, labeled, llm, prompts["assign_unused"], cfg)
    (out_dir / "assign_unused_calls.json").write_text(
        json.dumps(
            {label: {"assigned_to": o.assigned_to, "call": o.call.to_dict()} for label, o in assign_outcomes.items()},
            indent=2,
        ),
        encoding="utf-8",
    )

    map_units(propose_result.threads)
    verify_results, verify_calls = verify_threads(propose_result.threads, units, llm, prompts["verify_thread"], cfg)
    (out_dir / "verify_calls.json").write_text(
        json.dumps([c.to_dict() for c in verify_calls], indent=2), encoding="utf-8",
    )
    (out_dir / "verify_results.json").write_text(
        json.dumps([verify_result_to_dict(v) for v in verify_results], indent=2), encoding="utf-8",
    )
    (out_dir / "threads_final.json").write_text(
        json.dumps([thread_to_dict(t) for t in propose_result.threads], indent=2), encoding="utf-8",
    )

    known_pair_ids = {s.pair_id for s in statements}
    dangling = statement_ids_exist(propose_result.threads, known_pair_ids)
    if dangling:
        (out_dir / "dangling_statement_ids.json").write_text(json.dumps(dangling, indent=2), encoding="utf-8")

    total_seconds = propose_result.call.seconds
    total_prompt_tokens = propose_result.call.prompt_tokens
    total_completion_tokens = propose_result.call.completion_tokens
    for log in statement_logs:
        if log.call:
            total_seconds += log.call.seconds
            total_prompt_tokens += log.call.prompt_tokens
            total_completion_tokens += log.call.completion_tokens
    for o in assign_outcomes.values():
        total_seconds += o.call.seconds
        total_prompt_tokens += o.call.prompt_tokens
        total_completion_tokens += o.call.completion_tokens
    for c in verify_calls:
        total_seconds += c.seconds
        total_prompt_tokens += c.prompt_tokens
        total_completion_tokens += c.completion_tokens

    human_count = sum(1 for s in statements if s.source in ("human", "human_none"))
    model_count = sum(1 for s in statements if s.source in ("model", "model_none"))

    all_calls = [propose_result.call]
    all_calls += [log.call for log in statement_logs if log.call]
    all_calls += [o.call for o in assign_outcomes.values()]
    all_calls += verify_calls

    return {
        "strategy": strategy, "run_idx": run_idx,
        "threads": propose_result.threads,
        "verify_results": verify_results,
        "statements": statements,
        "total_seconds": total_seconds,
        "total_prompt_tokens": total_prompt_tokens,
        "total_completion_tokens": total_completion_tokens,
        "human_count": human_count, "model_count": model_count,
        "all_calls": all_calls,
    }


def run_pairs_only(cfg: Config) -> None:
    """Builds embedding-strategy pairs only, prints their similarity scores,
    and exits -- no chat-model calls, no propose/assign/verify, no report."""
    from .ids import pair_id
    from .vectors import cosine

    units = load_units(cfg.data_dir)
    unit_ids = list(units.keys())
    llm = LlmClient(cfg.endpoint, cfg.model, cfg.embed_model, cfg.request_timeout_s, cfg.thinking)
    texts = [f"search_document: {units[uid].text}" for uid in unit_ids]
    vectors = llm.embed(texts)
    embeddings = dict(zip(unit_ids, vectors))

    if cfg.pairs_file:
        pair_sets = load_pair_sets(cfg.pairs_file)
        pairs = [split_pair_id(pid) for pid in pair_sets.get("embedding", [])]
    else:
        pairs = embedding_pairs(unit_ids, embeddings, cfg.pairs_per_unit)

    ids = [pair_id(a, b) for a, b in pairs]
    print(json.dumps({"embedding": ids}))

    print(f"{len(pairs)} pairs", file=sys.stderr)
    for (a, b), pid in sorted(zip(pairs, ids), key=lambda t: t[1]):
        sim = cosine(embeddings[a], embeddings[b])
        print(f"{pid}: {sim:.4f}", file=sys.stderr)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--pairs-only", action="store_true")
    args = parser.parse_args()

    cfg = load_config(args.config)

    if args.pairs_only:
        run_pairs_only(cfg)
        return

    data_dir = cfg.data_dir
    out_root = cfg.out_dir
    out_root.mkdir(parents=True, exist_ok=True)

    units = load_units(data_dir)
    human_map = load_human_map(data_dir)
    expected = load_expected(data_dir)
    controls = load_controls(data_dir, human_map)
    prompts = load_prompt_templates(data_dir)

    pair_sets = None
    if cfg.pairs_file:
        pair_sets = load_pair_sets(cfg.pairs_file)
        if cfg.statement_source == "human":
            validate_pair_sets_have_sentences(pair_sets, cfg.strategies, human_map)

    llm = LlmClient(cfg.endpoint, cfg.model, cfg.embed_model, cfg.request_timeout_s, cfg.thinking)

    reports: list[StrategyReport] = []
    sent_temperatures: set[float] = set()

    for strategy in cfg.strategies:
        run_summaries = []
        control_passes = 0
        control_runs = 0

        for run_idx in range(cfg.runs):
            out_dir = out_root / strategy / f"run{run_idx}"
            summary = run_one(strategy, run_idx, cfg, units, human_map, prompts, llm, out_dir, pair_sets)
            run_summaries.append(summary)
            sent_temperatures.update(c.temperature for c in summary["all_calls"])

            for name, control_statements in controls.items():
                outcome = control_result(control_statements, cfg, llm, prompts["propose_threads"])
                control_runs += 1
                if outcome.passed:
                    control_passes += 1
                (out_dir / f"control_{name}.json").write_text(
                    json.dumps({"passed": outcome.passed, "threads": [thread_to_dict(t) for t in outcome.threads]}, indent=2),
                    encoding="utf-8",
                )

        runs_threads = [s["threads"] for s in run_summaries]
        stability = mean_stability(runs_threads) if cfg.runs > 1 else 0.0

        all_verify = [v for s in run_summaries for v in s["verify_results"]]
        all_threads = [t for s in run_summaries for t in s["threads"]]

        agreement = None
        if cfg.statement_source == "human" and expected is not None:
            agreement = sum(
                agreement_with_expected(expected["threads"], s["threads"]) for s in run_summaries
            ) / len(run_summaries)

        strategy_calls = [c for s in run_summaries for c in s["all_calls"]]
        truncated_count = sum(1 for c in strategy_calls if c.truncated)
        parse_failed_count = sum(1 for c in strategy_calls if not c.ok and not c.truncated)

        reports.append(StrategyReport(
            strategy=strategy,
            runs=cfg.runs,
            threads_found_avg=sum(len(s["threads"]) for s in run_summaries) / cfg.runs,
            strong_threads_avg=sum(sum(1 for t in s["threads"] if is_strong(t)) for s in run_summaries) / cfg.runs,
            quote_exactness_pct=quote_exactness(all_verify),
            control_pass=f"{control_passes}/{control_runs}" if control_runs else "n/a",
            stability=stability,
            coverage_avg=(sum(t.coverage_yes for t in all_threads) / len(all_threads)) if all_threads else 0.0,
            total_seconds=sum(s["total_seconds"] for s in run_summaries),
            total_prompt_tokens=sum(s["total_prompt_tokens"] for s in run_summaries),
            total_completion_tokens=sum(s["total_completion_tokens"] for s in run_summaries),
            human_statement_count=sum(s["human_count"] for s in run_summaries),
            model_statement_count=sum(s["model_count"] for s in run_summaries),
            agreement_with_expected=agreement,
            truncated_count=truncated_count,
            parse_failed_count=parse_failed_count,
        ))

    if not sent_temperatures:
        temp_line = "Temperature: no chat-model calls were made, nothing to confirm.\n"
    elif sent_temperatures == {cfg.temperature}:
        temp_line = f"Temperature confirmed: every request sent temperature={cfg.temperature} (from {len(sent_temperatures)} distinct value(s) observed).\n"
    else:
        temp_line = (
            f"Temperature MISMATCH: config says {cfg.temperature}, but requests actually sent {sorted(sent_temperatures)}.\n"
        )

    report_text = render_report(reports) + "\n" + temp_line
    (out_root / "report.md").write_text(report_text, encoding="utf-8")
    print(report_text)
    print(f"Wrote {out_root / 'report.md'}")


if __name__ == "__main__":
    main()
