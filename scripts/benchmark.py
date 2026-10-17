"""Milestone 9: three independent,
read-only benchmark sections -- thread replay (needs LM Studio), judging
agreement, and timing. Never writes to the real database: --agreement and
--timing open it in SQLite's own read-only mode (mode=ro URI); --threads
builds a throwaway job in a temp database and runs the app's own
run_thread_discovery against that.

Usage:
    python scripts/benchmark.py                       # all three sections
    python scripts/benchmark.py --agreement --timing  # just these two
    python scripts/benchmark.py --threads --repeats 3 --fixture fixtures/northlight
    python scripts/benchmark.py --db path/to/other.db --agreement

Output: benchmarks/<timestamp>/report.md and results.json, plus a
plain-text summary on screen.
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parent.parent
BACKEND_DIR = ROOT / "backend"
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(BACKEND_DIR))

import bench_metrics as bm  # noqa: E402

DEFAULT_DB_PATH = str(BACKEND_DIR / "job_friend.db")
DEFAULT_LOG_PATH = str(BACKEND_DIR / "logs" / "judging.log")
DEFAULT_FIXTURE = str(ROOT / "fixtures" / "northlight")


# --- Shared helpers ---

def open_readonly(db_path: str) -> sqlite3.Connection:
    """SQLite's own read-only mode: a stray write anywhere raises instead
    of silently landing on disk. as_posix() so a Windows backslash path
    doesn't get mangled inside the file: URI."""
    uri = f"file:{Path(db_path).resolve().as_posix()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def probe_lmstudio_models(base_url: str) -> list[str]:
    """Best-effort -- used only for the report header, never required."""
    try:
        import openai
        client = openai.OpenAI(base_url=base_url, api_key="lm-studio", max_retries=0, timeout=5)
        return sorted(m.id for m in client.models.list().data)
    except Exception:
        return []


def md_table(headers: list[str], rows: list[list]) -> str:
    def fmt(v):
        if v is None:
            return "—"
        if isinstance(v, float):
            return f"{v:.3f}"
        return str(v)

    lines = ["| " + " | ".join(headers) + " |", "| " + " | ".join("---" for _ in headers) + " |"]
    for row in rows:
        lines.append("| " + " | ".join(fmt(v) for v in row) + " |")
    return "\n".join(lines)


# =====================================================================
# Section 1: thread replay (--threads)
# =====================================================================

class RecordingLLMClient:
    """Transparent wrapper around the app's real LLMClient -- captures
    every call's raw response and metrics as the app's own code makes
    them, so the benchmark never duplicates a model call just to measure
    it."""

    def __init__(self, inner):
        self._inner = inner
        self.calls: list[dict] = []

    def complete(self, task, user_message):
        raw, metrics = self._inner.complete(task, user_message)
        self.calls.append({"task": task.name, "raw": raw, "metrics": metrics})
        return raw, metrics

    def complete_stream(self, task, user_message):
        for event in self._inner.complete_stream(task, user_message):
            if event[0] != "delta":
                _, raw, metrics = event
                self.calls.append({"task": task.name, "raw": raw, "metrics": metrics})
            yield event


def _load_fixture_statements(fixture_dir: Path) -> list[tuple[str, str, str]]:
    """Returns [(unit_a_label, unit_b_label, statement_text), ...] from
    <fixture_dir>/statements.json, keyed "U<a>-U<b>"."""
    statements = json.loads((fixture_dir / "statements.json").read_text(encoding="utf-8"))
    out = []
    for key, text in statements.items():
        m = re.match(r"^(U\d+)-(U\d+)$", key)
        if not m:
            continue
        out.append((m.group(1), m.group(2), text))
    return out


def _build_fixture_job(conn: sqlite3.Connection, fixture_dir: Path) -> int:
    """Builds one throwaway job in `conn` (a temp db) from a fixture's
    units.json + statements.json: every statement becomes a 'written'
    statement on a real pair of real units, exactly what gather_written_
    statements (app/threads.py) expects."""
    units = json.loads((fixture_dir / "units.json").read_text(encoding="utf-8"))
    statements = _load_fixture_statements(fixture_dir)

    conn.execute("INSERT INTO profile (name) VALUES ('bench')")
    conn.execute("INSERT INTO inventory (profile_id, name) VALUES (1, 'bench-inv')")
    conn.execute("INSERT INTO role (inventory_id, company, title, sort_order) VALUES (1, 'bench', 'bench', 0)")
    conn.execute("INSERT INTO flow (profile_id, name, inventory_id) VALUES (1, 'bench-flow', 1)")
    conn.execute("INSERT INTO job (flow_id, title, jd_text) VALUES (1, 'bench-job', 'jd')")
    job_id = conn.execute("SELECT id FROM job ORDER BY id DESC LIMIT 1").fetchone()["id"]

    label_to_unit_id: dict[str, int] = {}
    for i, unit in enumerate(units):
        conn.execute(
            "INSERT INTO unit (role_id, text, source, sort_order) VALUES (1, ?, 'manual', ?)",
            (unit.get("text", unit.get("title", unit["id"])), i),
        )
        label_to_unit_id[unit["id"]] = conn.execute("SELECT id FROM unit ORDER BY id DESC LIMIT 1").fetchone()["id"]

    for label_a, label_b, text in statements:
        if label_a not in label_to_unit_id or label_b not in label_to_unit_id:
            continue
        ua, ub = label_to_unit_id[label_a], label_to_unit_id[label_b]
        ua, ub = min(ua, ub), max(ua, ub)
        conn.execute(
            "INSERT INTO pair (job_id, unit_a_id, unit_b_id, score, model) VALUES (?, ?, ?, 0.5, 'bench')",
            (job_id, ua, ub),
        )
        pair_id = conn.execute("SELECT id FROM pair ORDER BY id DESC LIMIT 1").fetchone()["id"]
        conn.execute("INSERT INTO statement (pair_id, status, text) VALUES (?, 'written', ?)", (pair_id, text))

    conn.commit()
    return job_id


def _run_thread_repeat(conn: sqlite3.Connection, job_id: int, llm_client, model: str) -> dict:
    """One repeat of run_thread_discovery (the app's own function,
    unmodified) against the fixture job, plus everything the DB and the
    recording client captured about it."""
    from app.threads import run_thread_discovery

    run_id = run_thread_discovery(conn, job_id, llm_client, model)

    threads = conn.execute("SELECT * FROM thread WHERE run_id = ?", (run_id,)).fetchall()
    kept = [t for t in threads if not t["below_min"]]
    groups = [
        {r["statement_id"] for r in conn.execute(
            "SELECT statement_id FROM thread_statement WHERE thread_id = ?", (t["id"],)
        ).fetchall()}
        for t in threads
    ]
    all_statement_ids = {
        r["id"] for r in conn.execute(
            "SELECT s.id FROM statement s JOIN pair p ON p.id = s.pair_id WHERE p.job_id = ?", (job_id,)
        ).fetchall()
    }
    used_ids = {sid for g in groups for sid in g}
    unused_count = len(all_statement_ids - used_ids)

    thread_units = conn.execute(
        "SELECT tu.* FROM thread_unit tu JOIN thread t ON t.id = tu.thread_id WHERE t.run_id = ?", (run_id,)
    ).fetchall()
    verdicts = [u["model_verdict"] for u in thread_units if u["model_verdict"]]
    quotes = [u["quote"] for u in thread_units]

    run_row = conn.execute("SELECT * FROM thread_run WHERE id = ?", (run_id,)).fetchone()

    return {
        "run_id": run_id,
        "error": run_row["error"],
        "threads_proposed": len(threads),
        "threads_kept": len(kept),
        "unused_statements": unused_count,
        "groups": groups,
        "verdicts": verdicts,
        "quotes": quotes,
    }


def run_threads_section(args) -> dict:
    # Settings from the settings store, but "thinking off" is a fixed
    # requirement of this benchmark (not whatever the store currently has)
    # -- must be set before app.llm.tasks is ever imported, since its task
    # profiles bake THINK/NO_THINK into system_prompt at import time.
    real_conn = open_readonly(args.db)
    try:
        from app.config import settings
        from app.settings_store import load_settings_from_db
        load_settings_from_db(real_conn)
        settings.thread_thinking = False

        from app.judging import is_any_window_open
        if is_any_window_open(real_conn):
            return {"skipped": True, "reason": "A judging window is open on another job -- refusing to call the model."}
    finally:
        real_conn.close()

    from app.db import init_db
    from app.deps import get_llm_client
    from app.llm.schemas import ProposeThreadsResult

    fixture_dirs = [Path(args.fixture)] if args.fixture else [Path(DEFAULT_FIXTURE)]
    results_by_fixture = {}

    for fixture_dir in fixture_dirs:
        if not (fixture_dir / "units.json").is_file() or not (fixture_dir / "statements.json").is_file():
            results_by_fixture[str(fixture_dir)] = {"error": "missing units.json/statements.json"}
            continue

        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            tmp_db_path = str(Path(tmp) / "bench.db")
            conn = init_db(tmp_db_path)
            job_id = _build_fixture_job(conn, fixture_dir)
            valid_ids = {
                str(i) for i, _ in enumerate(
                    conn.execute(
                        "SELECT s.id FROM statement s JOIN pair p ON p.id = s.pair_id WHERE p.job_id = ? ORDER BY s.id",
                        (job_id,),
                    ).fetchall(), start=1,
                )
            }

            repeats_data = []
            all_calls = []
            for _ in range(args.repeats):
                recorder = RecordingLLMClient(get_llm_client())
                repeat = _run_thread_repeat(conn, job_id, recorder, settings.llm_model)
                repeat["calls"] = recorder.calls
                repeats_data.append(repeat)
                all_calls.extend(recorder.calls)

            conn.close()

        # Valid-support rate: from each repeat's propose_threads raw call.
        support_rates = []
        for repeat in repeats_data:
            propose_calls = [c for c in repeat["calls"] if c["task"] == "propose_threads"]
            if not propose_calls:
                continue
            try:
                parsed = ProposeThreadsResult.model_validate_json(propose_calls[0]["raw"])
            except Exception:
                continue
            support_rates.append(bm.valid_support_rate(parsed, valid_ids)["rate"])

        all_verdicts = [v for r in repeats_data for v in r["verdicts"]]
        all_quotes = [q for r in repeats_data for q in r["quotes"]]
        stability = bm.pairwise_stability([r["groups"] for r in repeats_data])

        call_rows = []
        for c in all_calls:
            m = c["metrics"]
            call_rows.append({
                "task": c["task"],
                "prompt_tokens": m.prompt_tokens if m else None,
                "completion_tokens": m.completion_tokens if m else None,
                "seconds": m.seconds if m else None,
                "tokens_per_second": (m.completion_tokens / m.seconds) if (m and m.seconds) else None,
            })
        totals = {
            "calls": len(call_rows),
            "prompt_tokens": sum(r["prompt_tokens"] or 0 for r in call_rows),
            "completion_tokens": sum(r["completion_tokens"] or 0 for r in call_rows),
            "seconds": sum(r["seconds"] or 0 for r in call_rows),
        }

        results_by_fixture[str(fixture_dir)] = {
            "repeats": args.repeats,
            "threads_proposed_avg": bm.median([r["threads_proposed"] for r in repeats_data]),
            "threads_kept_avg": bm.median([r["threads_kept"] for r in repeats_data]),
            "unused_statements_avg": bm.median([r["unused_statements"] for r in repeats_data]),
            "valid_support_rate_avg": bm.median(support_rates),
            "verdict_mix": bm.verdict_mix(all_verdicts),
            "quote_found_share": bm.quote_found_share(all_quotes),
            "stability_jaccard": stability,
            "per_call": call_rows,
            "totals": totals,
            "errors": [r["error"] for r in repeats_data if r["error"]],
        }

    return {
        "skipped": False,
        "repeats": args.repeats,
        "note": (
            f"Ran {args.repeats} repeat(s) per fixture on this machine's locally loaded model -- "
            "these numbers depend entirely on that model and will not match another one."
        ),
        "fixtures": results_by_fixture,
    }


# =====================================================================
# Section 2: judging agreement (--agreement)
# =====================================================================

def run_agreement_section(args) -> dict:
    conn = open_readonly(args.db)
    try:
        jobs = [r["id"] for r in conn.execute("SELECT id FROM job ORDER BY id").fetchall()]

        def judgment_rows(job_id: Optional[int]) -> list[dict]:
            if job_id is None:
                rows = conn.execute(
                    "SELECT model_verdict, user_verdict FROM judgment WHERE added_by_user = 0"
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT j.model_verdict, j.user_verdict FROM judgment j "
                    "JOIN requirement r ON r.id = j.requirement_id WHERE r.job_id = ? AND j.added_by_user = 0",
                    (job_id,),
                ).fetchall()
            return [dict(r) for r in rows]

        def per_job_agreement(job_id: Optional[int]) -> dict:
            rows = judgment_rows(job_id)
            return {
                "override_rate": bm.override_rate(rows),
                "confusion_matrix": bm.confusion_matrix(rows),
                "model_verdict_shares": bm.verdict_shares([r["model_verdict"] for r in rows]),
            }

        def requirement_rows(job_id: Optional[int]) -> list[sqlite3.Row]:
            if job_id is None:
                return conn.execute("SELECT status, last_error FROM requirement WHERE deleted = 0").fetchall()
            return conn.execute(
                "SELECT status, last_error FROM requirement WHERE deleted = 0 AND job_id = ?", (job_id,)
            ).fetchall()

        def per_job_requirements(job_id: Optional[int]) -> dict:
            rows = requirement_rows(job_id)
            pending_errors = [r["last_error"] for r in rows if r["status"] == "pending" and r["last_error"]]
            return {
                "status_breakdown": bm.status_breakdown([r["status"] for r in rows]),
                "pending_with_error": len(pending_errors),
                "error_types": bm.error_type_breakdown(pending_errors),
            }

        per_job = {
            job_id: {"agreement": per_job_agreement(job_id), "requirements": per_job_requirements(job_id)}
            for job_id in jobs
        }
        overall = {"agreement": per_job_agreement(None), "requirements": per_job_requirements(None)}

        has_reviewed_column = bool(
            conn.execute("SELECT 1 FROM pragma_table_info('judgment') WHERE name = 'reviewed'").fetchone()
        )

        return {
            "jobs": jobs,
            "per_job": per_job,
            "overall": overall,
            "has_reviewed_column": has_reviewed_column,
            "note": (
                'A null user_verdict means "not changed", not "reviewed and accepted" -- the override rate is a '
                "lower-bound disagreement measure, not an accuracy score."
                + (
                    " This schema has no 'reviewed' flag, so a proper agreement rate (reviewed-and-kept vs "
                    "reviewed-and-changed) isn't available; only the override rate above."
                    if not has_reviewed_column else ""
                )
            ),
        }
    finally:
        conn.close()


# =====================================================================
# Section 3: timing (--timing)
# =====================================================================

def run_timing_section(args) -> dict:
    conn = open_readonly(args.db)
    try:
        log_lines = []
        log_path = Path(args.log)
        if log_path.is_file():
            log_lines = log_path.read_text(encoding="utf-8", errors="ignore").splitlines()

        jobs = conn.execute(
            "SELECT id, title, created_at, extraction_seconds, judging_started_at, judging_deadline "
            "FROM job ORDER BY id"
        ).fetchall()

        per_job = {}
        for job in jobs:
            job_id = job["id"]

            req_rows = conn.execute(
                "SELECT status, judged_at, judge_seconds FROM requirement WHERE deleted = 0 AND job_id = ?",
                (job_id,),
            ).fetchall()
            judged = [r for r in req_rows if r["status"] == "done"]
            first_judged_at = min((r["judged_at"] for r in judged if r["judged_at"]), default=None)

            start = bm.parse_dt(job["judging_started_at"])
            first = bm.parse_dt(first_judged_at)
            deadline = bm.parse_dt(job["judging_deadline"])
            time_to_first = bm.duration_or_none((first - start).total_seconds() if (start and first) else None)
            window_total = bm.duration_or_none((deadline - start).total_seconds() if (start and deadline) else None)

            mean_judge_seconds = bm.median([r["judge_seconds"] for r in judged if r["judge_seconds"] is not None])
            log_metrics = bm.aggregate_log_metrics(log_lines, job_id)

            # Later stages -- approximate spans, as the spec calls for.
            statement_rows = conn.execute(
                "SELECT s.updated_at, s.autofilled_from_job_id FROM statement s JOIN pair p ON p.id = s.pair_id "
                "WHERE p.job_id = ?", (job_id,),
            ).fetchall()
            statements_span = bm.stage_span([r["updated_at"] for r in statement_rows])
            autofilled_count = sum(1 for r in statement_rows if r["autofilled_from_job_id"] is not None)

            thread_run_rows = conn.execute(
                "SELECT created_at FROM thread_run WHERE job_id = ?", (job_id,)
            ).fetchall()
            thread_run_span = bm.stage_span([r["created_at"] for r in thread_run_rows])

            letter_row = conn.execute("SELECT updated_at FROM letter WHERE job_id = ?", (job_id,)).fetchone()
            letter_at = letter_row["updated_at"] if letter_row else None

            # Enrichment answers aren't job-scoped (units belong to the
            # inventory, not a job) -- approximated from the units judged
            # for THIS job's requirements, as the closest job-relevant proxy.
            unit_rows = conn.execute(
                "SELECT DISTINCT u.updated_at FROM unit u JOIN judgment j ON j.unit_id = u.id "
                "JOIN requirement r ON r.id = j.requirement_id WHERE r.job_id = ?", (job_id,),
            ).fetchall()
            enrichment_span_approx = bm.stage_span([r["updated_at"] for r in unit_rows])

            per_job[job_id] = {
                "title": job["title"],
                "created_at": job["created_at"],
                "extraction_seconds": job["extraction_seconds"],
                "time_to_first_judged_row_s": time_to_first,
                "judging_window_total_s": window_total,
                "requirements_judged": len(judged),
                "requirements_total": len(req_rows),
                "mean_seconds_per_judged_requirement": mean_judge_seconds,
                "completion_tokens_per_second_log": log_metrics["completion_tokens_per_second"],
                "enrichment_span_s_approx": enrichment_span_approx,
                "statements_span_s": statements_span,
                "autofilled_count": autofilled_count,
                "thread_run_span_s": thread_run_span,
                "letter_updated_at": letter_at,
            }

        medians = {
            key: bm.median([per_job[j][key] for j in per_job])
            for key in (
                "extraction_seconds", "time_to_first_judged_row_s", "judging_window_total_s",
                "mean_seconds_per_judged_requirement", "completion_tokens_per_second_log", "statements_span_s",
            )
        }

        return {
            "job_order": [j["id"] for j in jobs],
            "per_job": per_job,
            "medians": medians,
            "note": (
                "Stage spans (enrichment, statements, thread run) are approximate: earliest-to-latest stored "
                "timestamp for rows touching this job, not an instrumented duration. Enrichment's span is a "
                "further approximation since enrichment answers live on units, not jobs. The letter stage has "
                "only a single updated_at snapshot, not a span."
            ),
        }
    finally:
        conn.close()


# =====================================================================
# Report writing
# =====================================================================

def build_report_md(header: dict, sections: dict) -> str:
    lines = [
        f"# Job-Friend benchmark — {header['date']}",
        "",
        f"- LM Studio models seen: {', '.join(header['lmstudio_models']) or 'unavailable'}",
        f"- Configured LLM model: {header['llm_model']}  ·  Embedding model: {header['embed_model']}",
        f"- Thread settings: n_threads={header['thread_settings']['n_threads']}, "
        f"min_support={header['thread_settings']['min_support']}, "
        f"thread_thinking={header['thread_settings']['thread_thinking']}",
        f"- Jobs in DB: {header['job_count']}  ·  Fixtures benchmarked: {header['fixture_count']}",
        "",
    ]

    if "threads" in sections:
        t = sections["threads"]
        lines.append("## 1. Thread replay")
        if t.get("skipped"):
            lines.append(f"Skipped: {t['reason']}")
        else:
            lines.append(t["note"])
            for fixture, data in t["fixtures"].items():
                lines.append(f"\n### {fixture}")
                if "error" in data:
                    lines.append(f"Error: {data['error']}")
                    continue
                lines.append(md_table(
                    ["metric", "value"],
                    [
                        ["threads proposed (median)", data["threads_proposed_avg"]],
                        ["threads kept (>= min_support, median)", data["threads_kept_avg"]],
                        ["unused statements (median)", data["unused_statements_avg"]],
                        ["valid-support rate (median)", data["valid_support_rate_avg"]],
                        ["verify_thread verdict: yes", data["verdict_mix"]["yes"]],
                        ["verify_thread verdict: partly", data["verdict_mix"]["partly"]],
                        ["verify_thread verdict: no", data["verdict_mix"]["no"]],
                        ["share with an exact quote found", data["quote_found_share"]],
                        ["stability (avg pairwise Jaccard)", data["stability_jaccard"]],
                        ["total calls", data["totals"]["calls"]],
                        ["total prompt tokens", data["totals"]["prompt_tokens"]],
                        ["total completion tokens", data["totals"]["completion_tokens"]],
                        ["total seconds", data["totals"]["seconds"]],
                    ],
                ))
        lines.append("")

    if "agreement" in sections:
        a = sections["agreement"]
        lines.append("## 2. Judging agreement")
        o = a["overall"]
        lines.append(md_table(
            ["metric", "value"],
            [
                ["judgments (model-made)", o["agreement"]["override_rate"]["total"]],
                ["overridden by user", o["agreement"]["override_rate"]["overridden"]],
                ["override rate", o["agreement"]["override_rate"]["rate"]],
                ["model verdict share: match", o["agreement"]["model_verdict_shares"]["match"]],
                ["model verdict share: weak", o["agreement"]["model_verdict_shares"]["weak"]],
                ["model verdict share: none", o["agreement"]["model_verdict_shares"]["none"]],
                ["requirements done", o["requirements"]["status_breakdown"].get("done", 0)],
                ["requirements pending", o["requirements"]["status_breakdown"].get("pending", 0)],
                ["pending with last_error", o["requirements"]["pending_with_error"]],
            ],
        ))
        lines.append("\nConfusion matrix (model → user), overall:")
        matrix = o["agreement"]["confusion_matrix"]
        lines.append(md_table(
            ["model \\ user", "match", "weak", "none"],
            [[m, matrix[m]["match"], matrix[m]["weak"], matrix[m]["none"]] for m in ("match", "weak", "none")],
        ))
        if o["requirements"]["error_types"]:
            lines.append("\nError types (pending requirements):")
            lines.append(md_table(["type", "count"], list(o["requirements"]["error_types"].items())))
        lines.append(f"\n{a['note']}\n")

    if "timing" in sections:
        ti = sections["timing"]
        lines.append("## 3. Timing")
        rows = []
        for job_id in ti["job_order"]:
            d = ti["per_job"][job_id]
            rows.append([
                job_id, d["extraction_seconds"], d["time_to_first_judged_row_s"], d["judging_window_total_s"],
                f"{d['requirements_judged']}/{d['requirements_total']}",
                d["mean_seconds_per_judged_requirement"], d["completion_tokens_per_second_log"],
                d["statements_span_s"], d["autofilled_count"],
            ])
        lines.append(md_table(
            ["job", "extract s", "time to 1st judged s", "window total s", "judged/total",
             "mean s/req", "completion tok/s", "statements span s", "autofilled"],
            rows,
        ))
        lines.append("\nMedians across jobs:")
        lines.append(md_table(["metric", "median"], list(ti["medians"].items())))
        lines.append(f"\n{ti['note']}\n")

    lines.append("## How to read this")
    lines.append(
        "- Thread replay numbers come from this machine's locally loaded model and a small number of repeats -- "
        "treat them as a screen, not a benchmark score, and never compare across machines/models.\n"
        "- The override rate in judging agreement is a lower bound on disagreement: a judgment the user never "
        "looked at also shows a null user_verdict, identical to one they reviewed and silently accepted.\n"
        "- Timing's later-stage spans (enrichment, statements, thread run) are approximate earliest-to-latest "
        "timestamps on stored rows, not instrumented durations, and enrichment's span is a further approximation "
        "since enrichment answers aren't scoped to a single job.\n"
        "- Autofilled counts undercount total autofill usage: autofilled_from_job_id is cleared once the user "
        "confirms a statement (by design), so a job where every autofilled answer was confirmed shows 0 here."
    )
    return "\n".join(lines)


def print_console_summary(sections: dict) -> None:
    print("=" * 70)
    if "threads" in sections:
        t = sections["threads"]
        print("THREAD REPLAY")
        if t.get("skipped"):
            print(f"  skipped: {t['reason']}")
        else:
            print(f"  {t['note']}")
            for fixture, data in t["fixtures"].items():
                if "error" in data:
                    print(f"  {fixture}: {data['error']}")
                    continue
                print(
                    f"  {fixture}: proposed={data['threads_proposed_avg']} kept={data['threads_kept_avg']} "
                    f"unused={data['unused_statements_avg']} valid_support={data['valid_support_rate_avg']} "
                    f"stability={data['stability_jaccard']:.3f} quote_found={data['quote_found_share']:.3f}"
                )
    if "agreement" in sections:
        o = sections["agreement"]["overall"]
        print("JUDGING AGREEMENT")
        print(
            f"  judgments={o['agreement']['override_rate']['total']} "
            f"overridden={o['agreement']['override_rate']['overridden']} "
            f"rate={o['agreement']['override_rate']['rate']:.3f}"
        )
        print(f"  requirement status: {o['requirements']['status_breakdown']}")
        print(f"  pending with error: {o['requirements']['pending_with_error']} {o['requirements']['error_types']}")
    if "timing" in sections:
        print("TIMING")
        print(f"  medians: {sections['timing']['medians']}")
    print("=" * 70)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--threads", action="store_true")
    parser.add_argument("--agreement", action="store_true")
    parser.add_argument("--timing", action="store_true")
    parser.add_argument("--db", default=DEFAULT_DB_PATH, help="DB path for --agreement/--timing (read-only)")
    parser.add_argument("--log", default=DEFAULT_LOG_PATH, help="judging.log path for --timing")
    parser.add_argument("--fixture", default=None, help="Fixture directory for --threads (default: fixtures/northlight)")
    parser.add_argument("--repeats", type=int, default=3, help="Repeats per fixture for --threads")
    parser.add_argument("--out-dir", default=None)
    args = parser.parse_args()

    run_all = not (args.threads or args.agreement or args.timing)
    sections: dict = {}

    if args.threads or run_all:
        sections["threads"] = run_threads_section(args)
    if args.agreement or run_all:
        sections["agreement"] = run_agreement_section(args)
    if args.timing or run_all:
        sections["timing"] = run_timing_section(args)

    from app.config import settings as app_settings  # safe: read-only attribute access

    job_count = 0
    try:
        conn = open_readonly(args.db)
        job_count = conn.execute("SELECT COUNT(*) AS n FROM job").fetchone()["n"]
        conn.close()
    except sqlite3.OperationalError:
        pass

    header = {
        "date": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "lmstudio_models": probe_lmstudio_models(app_settings.lm_studio_base_url),
        "llm_model": app_settings.llm_model,
        "embed_model": app_settings.embed_model,
        "thread_settings": {
            "n_threads": app_settings.n_threads,
            "min_support": app_settings.min_support,
            "thread_thinking": app_settings.thread_thinking,
        },
        "job_count": job_count,
        "fixture_count": len(sections.get("threads", {}).get("fixtures", {})),
    }

    out_dir = Path(args.out_dir) if args.out_dir else ROOT / "benchmarks" / datetime.now().strftime("%Y%m%d-%H%M%S")
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "report.md").write_text(build_report_md(header, sections), encoding="utf-8")
    (out_dir / "results.json").write_text(
        json.dumps({"header": header, "sections": sections}, indent=2, default=str), encoding="utf-8",
    )

    print_console_summary(sections)
    print(f"\nFull report: {out_dir / 'report.md'}")
    print(f"Raw results: {out_dir / 'results.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
