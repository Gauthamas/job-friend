import unittest

from experiments.threads.checks import (
    agreement_with_expected, control_result, is_strong, jaccard,
    match_threads_by_overlap, mean_stability, quote_exactness, statement_ids_exist,
)
from experiments.threads.config import Config, MaxTokens
from experiments.threads.data_model import Statement, Thread, VerifyResult
from .fakes import FakeLlmClient


def make_cfg(**overrides) -> Config:
    base = dict(
        endpoint="http://localhost:1234/v1", model="m", embed_model="e", temperature=0.2,
        max_tokens=MaxTokens(), request_timeout_s=10, runs=1, strategies=["fixed"],
        pairs_per_unit=2, n_threads=4, min_support=3, statement_source="human",
        seed=1, thinking=False, out_dir="/tmp/out", data_dir="/tmp/data",
    )
    base.update(overrides)
    return Config(**base)


class TestQuoteExactness(unittest.TestCase):
    def test_empty_is_zero(self):
        self.assertEqual(quote_exactness([]), 0.0)

    def test_mixed_exact_and_not(self):
        results = [
            VerifyResult("T1", "U1", "yes", "q", True),
            VerifyResult("T1", "U2", "yes", "q", False),
        ]
        self.assertEqual(quote_exactness(results), 0.5)


class TestStatementIdsExist(unittest.TestCase):
    def test_flags_dangling_ids(self):
        t = Thread(label="T1", idea="x", supporting_statement_ids=["U1-U2", "U5-U6"])
        bad = statement_ids_exist([t], known_pair_ids={"U1-U2"})
        self.assertEqual(bad, {"T1": ["U5-U6"]})

    def test_empty_when_all_known(self):
        t = Thread(label="T1", idea="x", supporting_statement_ids=["U1-U2"])
        self.assertEqual(statement_ids_exist([t], known_pair_ids={"U1-U2"}), {})


class TestIsStrong(unittest.TestCase):
    def test_strong_needs_both_support_and_coverage(self):
        strong = Thread(label="T1", idea="x", supporting_statement_ids=["a", "b", "c"], coverage_yes=4)
        self.assertTrue(is_strong(strong))

    def test_not_strong_if_support_too_low(self):
        weak = Thread(label="T1", idea="x", supporting_statement_ids=["a", "b"], coverage_yes=10)
        self.assertFalse(is_strong(weak))

    def test_not_strong_if_coverage_too_low(self):
        weak = Thread(label="T1", idea="x", supporting_statement_ids=["a", "b", "c", "d"], coverage_yes=1)
        self.assertFalse(is_strong(weak))

    def test_counts_support_after_assign_not_initial_propose(self):
        # Simulates assign_unused appending a 3rd supporting id post-hoc.
        t = Thread(label="T1", idea="x", supporting_statement_ids=["a", "b"], coverage_yes=4)
        self.assertFalse(is_strong(t))
        t.supporting_statement_ids.append("c")  # what assign_unused does
        self.assertTrue(is_strong(t))


class TestJaccardAndStability(unittest.TestCase):
    def test_jaccard_basic(self):
        self.assertEqual(jaccard({1, 2, 3}, {2, 3, 4}), 2 / 4)

    def test_jaccard_both_empty_is_one(self):
        self.assertEqual(jaccard(set(), set()), 1.0)

    def test_match_threads_greedy_pairs_best_overlap_first(self):
        a1 = Thread("T1", "x", ["p1", "p2"])
        a2 = Thread("T2", "y", ["p5"])
        b1 = Thread("T1", "x", ["p1", "p2", "p3"])
        b2 = Thread("T2", "y", ["p5", "p6"])
        matches = match_threads_by_overlap([a1, a2], [b1, b2])
        pairs = {(m[0].label, m[1].label) for m in matches}
        self.assertEqual(pairs, {("T1", "T1"), ("T2", "T2")})

    def test_mean_stability_identical_runs_is_one(self):
        run = [Thread("T1", "x", ["p1", "p2", "p3"])]
        self.assertEqual(mean_stability([run, [Thread("T1", "x", ["p1", "p2", "p3"])]]), 1.0)

    def test_mean_stability_single_run_is_zero(self):
        run = [Thread("T1", "x", ["p1"])]
        self.assertEqual(mean_stability([run]), 0.0)

    def test_mean_stability_disjoint_runs_is_zero(self):
        a = [Thread("T1", "x", ["p1", "p2"])]
        b = [Thread("T1", "x", ["p3", "p4"])]
        self.assertEqual(mean_stability([a, b]), 0.0)


class TestControlResult(unittest.TestCase):
    def test_pass_when_model_returns_no_threads(self):
        llm = FakeLlmClient()
        llm.queue_json({"threads": []})
        statements = [
            Statement("U1-U2", "U1", "U2", "shares nothing", "human", "S1"),
            Statement("U3-U4", "U3", "U4", "also unrelated", "human", "S2"),
            Statement("U5-U6", "U5", "U6", "still unrelated", "human", "S3"),
        ]
        cfg = make_cfg(n_threads=4, min_support=3)
        outcome = control_result(statements, cfg, llm, template="{statements_block}")
        self.assertTrue(outcome.passed)

    def test_fail_when_model_finds_a_thread_meeting_the_run_bar(self):
        llm = FakeLlmClient()
        llm.queue_json({"threads": [{"idea": "false positive", "supporting_statement_ids": ["S1", "S2", "S3"]}]})
        statements = [
            Statement("U1-U2", "U1", "U2", "a", "human", "S1"),
            Statement("U3-U4", "U3", "U4", "b", "human", "S2"),
            Statement("U5-U6", "U5", "U6", "c", "human", "S3"),
        ]
        cfg = make_cfg(n_threads=4, min_support=3)
        outcome = control_result(statements, cfg, llm, template="{statements_block}")
        self.assertFalse(outcome.passed)

    def test_uses_the_runs_min_support_not_a_stricter_one(self):
        # min_support=3 but the control only yields 2 real statements after
        # the model cites one unknown id -- should NOT pass by accident
        # just because support fell short of this cfg's bar; it should be
        # evaluated with the SAME bar as everything else, no special-casing.
        llm = FakeLlmClient()
        llm.queue_json({"threads": [{"idea": "x", "supporting_statement_ids": ["S1", "S2"]}]})
        statements = [
            Statement("U1-U2", "U1", "U2", "a", "human", "S1"),
            Statement("U3-U4", "U3", "U4", "b", "human", "S2"),
        ]
        cfg = make_cfg(n_threads=4, min_support=3)
        outcome = control_result(statements, cfg, llm, template="{statements_block}")
        self.assertTrue(outcome.passed)  # 2 < min_support=3 -> dropped -> no threads -> pass


class TestAgreementWithExpected(unittest.TestCase):
    def test_perfect_agreement(self):
        expected = {"U1-U2": "resilience", "U3-U4": "resilience", "U5-U6": "mentorship"}
        run_threads = [
            Thread("T1", "x", ["U1-U2", "U3-U4"]),
            Thread("T2", "y", ["U5-U6"]),
        ]
        self.assertEqual(agreement_with_expected(expected, run_threads), 1.0)

    def test_total_disagreement(self):
        expected = {"U1-U2": "resilience", "U3-U4": "mentorship"}
        run_threads = [Thread("T1", "x", ["U1-U2", "U3-U4"])]  # run says "same", expected says "different"
        self.assertEqual(agreement_with_expected(expected, run_threads), 0.0)

    def test_fewer_than_two_expected_ids_is_vacuously_one(self):
        self.assertEqual(agreement_with_expected({"U1-U2": "a"}, []), 1.0)


if __name__ == "__main__":
    unittest.main()
