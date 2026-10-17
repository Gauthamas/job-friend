from dataclasses import dataclass
from typing import Iterator, Optional, Protocol

from app.llm.tasks import TaskProfile


@dataclass
class CallMetrics:
    task: str
    seconds: float
    prompt_tokens: int
    completion_tokens: int
    # "stop" | "length" | None (mock/unavailable). "length" means the model
    # hit max_tokens before finishing -- the batch judge path uses this to
    # detect a truncated stream and requeue whatever wasn't completed.
    finish_reason: Optional[str] = None
    # completion_tokens_details.reasoning_tokens from the usage chunk, when
    # the server reports it (None if absent/unsupported). LM Studio reports
    # this as a SEPARATE pool from completion_tokens, not a subset of it --
    # add them together for the actual total tokens generated.
    reasoning_tokens: Optional[int] = None
    # Time to the very first streamed chunk of any kind (monotonic seconds
    # from call start), including a reasoning-only chunk with no visible
    # .content -- i.e. before thinking even starts producing anything.
    # None if no chunk ever arrived, or for a non-streaming call.
    seconds_to_first_chunk: Optional[float] = None


class LlmTimeout(Exception):
    """A model call exceeded its idle (read) timeout or its total deadline."""

    def __init__(self, task: str, reason: str):
        super().__init__(f"LLM call for {task} timed out: {reason}")
        self.task = task


# A stream is a sequence of ("delta", text_chunk: str) events followed by
# exactly one ("done", full_raw_json_text: str, metrics: CallMetrics) event.
StreamEvent = tuple


class LLMClient(Protocol):
    def complete(self, task: TaskProfile, user_message: str) -> tuple[str, CallMetrics]:
        """Run one model call for `task` and return (raw_json_text, metrics)."""
        ...

    def complete_stream(self, task: TaskProfile, user_message: str) -> Iterator[StreamEvent]:
        """Same call as `complete`, but yields progress as tokens arrive."""
        ...
