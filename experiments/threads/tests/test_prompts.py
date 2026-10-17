import unittest

from experiments.threads.prompts import fill


class TestFill(unittest.TestCase):
    def test_replaces_known_placeholder(self):
        self.assertEqual(fill("Hello {name}", name="world"), "Hello world")

    def test_leaves_unknown_braces_alone(self):
        template = 'Output: {"verdict": "yes", "quote": "..."}'
        self.assertEqual(fill(template), template)

    def test_leaves_unknown_single_word_braces_alone_too(self):
        # {threads} isn't a kwarg here -- must not raise, must not vanish.
        self.assertEqual(fill("See {threads} above"), "See {threads} above")

    def test_json_example_coexists_with_real_placeholders(self):
        template = 'Describe {unit_a_text} vs {unit_b_text}.\nOutput: {"similarity": "..." }'
        result = fill(template, unit_a_text="A", unit_b_text="B")
        self.assertIn("Describe A vs B.", result)
        self.assertIn('{"similarity": "..." }', result)

    def test_multiple_occurrences_all_replaced(self):
        self.assertEqual(fill("{x} and {x}", x="1"), "1 and 1")


if __name__ == "__main__":
    unittest.main()
