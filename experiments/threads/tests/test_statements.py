import unittest

from experiments.threads.config import Config, MaxTokens
from experiments.threads.statements import source_statements
from .fakes import FakeLlmClient


def make_cfg(source: str) -> Config:
    return Config(
        endpoint="http://localhost:1234/v1", model="m", embed_model="e", temperature=0.2,
        max_tokens=MaxTokens(), request_timeout_s=10, runs=1, strategies=["fixed"],
        pairs_per_unit=2, n_threads=4, min_support=3, statement_source=source,
        seed=1, thinking=False, out_dir="/tmp/out", data_dir="/tmp/data",
    )


def render(a, b):
    return f"compare {a} and {b}"


class TestHumanSource(unittest.TestCase):
    def test_pair_present_with_text_is_kept(self):
        human_map = {"U1-U2": "both about resilience"}
        llm = FakeLlmClient()
        statements, logs = source_statements([("U1", "U2")], make_cfg("human"), human_map, llm, render)
        self.assertEqual(len(statements), 1)
        self.assertEqual(statements[0].text, "both about resilience")
        self.assertEqual(statements[0].source, "human")

    def test_pair_present_with_null_is_kept_as_human_none(self):
        human_map = {"U1-U2": None}
        llm = FakeLlmClient()
        statements, logs = source_statements([("U1", "U2")], make_cfg("human"), human_map, llm, render)
        self.assertEqual(len(statements), 1)
        self.assertIsNone(statements[0].text)
        self.assertEqual(statements[0].source, "human_none")

    def test_pair_absent_is_skipped_not_kept(self):
        human_map = {}
        llm = FakeLlmClient()
        statements, logs = source_statements([("U1", "U2")], make_cfg("human"), human_map, llm, render)
        self.assertEqual(statements, [])

    def test_human_source_never_calls_the_model(self):
        human_map = {"U1-U2": "text"}
        llm = FakeLlmClient()  # no responses queued -- would raise if called
        source_statements([("U1", "U2")], make_cfg("human"), human_map, llm, render)
        self.assertEqual(llm.calls, [])


class TestModelSource(unittest.TestCase):
    def test_model_returns_text(self):
        llm = FakeLlmClient()
        llm.queue_json({"similarity": "both mention a deadline"})
        statements, logs = source_statements([("U1", "U2")], make_cfg("model"), {}, llm, render)
        self.assertEqual(statements[0].text, "both mention a deadline")
        self.assertEqual(statements[0].source, "model")

    def test_model_returns_none(self):
        llm = FakeLlmClient()
        llm.queue_json({"similarity": None})
        statements, logs = source_statements([("U1", "U2")], make_cfg("model"), {}, llm, render)
        self.assertIsNone(statements[0].text)
        self.assertEqual(statements[0].source, "model_none")

    def test_model_invalid_json_recorded_as_failed(self):
        llm = FakeLlmClient()
        llm.queue_failure()
        statements, logs = source_statements([("U1", "U2")], make_cfg("model"), {}, llm, render)
        self.assertEqual(statements[0].source, "failed")
        self.assertIsNone(statements[0].text)
        self.assertFalse(logs[0].call.ok)


class TestHumanThenModel(unittest.TestCase):
    def test_uses_human_text_when_pair_present(self):
        human_map = {"U1-U2": "human wrote this"}
        llm = FakeLlmClient()  # not called
        statements, logs = source_statements([("U1", "U2")], make_cfg("human_then_model"), human_map, llm, render)
        self.assertEqual(statements[0].text, "human wrote this")
        self.assertEqual(statements[0].source, "human")
        self.assertEqual(llm.calls, [])

    def test_uses_human_none_when_pair_present_as_null_does_not_call_model(self):
        # An explicit human "none" is a real judgment, not a gap -- the
        # model must not be asked to override it.
        human_map = {"U1-U2": None}
        llm = FakeLlmClient()
        statements, logs = source_statements([("U1", "U2")], make_cfg("human_then_model"), human_map, llm, render)
        self.assertEqual(statements[0].source, "human_none")
        self.assertEqual(llm.calls, [])

    def test_calls_model_when_pair_absent(self):
        human_map = {}
        llm = FakeLlmClient()
        llm.queue_json({"similarity": "model filled this in"})
        statements, logs = source_statements([("U1", "U2")], make_cfg("human_then_model"), human_map, llm, render)
        self.assertEqual(statements[0].text, "model filled this in")
        self.assertEqual(statements[0].source, "model")
        self.assertEqual(len(llm.calls), 1)

    def test_mixed_pairs_some_human_some_model(self):
        human_map = {"U1-U2": "human text"}
        llm = FakeLlmClient()
        llm.queue_json({"similarity": "model text"})
        statements, logs = source_statements(
            [("U1", "U2"), ("U3", "U4")], make_cfg("human_then_model"), human_map, llm, render,
        )
        sources = {s.pair_id: s.source for s in statements}
        self.assertEqual(sources["U1-U2"], "human")
        self.assertEqual(sources["U3-U4"], "model")


if __name__ == "__main__":
    unittest.main()
