import unittest

from experiments.threads.config import Config, MaxTokens
from experiments.threads.data_model import Statement
from experiments.threads.pipeline import assign_labels, assign_unused, map_units, propose_threads
from .fakes import FakeLlmClient


def make_cfg(**overrides) -> Config:
    base = dict(
        endpoint="http://localhost:1234/v1", model="m", embed_model="e", temperature=0.2,
        max_tokens=MaxTokens(), request_timeout_s=10, runs=1, strategies=["fixed"],
        pairs_per_unit=2, n_threads=4, min_support=2, statement_source="human",
        seed=1, thinking=False, out_dir="/tmp/out", data_dir="/tmp/data",
    )
    base.update(overrides)
    return Config(**base)


def make_statements(n: int) -> list[Statement]:
    return [Statement(f"U{i}-U{i+1}", f"U{i}", f"U{i+1}", f"text {i}", "human") for i in range(1, n + 1)]


class TestAssignLabels(unittest.TestCase):
    def test_labels_are_sequential_starting_at_s1(self):
        statements = make_statements(3)
        labeled = assign_labels(statements)
        self.assertEqual([s.s_label for s in labeled], ["S1", "S2", "S3"])

    def test_none_statements_get_no_label_and_are_excluded(self):
        statements = make_statements(2)
        statements.append(Statement("U9-U10", "U9", "U10", None, "human_none"))
        labeled = assign_labels(statements)
        self.assertEqual(len(labeled), 2)  # the None one is excluded
        self.assertEqual(statements[2].s_label, "")  # untouched


class TestProposeThreads(unittest.TestCase):
    def test_shows_s_labels_to_the_model_not_pair_ids(self):
        llm = FakeLlmClient()
        llm.queue_json({"threads": []})
        labeled = assign_labels(make_statements(3))
        propose_threads(labeled, n_threads=4, min_support=2, llm=llm, template="{statements_block}", cfg=make_cfg())
        prompt = llm.calls[0]["user_message"]
        self.assertIn("S1:", prompt)
        self.assertNotIn("U1-U2", prompt)

    def test_maps_s_labels_back_to_pair_ids(self):
        llm = FakeLlmClient()
        llm.queue_json({"threads": [{"idea": "resilience", "supporting_statement_ids": ["S1", "S2"]}]})
        labeled = assign_labels(make_statements(3))
        result = propose_threads(labeled, n_threads=4, min_support=2, llm=llm, template="{statements_block}", cfg=make_cfg())
        self.assertEqual(result.threads[0].supporting_statement_ids, ["U1-U2", "U2-U3"])

    def test_drops_thread_under_min_support(self):
        llm = FakeLlmClient()
        llm.queue_json({"threads": [{"idea": "weak", "supporting_statement_ids": ["S1"]}]})
        labeled = assign_labels(make_statements(3))
        result = propose_threads(labeled, n_threads=4, min_support=2, llm=llm, template="{statements_block}", cfg=make_cfg())
        self.assertEqual(result.threads, [])
        self.assertEqual(result.dropped_under_support, 1)

    def test_unknown_s_label_is_dropped_and_recorded_not_fatal(self):
        llm = FakeLlmClient()
        llm.queue_json({"threads": [{"idea": "x", "supporting_statement_ids": ["S1", "S2", "S99"]}]})
        labeled = assign_labels(make_statements(3))
        result = propose_threads(labeled, n_threads=4, min_support=2, llm=llm, template="{statements_block}", cfg=make_cfg())
        self.assertEqual(result.threads[0].supporting_statement_ids, ["U1-U2", "U2-U3"])
        self.assertEqual(result.dropped_unknown_ids, ["S99"])

    def test_failed_call_returns_no_threads(self):
        llm = FakeLlmClient()
        llm.queue_failure()
        labeled = assign_labels(make_statements(3))
        result = propose_threads(labeled, n_threads=4, min_support=2, llm=llm, template="{statements_block}", cfg=make_cfg())
        self.assertEqual(result.threads, [])
        self.assertFalse(result.call.ok)

    def test_caps_at_n_threads(self):
        llm = FakeLlmClient()
        llm.queue_json({"threads": [
            {"idea": f"idea{i}", "supporting_statement_ids": ["S1", "S2"]} for i in range(5)
        ]})
        labeled = assign_labels(make_statements(3))
        result = propose_threads(labeled, n_threads=2, min_support=2, llm=llm, template="{statements_block}", cfg=make_cfg())
        self.assertEqual(len(result.threads), 2)


class TestAssignUnused(unittest.TestCase):
    def test_unused_statement_attached_to_chosen_thread(self):
        from experiments.threads.data_model import Thread
        llm = FakeLlmClient()
        # S2 and S3 are both unused (not in T1's support) -- both get offered.
        llm.queue_json({"assignment": "T1"})
        llm.queue_json({"assignment": "none"})
        labeled = assign_labels(make_statements(3))  # S1=U1-U2, S2=U2-U3, S3=U3-U4
        threads = [Thread(label="T1", idea="x", supporting_statement_ids=["U1-U2"])]
        outcomes = assign_unused(threads, labeled, llm, template="{threads_block}{statement_id}{statement_text}", cfg=make_cfg())
        self.assertEqual(len(outcomes), 2)
        self.assertEqual(outcomes["S2"].assigned_to, "T1")
        self.assertEqual(outcomes["S3"].assigned_to, None)
        self.assertIn("U2-U3", threads[0].supporting_statement_ids)

    def test_none_assignment_leaves_statement_unassigned(self):
        from experiments.threads.data_model import Thread
        llm = FakeLlmClient()
        llm.queue_json({"assignment": "none"})
        labeled = assign_labels(make_statements(1))
        threads = []
        outcomes = assign_unused(threads, labeled, llm, template="{threads_block}{statement_id}{statement_text}", cfg=make_cfg())
        self.assertIsNone(outcomes["S1"].assigned_to)

    def test_already_used_statement_is_not_offered_again(self):
        from experiments.threads.data_model import Thread
        llm = FakeLlmClient()  # nothing queued -- would raise if called
        labeled = assign_labels(make_statements(1))  # S1 = U1-U2
        threads = [Thread(label="T1", idea="x", supporting_statement_ids=["U1-U2"])]
        outcomes = assign_unused(threads, labeled, llm, template="x", cfg=make_cfg())
        self.assertEqual(outcomes, {})


class TestMapUnits(unittest.TestCase):
    def test_units_derived_from_pair_ids(self):
        from experiments.threads.data_model import Thread
        t = Thread(label="T1", idea="x", supporting_statement_ids=["U1-U2", "U2-U3"])
        map_units([t])
        self.assertEqual(t.units, {"U1", "U2", "U3"})


if __name__ == "__main__":
    unittest.main()
