import unittest
from unittest.mock import MagicMock, patch

import requests

from experiments.threads.llm_client import LlmClient, LlmTimeout, strip_think


class TestStripThink(unittest.TestCase):
    def test_removes_think_block(self):
        self.assertEqual(strip_think("<think>reasoning</think>{\"a\": 1}"), '{"a": 1}')

    def test_no_think_block_unchanged(self):
        self.assertEqual(strip_think('{"a": 1}'), '{"a": 1}')

    def test_multiline_think_block(self):
        text = "<think>\nstep one\nstep two\n</think>\n{\"a\": 1}"
        self.assertEqual(strip_think(text), '{"a": 1}')


def _fake_response(content: str, status=200):
    resp = MagicMock()
    resp.status_code = status
    resp.json.return_value = {
        "choices": [{"message": {"content": content}}],
        "usage": {"prompt_tokens": 7, "completion_tokens": 3},
    }
    resp.raise_for_status = MagicMock()
    return resp


class TestCallJson(unittest.TestCase):
    def setUp(self):
        self.client = LlmClient("http://localhost:1234/v1", "m", "e", request_timeout_s=5, thinking=False)

    @patch("experiments.threads.llm_client.requests.post")
    def test_valid_json_first_try(self, mock_post):
        mock_post.return_value = _fake_response('{"similarity": "x"}')
        result = self.client.call_json("sys", "user", temperature=0.2, max_tokens=50)
        self.assertTrue(result.ok)
        self.assertEqual(result.attempts, 1)
        self.assertEqual(result.parsed, {"similarity": "x"})
        self.assertEqual(result.prompt_tokens, 7)

    @patch("experiments.threads.llm_client.requests.post")
    def test_invalid_then_valid_retries_once(self, mock_post):
        mock_post.side_effect = [_fake_response("not json"), _fake_response('{"similarity": "x"}')]
        result = self.client.call_json("sys", "user", temperature=0.2, max_tokens=50)
        self.assertTrue(result.ok)
        self.assertEqual(result.attempts, 2)
        self.assertEqual(len(result.raw_responses), 2)

    @patch("experiments.threads.llm_client.requests.post")
    def test_invalid_twice_recorded_as_failure_not_a_third_try(self, mock_post):
        mock_post.return_value = _fake_response("not json")
        result = self.client.call_json("sys", "user", temperature=0.2, max_tokens=50)
        self.assertFalse(result.ok)
        self.assertEqual(result.attempts, 2)
        self.assertEqual(mock_post.call_count, 2)
        self.assertIsNotNone(result.error)

    @patch("experiments.threads.llm_client.requests.post")
    def test_strips_think_before_parsing(self, mock_post):
        mock_post.return_value = _fake_response('<think>hmm</think>{"similarity": "x"}')
        result = self.client.call_json("sys", "user", temperature=0.2, max_tokens=50)
        self.assertTrue(result.ok)
        self.assertEqual(result.parsed, {"similarity": "x"})

    @patch("experiments.threads.llm_client.requests.post")
    def test_timeout_is_caught_and_recorded_not_retried(self, mock_post):
        # call_json catches LlmTimeout internally and reports it as a
        # failed CallResult, rather than letting it propagate -- a timeout
        # is not retried (a stalled model would just stall again).
        mock_post.side_effect = requests.exceptions.Timeout()
        result = self.client.call_json("sys", "user", temperature=0.2, max_tokens=50)
        self.assertFalse(result.ok)
        self.assertIn("timeout", result.error)
        self.assertEqual(mock_post.call_count, 1)

    @patch("experiments.threads.llm_client.requests.post")
    def test_raw_timeout_from_chat_once_is_typed(self, mock_post):
        mock_post.side_effect = requests.exceptions.Timeout()
        with self.assertRaises(LlmTimeout):
            self.client._chat_once("sys", "user", temperature=0.2, max_tokens=50)


if __name__ == "__main__":
    unittest.main()
