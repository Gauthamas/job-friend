"""Entry point: python -m experiments.threads.details --config config.yaml

Reads the artifacts a prior `run.py` run already wrote under cfg.out_dir
(threads_final.json, assign_unused_calls.json, verify_results.json,
statements.json) and renders a human-readable details.md: per strategy and
run, each thread's idea + supporting pair ids, the pairs left unused, and
every unit's verify verdict/quote under its thread. Makes no model calls --
pure read-and-render over what run.py already produced.
"""

import argparse
import json
from pathlib import Path

from .config import Config, load_config


def _reconstruct_s_labels(statements: list[dict]) -> dict[str, str]:
    """statements.json is written before assign_labels() runs, so s_label
    is blank on disk -- labels are S1..Sn over entries with text != null,
    in file order, same as assign_labels() itself does."""
    label_to_pair = {}
    i = 0
    for s in statements:
        if s["text"] is None:
            continue
        i += 1
        label_to_pair[f"S{i}"] = s["pair_id"]
    return label_to_pair


def _collect_failures(run_dir: Path) -> list[tuple[str, str, str, bool]]:
    """Scans every persisted call for this run and returns (call_type, label,
    error, truncated) for each one that didn't come back ok -- nothing here
    is silently dropped, per the spec."""
    failures: list[tuple[str, str, str, bool]] = []

    propose_call = json.loads((run_dir / "propose_threads_call.json").read_text(encoding="utf-8"))
    if not propose_call["ok"]:
        failures.append(("propose_threads", "-", propose_call["error"], propose_call["truncated"]))

    assign_calls = json.loads((run_dir / "assign_unused_calls.json").read_text(encoding="utf-8"))
    for label, o in assign_calls.items():
        call = o["call"]
        if not call["ok"]:
            failures.append(("assign_unused", label, call["error"], call["truncated"]))

    verify_calls_path = run_dir / "verify_calls.json"
    verify_results_path = run_dir / "verify_results.json"
    if verify_calls_path.exists():
        verify_calls = json.loads(verify_calls_path.read_text(encoding="utf-8"))
        verify_results = json.loads(verify_results_path.read_text(encoding="utf-8"))
        for call, v in zip(verify_calls, verify_results):
            if not call["ok"]:
                failures.append(("verify_thread", f"{v['thread_label']}/{v['unit_id']}", call["error"], call["truncated"]))

    statement_calls_path = run_dir / "statement_calls.json"
    if statement_calls_path.exists():
        for log in json.loads(statement_calls_path.read_text(encoding="utf-8")):
            call = log["call"]
            if call is not None and not call["ok"]:
                failures.append(("suggest_similarity", log["pair_id"], call["error"], call["truncated"]))

    return failures


def render_run_details(strategy: str, run_idx: int, run_dir: Path) -> str:
    threads = json.loads((run_dir / "threads_final.json").read_text(encoding="utf-8"))
    statements = json.loads((run_dir / "statements.json").read_text(encoding="utf-8"))
    assign_calls = json.loads((run_dir / "assign_unused_calls.json").read_text(encoding="utf-8"))
    verify_results = json.loads((run_dir / "verify_results.json").read_text(encoding="utf-8"))

    label_to_pair = _reconstruct_s_labels(statements)

    lines = [f"### {strategy} / run{run_idx}\n"]

    lines.append("**Threads:**\n")
    if not threads:
        lines.append("(none)\n")
    for t in threads:
        lines.append(f"- `{t['label']}` {t['idea']}")
        lines.append(f"  - supporting: {', '.join(t['supporting_statement_ids']) or '(none)'}")
    lines.append("")

    unused = sorted(label_to_pair[label] for label, o in assign_calls.items() if o["assigned_to"] is None)
    lines.append(f"**Unused:** {', '.join(unused) if unused else '(none)'}\n")

    lines.append("**Verify verdicts:**\n")
    by_thread: dict[str, list[dict]] = {}
    for v in verify_results:
        by_thread.setdefault(v["thread_label"], []).append(v)
    if not verify_results:
        lines.append("(none)\n")
    for label, rows in by_thread.items():
        lines.append(f"- `{label}`")
        for v in rows:
            exact = "exact" if v["quote_exact"] else "not exact"
            lines.append(f"  - {v['unit_id']}: {v['verdict']} -- \"{v['quote']}\" ({exact})")
    lines.append("")

    failures = _collect_failures(run_dir)
    lines.append("**Failures (truncated or unparsed):**\n")
    if not failures:
        lines.append("(none)\n")
    for call_type, label, error, truncated in failures:
        flag = "truncated" if truncated else "parse error"
        lines.append(f"- {call_type} [{label}] ({flag}): {error}")
    lines.append("")

    return "\n".join(lines)


def render_settings(cfg: Config) -> str:
    mt = cfg.max_tokens
    return (
        "## Settings used\n\n"
        f"- thinking: {cfg.thinking}\n"
        f"- temperature: {cfg.temperature}\n"
        f"- max_tokens: suggest_similarity={mt.suggest_similarity}, "
        f"propose_threads={mt.propose_threads}, assign_unused={mt.assign_unused}, "
        f"verify_thread={mt.verify_thread}\n"
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, required=True)
    args = parser.parse_args()

    cfg = load_config(args.config)
    out_root = cfg.out_dir

    sections = ["# Thread-finding experiment details\n", render_settings(cfg)]
    for strategy in cfg.strategies:
        for run_idx in range(cfg.runs):
            run_dir = out_root / strategy / f"run{run_idx}"
            if not run_dir.exists():
                continue
            sections.append(render_run_details(strategy, run_idx, run_dir))

    text = "\n".join(sections)
    out_path = out_root / "details.md"
    out_path.write_text(text, encoding="utf-8")
    print(text)
    print(f"Wrote {out_path}")


if __name__ == "__main__":
    main()
