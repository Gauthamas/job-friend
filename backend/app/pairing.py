"""Milestone 3: the pair builder. No LLM calls --
embeddings already written by the enrichment/commit paths are reused, never
recomputed here."""

import sqlite3
from itertools import combinations
from typing import NamedTuple

from app.config import settings
from app.vectors import cosine_similarity, from_blob

# §6: "up to four embedded fields (text, context, contribution, outcome)" --
# skills vectors exist too but are deliberately not part of pair scoring.
PAIR_FIELDS = ("text", "context", "contribution", "outcome")


class RemovedPair(NamedTuple):
    unit_a_id: int
    unit_b_id: int
    had_written_statement: bool


def matched_unit_ids_for_job(conn: sqlite3.Connection, job_id: int) -> list[int]:
    """§6's "items": units with an effective match verdict on at least one
    of this job's requirements -- the same set the enrichment screen (§5)
    lists, which by the time Continue is clickable are all fully enriched."""
    rows = conn.execute(
        "SELECT DISTINCT u.id FROM unit u "
        "JOIN role ro ON ro.id = u.role_id "
        "JOIN judgment j ON j.unit_id = u.id "
        "JOIN requirement r ON r.id = j.requirement_id "
        "WHERE r.job_id = ? AND r.deleted = 0 AND u.deleted = 0 "
        "AND u.discarded_at IS NULL AND ro.discarded_at IS NULL "
        "AND COALESCE(j.user_verdict, j.model_verdict) = 'match' "
        "ORDER BY u.id",
        (job_id,),
    ).fetchall()
    return [row["id"] for row in rows]


def _unit_vectors(conn: sqlite3.Connection, unit_ids: list[int]) -> dict[int, list]:
    vectors: dict[int, list] = {uid: [] for uid in unit_ids}
    if not unit_ids:
        return vectors
    unit_placeholders = ",".join("?" * len(unit_ids))
    field_placeholders = ",".join("?" * len(PAIR_FIELDS))
    rows = conn.execute(
        f"SELECT unit_id, vector FROM unit_embedding "
        f"WHERE unit_id IN ({unit_placeholders}) AND field IN ({field_placeholders})",
        (*unit_ids, *PAIR_FIELDS),
    ).fetchall()
    for row in rows:
        vectors[row["unit_id"]].append(from_blob(row["vector"]))
    return vectors


def _pair_score(vectors_a: list, vectors_b: list) -> float:
    """§6: "max cosine similarity across all field vectors of the two
    units" -- every field vector of A against every field vector of B."""
    if not vectors_a or not vectors_b:
        return 0.0
    return max(cosine_similarity(va, vb) for va in vectors_a for vb in vectors_b)


def compute_pair_scores(conn: sqlite3.Connection, unit_ids: list[int]) -> dict[tuple[int, int], float]:
    """Every pairwise score among unit_ids, keyed (smaller_id, larger_id)."""
    vectors = _unit_vectors(conn, unit_ids)
    ordered = sorted(unit_ids)
    return {(a, b): _pair_score(vectors[a], vectors[b]) for a, b in combinations(ordered, 2)}


def select_pairs(
    unit_ids: list[int], scores: dict[tuple[int, int], float],
    pair_k: int, pair_n: int | None, pair_global_on: bool,
) -> list[tuple[int, int, float]]:
    """§6 rule: for each unit, its top pair_k partners (ties broken by the
    partner's id, ascending, for determinism); union; optionally add the
    global top pair_n pairs not already included; fewer than 3 units means
    every pair. Returns (unit_a_id, unit_b_id, score) sorted by ids."""
    ordered = sorted(unit_ids)
    if len(ordered) < 3:
        return sorted((a, b, s) for (a, b), s in scores.items())

    selected: set[tuple[int, int]] = set()
    for uid in ordered:
        partners = []
        for other in ordered:
            if other == uid:
                continue
            key = (uid, other) if uid < other else (other, uid)
            partners.append((scores[key], other, key))
        partners.sort(key=lambda t: (-t[0], t[1]))
        for _, _, key in partners[:pair_k]:
            selected.add(key)

    if pair_global_on:
        n_global = pair_n if pair_n is not None else len(ordered)
        by_score = sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))
        added = 0
        for key, _ in by_score:
            if added >= n_global:
                break
            if key in selected:
                continue
            selected.add(key)
            added += 1

    return sorted((a, b, scores[(a, b)]) for (a, b) in selected)


def cap_pairs(
    pairs: list[tuple[int, int, float]], answered_keys: set[tuple[int, int]], pair_max: int,
) -> list[tuple[int, int, float]]:
    """Caps the selection at pair_max, keeping every already-answered
    (written/none) pair regardless of score -- those count toward the cap,
    but never get dropped to make room, so the total can exceed pair_max
    when there are more answered pairs than that. Among the rest, keeps the
    highest-scoring ones, ties broken by unit ids ascending (deterministic)."""
    if len(pairs) <= pair_max:
        return pairs
    always_keep = [p for p in pairs if (p[0], p[1]) in answered_keys]
    if len(always_keep) >= pair_max:
        return sorted(always_keep)
    rest = [p for p in pairs if (p[0], p[1]) not in answered_keys]
    rest.sort(key=lambda t: (-t[2], t[0], t[1]))
    remaining_slots = pair_max - len(always_keep)
    return sorted(always_keep + rest[:remaining_slots])


def build_and_save_pairs(conn: sqlite3.Connection, job_id: int) -> list[RemovedPair]:
    """Builds the current pair set for job_id and reconciles it against
    what's already stored (§6 rule 5: idempotent rebuild). A pair still in
    the new set keeps its row and statement untouched except for a
    refreshed score (embeddings may have changed since it was last built);
    a pair no longer in the set is deleted along with its statement.
    Returns the pairs that got removed, so the caller can warn about any
    that had a written statement."""
    unit_ids = matched_unit_ids_for_job(conn, job_id)
    scores = compute_pair_scores(conn, unit_ids)
    candidate_pairs = select_pairs(unit_ids, scores, settings.pair_k, settings.pair_n, settings.pair_global_on)

    answered_keys = {
        (row["unit_a_id"], row["unit_b_id"]) for row in conn.execute(
            "SELECT p.unit_a_id, p.unit_b_id FROM pair p JOIN statement s ON s.pair_id = p.id "
            "WHERE p.job_id = ? AND s.status IN ('written', 'none')",
            (job_id,),
        ).fetchall()
    }
    new_pairs = cap_pairs(candidate_pairs, answered_keys, settings.pair_max)
    new_keys = {(a, b) for a, b, _ in new_pairs}

    existing = conn.execute(
        "SELECT p.id, p.unit_a_id, p.unit_b_id, s.status FROM pair p "
        "LEFT JOIN statement s ON s.pair_id = p.id WHERE p.job_id = ?",
        (job_id,),
    ).fetchall()

    removed: list[RemovedPair] = []
    for row in existing:
        key = (row["unit_a_id"], row["unit_b_id"])
        if key in new_keys:
            continue
        removed.append(RemovedPair(row["unit_a_id"], row["unit_b_id"], row["status"] == "written"))
        conn.execute("DELETE FROM statement WHERE pair_id = ?", (row["id"],))
        conn.execute("DELETE FROM pair WHERE id = ?", (row["id"],))

    model = settings.embed_model
    for unit_a_id, unit_b_id, score in new_pairs:
        conn.execute(
            "INSERT INTO pair (job_id, unit_a_id, unit_b_id, score, model) VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT(job_id, unit_a_id, unit_b_id) DO UPDATE SET score = excluded.score, model = excluded.model",
            (job_id, unit_a_id, unit_b_id, score, model),
        )
        pair_id = conn.execute(
            "SELECT id FROM pair WHERE job_id = ? AND unit_a_id = ? AND unit_b_id = ?",
            (job_id, unit_a_id, unit_b_id),
        ).fetchone()["id"]
        conn.execute(
            "INSERT INTO statement (pair_id, status) VALUES (?, 'unanswered') "
            "ON CONFLICT(pair_id) DO NOTHING",
            (pair_id,),
        )

    conn.commit()
    return removed
