import dataclasses
from types import SimpleNamespace

import httpx
import openai
import pytest

from app.llm.base import LlmTimeout
from app.llm.lmstudio_client import LMStudioClient
from app.llm.lock import llm_call_lock
from app.llm.runner import run_task, run_task_streaming
from app.llm.tasks import JUDGE_BATCH


def api_timeout() -> openai.APITimeoutError:
    return openai.APITimeoutError(request=httpx.Request("POST", "http://localhost:1234/v1/chat/completions"))


def make_client() -> LMStudioClient:
    return LMStudioClient("http://localhost:1234/v1", "test-model")


class FakeStream:
    def __init__(self, chunks):
        self._chunks = list(chunks)
        self.closed = False

    def __iter__(self):
        return iter(self._chunks)

    def close(self):
        self.closed = True


def text_chunk(text: str):
    return SimpleNamespace(
        choices=[SimpleNamespace(delta=SimpleNamespace(content=text), finish_reason=None)], usage=None,
    )


def test_client_disables_sdk_retries():
    assert make_client()._client.max_retries == 0


def test_streaming_idle_timeout_raises_typed_error_and_releases_lock(monkeypatch):
    client = make_client()

    def raise_timeout(**kwargs):
        raise api_timeout()

    monkeypatch.setattr(client._client.chat.completions, "create", raise_timeout)
    with pytest.raises(LlmTimeout):
        list(client.complete_stream(JUDGE_BATCH, "msg"))
    assert not llm_call_lock.locked()


def test_streaming_total_deadline_closes_stream_and_releases_lock(monkeypatch):
    client = make_client()
    stream = FakeStream([text_chunk("{")])
    monkeypatch.setattr(client._client.chat.completions, "create", lambda **kwargs: stream)
    task = dataclasses.replace(JUDGE_BATCH, total_timeout_s=0.0)

    with pytest.raises(LlmTimeout):
        list(client.complete_stream(task, "msg"))
    assert stream.closed
    assert not llm_call_lock.locked()


def test_non_streamed_timeout_raises_typed_error_and_releases_lock(monkeypatch):
    client = make_client()

    def raise_timeout(**kwargs):
        raise api_timeout()

    monkeypatch.setattr(client._client.chat.completions, "create", raise_timeout)
    with pytest.raises(LlmTimeout):
        client.complete(JUDGE_BATCH, "msg")
    assert not llm_call_lock.locked()


class TimingOutClient:
    """Stand-in for LMStudioClient: every call times out, and we count calls."""

    def __init__(self):
        self.calls = 0

    def complete(self, task, user_message):
        self.calls += 1
        raise LlmTimeout(task.name, "idle")

    def complete_stream(self, task, user_message):
        self.calls += 1
        raise LlmTimeout(task.name, "idle")
        yield  # pragma: no cover -- makes this a generator


def test_run_task_reports_timeout_as_error_outcome_without_retry():
    client = TimingOutClient()
    outcome = run_task(client, JUDGE_BATCH, "msg")
    assert outcome.status == "error"
    assert outcome.error == "Model call timed out."
    assert client.calls == 1  # a timeout is never retried, regardless of max_attempts


def test_run_task_streaming_reports_timeout_as_error_outcome():
    client = TimingOutClient()
    events = list(run_task_streaming(client, JUDGE_BATCH, "msg"))
    outcome = next(e for e in events if e[0] == "outcome")[1]
    assert outcome.status == "error"
    assert outcome.error == "Model call timed out."
    assert client.calls == 1
