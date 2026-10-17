"""Read-only comparison: re-judges a sample of already-'done' requirements
with thinking OFF, using each one's existing shortlist (the same unit ids
already in its judgment rows) and the units' CURRENT text, then reports how
the model's own verdicts and derived requirement verdicts changed versus
whatever is already stored.

Opens the real database in SQLite's own read-only mode (`mode=ro`), so a
stray write anywhere in this script raises instead of silently landing on
disk -- it never calls .commit() either. The only network calls are to the
local LM Studio judge endpoint (one per sampled requirement, single
attempt, no retry -- this is a measurement script, not production judging).

Usage (needs LM Studio running):
    python scripts/compare_judge_thinking.py [--n 20] [--out out.json] [--db-path PATH]
"""

import argparse
import dataclasses
import json
import sqlite3
import sys
import time
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent / "backend"
sys.path.insert(0, str(BACKEND_DIR))

from app.config import settings  # noqa: E402
from app.judge_input import build_candidate_haystacks, build_judge_message, format_unit_id  # noqa: E402
from app.llm.base import LlmTimeout  # noqa: E402
from app.llm.judge_validation import validate_judge  # noqa: E402
from app.llm.lmstudio_client import LMStudioClient  # noqa: E402
from app.llm.tasks import build_judge_task  # noqa: E402
from app.shortlist import Candidate, _parse_skills  # noqa: E402

MODEL_VERDICTS = ("match", "weak", "none")


def open_readonly(db_path: str) -> sqlite3.Connection:
    # uri=True + mode=ro: SQLite itself refuses any write against this
    # connection, not just "we happen not to call commit".
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _evenly_spaced_indices(count: int, k: int) -> list[int]:
    if k <= 0 or count == 0:
        return []
    if k >= count:
        return list(range(count))
    step = count / k
    return sorted({int(i * step) for i in range(k)})


def sample_done_requirement_ids(conn: sqlite3.Connection, n: int) -> list[int]:
    """Evenly sampled across jobs: N split as equally as possible across
    every job that has at least one 'done' requirement, and evenly spaced
    (by sort_order) within each job rather than just its first few."""
    job_ids = [
        r["job_id"]
        for r in conn.execute(
            "SELECT DISTINCT job_id FROM requirement WHERE status = 'done' AND deleted = 0 ORDER BY job_id"
        )
    ]
    if not job_ids:
        return []

    base, remainder = divmod(n, len(job_ids))
    sampled: list[int] = []
    for i, job_id in enumerate(job_ids):
        quota = base + (1 if i < remainder else 0)
        if quota <= 0:
            continue
        ids = [
            r["id"]
            for r in conn.execute(
                "SELECT id FROM requirement WHERE job_id = ? AND status = 'done' AND deleted = 0 "
                "ORDER BY sort_order",
                (job_id,),
            )
        ]
        for idx in _evenly_spaced_indices(len(ids), quota):
            sampled.append(ids[idx])
    return sampled[:n]


def _candidates_for_requirement(conn: sqlite3.Connection, requirement_id: int) -> list[Candidate]:
    """Same query as app.judging._candidates_for_requirement: the existing
    shortlist (judgment rows already attached, excluding manually added
    units), with each unit's CURRENT text -- no snapshot."""
    rows = conn.execute(
        "SELECT j.unit_id, j.score, u.text, u.context, u.contribution, u.outcome, u.skills_json "
        "FROM judgment j JOIN unit u ON j.unit_id = u.id "
        "WHERE j.requirement_id = ? AND j.added_by_user = 0 ORDER BY j.score DESC",
        (requirement_id,),
    ).fetchall()
    return [
        Candidate(
            unit_id=r["unit_id"], text=r["text"], context=r["context"],
            contribution=r["contribution"], outcome=r["outcome"],
            skills=_parse_skills(r["skills_json"]), score=r["score"] or 0.0,
        )
        for r in rows
    ]


def _old_model_verdicts(conn: sqlite3.Connection, requirement_id: int) -> dict[int, str]:
    rows = conn.execute(
        "SELECT unit_id, model_verdict FROM judgment WHERE requirement_id = ? AND added_by_user = 0",
        (requirement_id,),
    ).fetchall()
    return {r["unit_id"]: (r["model_verdict"] or "none") for r in rows}


def derive_from_model_verdicts(verdicts: dict[int, str]) -> str:
    """Requirement-level rollup from MODEL verdicts alone (ignores
    user_verdict corrections) -- this script compares the model's own
    output across settings, not the user-corrected end state."""
    values = verdicts.values()
    if "match" in values:
        return "match"
    if "weak" in values:
        return "weak"
    return "gap"


def judge_once_no_thinking(
    llm_client: LMStudioClient, requirement_id: int, requirement_text: str, candidates: list[Candidate],
) -> dict:
    """One judge call, thinking off, no retry. Returns a dict with
    new_verdicts (unit_id -> verdict), seconds, prompt_tokens,
    completion_tokens, error (None on success)."""
    if not candidates:
        return {"new_verdicts": {}, "seconds": 0.0, "prompt_tokens": 0, "completion_tokens": 0, "error": None}

    haystacks = build_candidate_haystacks(candidates)
    candidate_ids = set(haystacks.keys())
    message = build_judge_message(requirement_id, requirement_text, candidates)
    task = build_judge_task(thinking=False)

    try:
        raw, metrics = llm_client.complete(task, message)
    except LlmTimeout as e:
        return {
            "new_verdicts": {}, "seconds": 0.0, "prompt_tokens": 0, "completion_tokens": 0,
            "error": f"timeout: {e}",
        }

    result = {
        "new_verdicts": {}, "seconds": metrics.seconds,
        "prompt_tokens": metrics.prompt_tokens, "completion_tokens": metrics.completion_tokens,
        "error": None,
    }
    try:
        parsed = task.response_model.model_validate_json(raw)
    except Exception as e:  # noqa: BLE001 -- report, don't crash the batch
        result["error"] = f"invalid JSON: {e}"
        return result

    errors = validate_judge(parsed, candidate_ids=candidate_ids, haystacks=haystacks)
    if errors:
        result["error"] = "; ".join(errors)
        return result

    listed = {u.id: u.v for u in parsed.units}
    new_verdicts = {}
    for c in candidates:
        new_verdicts[c.unit_id] = listed.get(format_unit_id(c.unit_id), "none")
    result["new_verdicts"] = new_verdicts
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--n", type=int, default=20, help="number of requirements to sample (default 20)")
    parser.add_argument("--out", type=Path, default=Path("compare_judge_thinking.json"))
    parser.add_argument("--db-path", default=settings.db_path)
    args = parser.parse_args()

    conn = open_readonly(args.db_path)
    try:
        requirement_ids = sample_done_requirement_ids(conn, args.n)
        if not requirement_ids:
            print("No 'done' requirements found -- nothing to compare.")
            return

        llm_client = LMStudioClient(settings.lm_studio_base_url, settings.llm_model)
        results = []

        for requirement_id in requirement_ids:
            row = conn.execute(
                "SELECT id, job_id, text FROM requirement WHERE id = ?", (requirement_id,)
            ).fetchone()
            candidates = _candidates_for_requirement(conn, requirement_id)
            old_verdicts = _old_model_verdicts(conn, requirement_id)

            outcome = judge_once_no_thinking(llm_client, requirement_id, row["text"], candidates)

            old_derived = derive_from_model_verdicts(old_verdicts)
            new_derived = (
                derive_from_model_verdicts(outcome["new_verdicts"]) if outcome["error"] is None else None
            )

            units = []
            for unit_id in old_verdicts:
                units.append({
                    "unit_id": unit_id,
                    "old_verdict": old_verdicts[unit_id],
                    "new_verdict": outcome["new_verdicts"].get(unit_id) if outcome["error"] is None else None,
                })

            results.append({
                "requirement_id": requirement_id,
                "job_id": row["job_id"],
                "text": row["text"],
                "old_derived_verdict": old_derived,
                "new_derived_verdict": new_derived,
                "seconds": outcome["seconds"],
                "prompt_tokens": outcome["prompt_tokens"],
                "completion_tokens": outcome["completion_tokens"],
                "error": outcome["error"],
                "units": units,
            })
            result_label = new_derived if new_derived else f"ERROR: {outcome['error']}"
            print(f"requirement {requirement_id} (job {row['job_id']}): "
                  f"{old_derived} -> {result_label} ({outcome['seconds']:.1f}s)")

    finally:
        conn.close()

    args.out.write_text(json.dumps(results, indent=2), encoding="utf-8")

    # --- summary ---
    completed = [r for r in results if r["error"] is None]
    all_units = [u for r in completed for u in r["units"]]
    agreeing_units = [u for u in all_units if u["old_verdict"] == u["new_verdict"]]

    print()
    print(f"Sampled {len(results)} requirements ({len(completed)} judged successfully, "
          f"{len(results) - len(completed)} failed/timed out).")
    if all_units:
        print(f"Per-unit verdict agreement: {len(agreeing_units)}/{len(all_units)} "
              f"({100 * len(agreeing_units) / len(all_units):.1f}%)")
        for v in MODEL_VERDICTS:
            old_v_units = [u for u in all_units if u["old_verdict"] == v]
            if not old_v_units:
                continue
            same = sum(1 for u in old_v_units if u["new_verdict"] == v)
            print(f"  old={v}: {same}/{len(old_v_units)} unchanged")
    else:
        print("No units to compare (every sampled requirement had an empty shortlist).")

    changed = [r for r in completed if r["old_derived_verdict"] != r["new_derived_verdict"]]
    print(f"Requirements whose derived verdict (match/weak/gap) changed: {len(changed)}/{len(completed)}")

    if completed:
        avg_seconds = sum(r["seconds"] for r in completed) / len(completed)
        print(f"Average seconds per call: {avg_seconds:.2f}s")

    print(f"\nWrote {args.out}")


if __name__ == "__main__":
    main()
