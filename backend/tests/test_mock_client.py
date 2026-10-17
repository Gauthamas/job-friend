import pytest

from app.llm.mock_client import MockLLMClient
from app.llm.tasks import JUDGE_BATCH


def test_serves_responses_in_order():
    client = MockLLMClient({"judge_batch": ['{"a": 1}', '{"a": 2}']})
    raw1, _ = client.complete(JUDGE_BATCH, "irrelevant")
    raw2, _ = client.complete(JUDGE_BATCH, "irrelevant")
    assert raw1 == '{"a": 1}'
    assert raw2 == '{"a": 2}'


def test_raises_when_exhausted():
    client = MockLLMClient({"judge_batch": ['{"a": 1}']})
    client.complete(JUDGE_BATCH, "irrelevant")
    with pytest.raises(AssertionError):
        client.complete(JUDGE_BATCH, "irrelevant")


def test_raises_when_task_unregistered():
    client = MockLLMClient({})
    with pytest.raises(AssertionError):
        client.complete(JUDGE_BATCH, "irrelevant")
