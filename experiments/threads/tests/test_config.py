import unittest

from experiments.threads.config import Config, MaxTokens, validate_config


def make_cfg(**overrides) -> Config:
    base = dict(
        endpoint="http://localhost:1234/v1", model="m", embed_model="e", temperature=0.2,
        max_tokens=MaxTokens(), request_timeout_s=10, runs=1, strategies=["fixed"],
        pairs_per_unit=2, n_threads=4, min_support=3, statement_source="human",
        seed=1, thinking=False, out_dir="/tmp/out", data_dir="/tmp/data",
    )
    base.update(overrides)
    return Config(**base)


class TestValidateConfig(unittest.TestCase):
    def test_valid_config_has_no_errors(self):
        self.assertEqual(validate_config(make_cfg()), [])

    def test_unknown_strategy_rejected(self):
        errors = validate_config(make_cfg(strategies=["bogus"]))
        self.assertTrue(any("bogus" in e for e in errors))

    def test_unknown_statement_source_rejected(self):
        errors = validate_config(make_cfg(statement_source="bogus"))
        self.assertTrue(any("bogus" in e for e in errors))

    def test_human_then_model_is_a_valid_source(self):
        self.assertEqual(validate_config(make_cfg(statement_source="human_then_model")), [])

    def test_zero_temperature_with_multiple_runs_rejected(self):
        errors = validate_config(make_cfg(temperature=0, runs=3))
        self.assertTrue(any("stability" in e for e in errors))

    def test_zero_temperature_with_single_run_is_fine(self):
        self.assertEqual(validate_config(make_cfg(temperature=0, runs=1)), [])

    def test_min_support_must_be_positive(self):
        self.assertTrue(validate_config(make_cfg(min_support=0)))


if __name__ == "__main__":
    unittest.main()
