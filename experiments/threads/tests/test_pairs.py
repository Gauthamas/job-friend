import unittest
from collections import Counter

from experiments.threads.ids import pair_id, pair_sort_key, split_pair_id
from experiments.threads.pairs import embedding_pairs, fixed_pairs, random_cycle_pairs


class TestIds(unittest.TestCase):
    def test_pair_id_orders_by_trailing_number(self):
        self.assertEqual(pair_id("U4", "U3"), "U3-U4")
        self.assertEqual(pair_id("U3", "U4"), "U3-U4")

    def test_pair_id_double_digit_sorts_numerically_not_lexically(self):
        # lexical sort would put "U10" before "U2"
        self.assertEqual(pair_id("U10", "U2"), "U2-U10")

    def test_split_pair_id_round_trips(self):
        self.assertEqual(split_pair_id(pair_id("U4", "U3")), ("U3", "U4"))

    def test_sort_key_handles_no_trailing_number(self):
        # must not raise
        pair_sort_key("cover_letter")


class TestFixedPairs(unittest.TestCase):
    def test_reads_pairs_from_statement_keys(self):
        pairs = fixed_pairs(["U3-U4", "U9-U10"])
        self.assertEqual(pairs, [("U3", "U4"), ("U9", "U10")])


class TestRandomCyclePairs(unittest.TestCase):
    def test_every_unit_appears_in_exactly_two_pairs(self):
        unit_ids = [f"U{i}" for i in range(1, 11)]
        pairs = random_cycle_pairs(unit_ids, seed=42)
        self.assertEqual(len(pairs), 10)
        counts = Counter()
        for a, b in pairs:
            counts[a] += 1
            counts[b] += 1
        self.assertTrue(all(c == 2 for c in counts.values()), counts)

    def test_no_repeated_pair_and_no_self_pair(self):
        unit_ids = [f"U{i}" for i in range(1, 11)]
        pairs = random_cycle_pairs(unit_ids, seed=7)
        canonical = [pair_id(a, b) for a, b in pairs]
        self.assertEqual(len(canonical), len(set(canonical)))
        self.assertTrue(all(a != b for a, b in pairs))

    def test_seed_is_deterministic(self):
        unit_ids = [f"U{i}" for i in range(1, 11)]
        self.assertEqual(random_cycle_pairs(unit_ids, seed=1), random_cycle_pairs(unit_ids, seed=1))

    def test_different_seeds_usually_differ(self):
        unit_ids = [f"U{i}" for i in range(1, 11)]
        self.assertNotEqual(random_cycle_pairs(unit_ids, seed=1), random_cycle_pairs(unit_ids, seed=2))

    def test_fewer_than_three_units_raises(self):
        with self.assertRaises(ValueError):
            random_cycle_pairs(["U1", "U2"], seed=1)


class TestEmbeddingPairs(unittest.TestCase):
    def test_every_unit_gets_at_least_pairs_per_unit(self):
        # 4 orthogonal-ish "clusters" of units so nearest-neighbor picks are
        # predictable without needing a real model.
        unit_ids = ["A1", "A2", "B1", "B2", "C1"]
        embeddings = {
            "A1": [1.0, 0.0, 0.0], "A2": [0.9, 0.1, 0.0],
            "B1": [0.0, 1.0, 0.0], "B2": [0.0, 0.9, 0.1],
            "C1": [0.0, 0.0, 1.0],
        }
        pairs = embedding_pairs(unit_ids, embeddings, pairs_per_unit=2)
        counts = Counter()
        for a, b in pairs:
            counts[a] += 1
            counts[b] += 1
        for uid in unit_ids:
            self.assertGreaterEqual(counts[uid], 2, f"{uid} appears in {counts[uid]} pairs")

    def test_no_pair_repeated(self):
        unit_ids = ["A1", "A2", "B1"]
        embeddings = {"A1": [1.0, 0.0], "A2": [0.9, 0.1], "B1": [0.0, 1.0]}
        pairs = embedding_pairs(unit_ids, embeddings, pairs_per_unit=2)
        self.assertEqual(len(pairs), len(set(pairs)))


if __name__ == "__main__":
    unittest.main()
