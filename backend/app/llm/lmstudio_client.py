import time
from typing import Iterator, Optional

import httpx
import openai
from openai import OpenAI

from app.llm.base import CallMetrics, LlmTimeout, StreamEvent
from app.llm.lock import llm_call_lock
from app.llm.tasks import TaskProfile


class LMStudioClient:
    def __init__(self, base_url: str, model: str):
        # max_retries=0: a timed-out call is reported, never silently retried
        # by the SDK (a retry would double the wait on a stalled model).
        self._client = OpenAI(base_url=base_url, api_key="lm-studio", max_retries=0)
        self._model = model

    def complete(self, task: TaskProfile, user_message: str) -> tuple[str, CallMetrics]:
        start = time.monotonic()
        kwargs = {}
        if task.structured:
            kwargs["response_format"] = task.response_format()
        # A non-streamed response arrives in one piece, so the idle timeout and
        # the total deadline collapse into one wait: use the smaller of the two.
        timeout = min(task.timeout_s, task.total_timeout_s)
        with llm_call_lock:
            try:
                response = self._client.chat.completions.create(
                    model=self._model,
                    messages=[
                        {"role": "system", "content": task.system_prompt},
                        {"role": "user", "content": user_message},
                    ],
                    temperature=task.temperature,
                    max_tokens=task.max_tokens,
                    timeout=timeout,
                    **kwargs,
                )
            except (openai.APITimeoutError, httpx.TimeoutException) as e:
                raise LlmTimeout(task.name, f"no response within {timeout:.0f}s") from e
        seconds = time.monotonic() - start

        raw = response.choices[0].message.content
        usage = response.usage
        details = getattr(usage, "completion_tokens_details", None) if usage else None
        metrics = CallMetrics(
            task=task.name,
            seconds=seconds,
            prompt_tokens=usage.prompt_tokens if usage else 0,
            completion_tokens=usage.completion_tokens if usage else 0,
            finish_reason=response.choices[0].finish_reason,
            reasoning_tokens=getattr(details, "reasoning_tokens", None) if details is not None else None,
        )
        return raw, metrics

    def complete_stream(self, task: TaskProfile, user_message: str) -> Iterator[StreamEvent]:
        start = time.monotonic()
        kwargs = {}
        if task.structured:
            kwargs["response_format"] = task.response_format()
        with llm_call_lock:
            stream = None
            try:
                # timeout is the idle timeout here: the SDK raises if no bytes
                # arrive for timeout_s. The total deadline is checked per chunk
                # below, so a slow trickle is still bounded.
                stream = self._client.chat.completions.create(
                    model=self._model,
                    messages=[
                        {"role": "system", "content": task.system_prompt},
                        {"role": "user", "content": user_message},
                    ],
                    temperature=task.temperature,
                    max_tokens=task.max_tokens,
                    stream=True,
                    stream_options={"include_usage": True},
                    timeout=task.timeout_s,
                    **kwargs,
                )

                accumulated = ""
                prompt_tokens = 0
                completion_tokens = 0
                reasoning_tokens = None
                finish_reason = None
                first_chunk_at: Optional[float] = None

                for chunk in stream:
                    if first_chunk_at is None:
                        first_chunk_at = time.monotonic()
                    if time.monotonic() - start > task.total_timeout_s:
                        raise LlmTimeout(task.name, f"exceeded total deadline of {task.total_timeout_s:.0f}s")
                    if chunk.choices:
                        delta = chunk.choices[0].delta.content or ""
                        if delta:
                            accumulated += delta
                            yield ("delta", delta)
                        if chunk.choices[0].finish_reason:
                            finish_reason = chunk.choices[0].finish_reason
                    if chunk.usage:
                        prompt_tokens = chunk.usage.prompt_tokens
                        completion_tokens = chunk.usage.completion_tokens
                        details = getattr(chunk.usage, "completion_tokens_details", None)
                        if details is not None:
                            reasoning_tokens = getattr(details, "reasoning_tokens", None)
            except (openai.APITimeoutError, httpx.TimeoutException) as e:
                raise LlmTimeout(task.name, f"no data within {task.timeout_s:.0f}s") from e
            finally:
                # Closing the HTTP stream on every exit path (normal end,
                # timeout, or the consumer abandoning the generator) frees the
                # connection; the `with` block releases llm_call_lock.
                if stream is not None:
                    stream.close()

        seconds = time.monotonic() - start
        seconds_to_first_chunk = (first_chunk_at - start) if first_chunk_at is not None else None
        metrics = CallMetrics(
            task=task.name, seconds=seconds,
            prompt_tokens=prompt_tokens, completion_tokens=completion_tokens,
            finish_reason=finish_reason, reasoning_tokens=reasoning_tokens,
            seconds_to_first_chunk=seconds_to_first_chunk,
        )
        yield ("done", accumulated, metrics)
