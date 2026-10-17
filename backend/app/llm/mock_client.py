from typing import Iterator, Optional

from app.llm.base import CallMetrics, StreamEvent
from app.llm.tasks import TaskProfile


class MockLLMClient:
    """Serves canned JSON responses in order, per task name. No network calls."""

    def __init__(self, responses: dict[str, list[str]] | None = None):
        self._responses = {task: list(items) for task, items in (responses or {}).items()}
        self._finish_reasons: dict[str, list[Optional[str]]] = {}
        # (task_name, user_message) per complete() call, in order -- lets
        # tests assert on call count and on exactly what was sent.
        self.calls: list[tuple[str, str]] = []

    def queue(self, task_name: str, raw_json: str, finish_reason: Optional[str] = "stop") -> None:
        self._responses.setdefault(task_name, []).append(raw_json)
        self._finish_reasons.setdefault(task_name, []).append(finish_reason)

    def complete(self, task: TaskProfile, user_message: str) -> tuple[str, CallMetrics]:
        self.calls.append((task.name, user_message))
        queue = self._responses.get(task.name)
        if not queue:
            raise AssertionError(f"MockLLMClient has no more responses queued for task {task.name!r}")
        raw = queue.pop(0)
        finish_reason = self._finish_reasons.get(task.name, ["stop"]).pop(0) if self._finish_reasons.get(task.name) else "stop"
        metrics = CallMetrics(
            task=task.name, seconds=0.0, prompt_tokens=0, completion_tokens=0, finish_reason=finish_reason,
        )
        return raw, metrics

    def complete_stream(self, task: TaskProfile, user_message: str) -> Iterator[StreamEvent]:
        raw, metrics = self.complete(task, user_message)
        # Chunk into small pieces (not one shot) so tests exercise the same
        # incremental-delta path the real streaming client uses.
        chunk_size = 7
        for i in range(0, len(raw), chunk_size):
            yield ("delta", raw[i : i + chunk_size])
        yield ("done", raw, metrics)
