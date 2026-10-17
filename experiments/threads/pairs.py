"""The three pairing strategies. Each returns a list of (unit_a_id,
unit_b_id) tuples; ids.pair_id() canonicalizes them the same way regardless
of which strategy produced them, so they line up with statements.json."""

import random

from .ids import pair_sort_key
from .vectors import cosine


def fixed_pairs(statement_keys: list[str]) -> list[tuple[str, str]]:
    pairs = []
    for key in statement_keys:
        a, b = key.split("-", 1)
        pairs.append((a, b))
    return pairs


def random_cycle_pairs(unit_ids: list[str], seed: int) -> list[tuple[str, str]]:
    """A seeded Hamiltonian cycle: every unit has exactly 2 neighbors (the
    one before and after it in the shuffled order), so every unit appears
    in exactly 2 pairs and no pair repeats."""
    n = len(unit_ids)
    if n < 3:
        raise ValueError(f"random_cycle needs at least 3 units to avoid a repeated pair, got {n}")
    ids = list(unit_ids)
    random.Random(seed).shuffle(ids)
    return [(ids[i], ids[(i + 1) % n]) for i in range(n)]


def embedding_pairs(
    unit_ids: list[str], embeddings: dict[str, list[float]], pairs_per_unit: int,
) -> list[tuple[str, str]]:
    """Each unit's top `pairs_per_unit` nearest neighbors by cosine
    similarity, symmetrized -- "at least pairs_per_unit" because a unit can
    also be picked by others even after it's filled its own quota."""
    chosen: set[tuple[str, str]] = set()
    for uid in unit_ids:
        sims = sorted(
            ((cosine(embeddings[uid], embeddings[other]), other) for other in unit_ids if other != uid),
            key=lambda t: -t[0],
        )
        for _, other_id in sims[:pairs_per_unit]:
            chosen.add(tuple(sorted([uid, other_id], key=pair_sort_key)))
    return sorted(chosen)
