"""Milestone 3: pure pair-scoring/selection
functions in app/pairing.py, with small hand-rolled vectors so expected
scores and selections are easy to verify by hand."""

import numpy as np
import pytest

from app.pairing import _pair_score, cap_pairs, select_pairs


def test_pair_score_is_the_max_over_all_field_combinations():
    # A has two field vectors, B has two -- the max similarity must come
    # from the BEST-matching pair of fields, not an average or the first.
    vectors_a = [np.array([1.0, 0.0]), np.array([0.0, 1.0])]
    vectors_b = [np.array([0.0, 1.0]), np.array([-1.0, 0.0])]
    # a[0] vs b[0] = 0, a[0] vs b[1] = -1, a[1] vs b[0] = 1 (best), a[1] vs b[1] = 0
    assert _pair_score(vectors_a, vectors_b) == pytest.approx(1.0)


def test_pair_score_is_zero_with_no_vectors_on_either_side():
    assert _pair_score([], [np.array([1.0, 0.0])]) == 0.0
    assert _pair_score([np.array([1.0, 0.0])], []) == 0.0


# --- select_pairs ---

def test_fewer_than_three_units_selects_every_pair():
    # pair_k=0 and global off would normally select nothing -- but fewer
    # than 3 units always means every pair regardless of k/n/global.
    result = select_pairs([1, 2], {(1, 2): 0.1}, pair_k=0, pair_n=0, pair_global_on=False)
    assert result == [(1, 2, 0.1)]


def test_exactly_three_units_follows_the_normal_rule_not_the_shortcut():
    # The "fewer than 3" shortcut must not fire at exactly 3 -- with
    # pair_k=0 and global off, nothing should be selected.
    scores = {(1, 2): 0.1, (1, 3): 0.2, (2, 3): 0.9}
    result = select_pairs([1, 2, 3], scores, pair_k=0, pair_n=0, pair_global_on=False)
    assert result == []


def test_every_unit_ends_up_in_at_least_pair_k_pairs():
    # 5 units, a deliberately lopsided score matrix so the "each unit's
    # own top-k" rule is the only thing that can save a weak unit (4) from
    # being left out entirely.
    ids = [1, 2, 3, 4, 5]
    scores = {}
    for a, b in [(1, 2), (1, 3), (1, 5), (2, 3), (2, 5), (3, 5)]:
        scores[(a, b)] = 0.9
    for key in [(1, 4), (2, 4), (3, 4), (4, 5)]:
        scores[key] = 0.01  # unit 4 is weakly related to everything

    result = select_pairs(ids, scores, pair_k=2, pair_n=0, pair_global_on=False)
    pairs_by_unit = {uid: 0 for uid in ids}
    for a, b, _ in result:
        pairs_by_unit[a] += 1
        pairs_by_unit[b] += 1
    for uid in ids:
        assert pairs_by_unit[uid] >= 2, f"unit {uid} has only {pairs_by_unit[uid]} pairs"


def test_a_b_and_b_a_are_the_same_pair_never_duplicated():
    ids = [1, 2, 3, 4]
    scores = {
        (1, 2): 0.9, (1, 3): 0.9, (1, 4): 0.9,
        (2, 3): 0.9, (2, 4): 0.9, (3, 4): 0.9,
    }
    result = select_pairs(ids, scores, pair_k=3, pair_n=0, pair_global_on=False)
    keys = [(a, b) for a, b, _ in result]
    assert len(keys) == len(set(keys))  # no duplicates
    for a, b in keys:
        assert a < b  # always smaller id first


def test_result_is_deterministic_and_sorted_by_ids():
    ids = [3, 1, 4, 2]
    scores = {
        (1, 2): 0.5, (1, 3): 0.5, (1, 4): 0.5,
        (2, 3): 0.5, (2, 4): 0.5, (3, 4): 0.5,
    }
    result1 = select_pairs(ids, scores, pair_k=2, pair_n=1, pair_global_on=True)
    result2 = select_pairs(list(reversed(ids)), scores, pair_k=2, pair_n=1, pair_global_on=True)
    assert result1 == result2
    assert result1 == sorted(result1)


def test_global_top_n_adds_pairs_not_already_covered_by_per_unit_top_k():
    # 4 units, two disjoint pairs {1,2} and {3,4} each scoring 0.9 (so
    # pair_k=1 locks in exactly those two pairs for every unit), plus a
    # single cross pair (2,3)=0.5 -- higher than every other remaining
    # pair (0.1) but lower than any unit's own top-1, so per-unit
    # selection alone never picks it. global_on is what guarantees the
    # single best *remaining* pair still gets included.
    ids = [1, 2, 3, 4]
    scores = {(1, 2): 0.9, (3, 4): 0.9, (2, 3): 0.5, (1, 3): 0.1, (1, 4): 0.1, (2, 4): 0.1}

    without_global = select_pairs(ids, scores, pair_k=1, pair_n=0, pair_global_on=False)
    assert without_global == [(1, 2, 0.9), (3, 4, 0.9)]

    with_global = select_pairs(ids, scores, pair_k=1, pair_n=1, pair_global_on=True)
    assert with_global == [(1, 2, 0.9), (2, 3, 0.5), (3, 4, 0.9)]


# --- cap_pairs (pair_max) ---

def test_cap_keeps_highest_scoring_up_to_pair_max():
    pairs = [(1, 2, 0.5), (1, 3, 0.9), (2, 3, 0.1), (2, 4, 0.7)]
    result = cap_pairs(pairs, answered_keys=set(), pair_max=2)
    assert result == [(1, 3, 0.9), (2, 4, 0.7)]  # top 2 scores: 0.9, 0.7


def test_cap_noop_when_under_the_limit():
    pairs = [(1, 2, 0.5), (1, 3, 0.9)]
    assert cap_pairs(pairs, answered_keys=set(), pair_max=5) == pairs


def test_cap_ties_broken_by_unit_ids_ascending():
    pairs = [(1, 2, 0.5), (1, 3, 0.5), (2, 3, 0.5)]
    result = cap_pairs(pairs, answered_keys=set(), pair_max=2)
    assert result == [(1, 2, 0.5), (1, 3, 0.5)]  # equal scores -> lower ids win


def test_cap_never_drops_an_answered_pair():
    pairs = [(1, 2, 0.1), (1, 3, 0.9), (2, 3, 0.5)]
    # (1,2) scores lowest but is answered -- must survive the cap=1.
    result = cap_pairs(pairs, answered_keys={(1, 2)}, pair_max=1)
    assert result == [(1, 2, 0.1)]


def test_cap_answered_pairs_exceeding_pair_max_are_all_kept():
    pairs = [(1, 2, 0.1), (1, 3, 0.2), (2, 3, 0.9)]
    result = cap_pairs(pairs, answered_keys={(1, 2), (1, 3), (2, 3)}, pair_max=1)
    assert result == pairs  # all 3 answered -- cap of 1 can't drop any of them


def test_cap_is_deterministic_regardless_of_input_order():
    pairs = [(1, 2, 0.5), (1, 3, 0.9), (2, 3, 0.1), (2, 4, 0.7)]
    result1 = cap_pairs(pairs, answered_keys=set(), pair_max=2)
    result2 = cap_pairs(list(reversed(pairs)), answered_keys=set(), pair_max=2)
    assert result1 == result2


def test_changing_pair_max_changes_the_set():
    pairs = [(1, 2, 0.5), (1, 3, 0.9), (2, 3, 0.1), (2, 4, 0.7)]
    small = cap_pairs(pairs, answered_keys=set(), pair_max=1)
    large = cap_pairs(pairs, answered_keys=set(), pair_max=3)
    assert small == [(1, 3, 0.9)]
    assert len(large) == 3
    assert small != large
