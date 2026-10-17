"""A queue-based fake LlmClient, shared by every test that needs one --
same spirit as the main backend's MockLLMClient, no network calls."""

from experiments.threads.llm_client import CallResult


class FakeLlmClient:
    def __init__(self):
        self._queue: list[dict | None] = []  # None means "simulate failure"
        self.calls: list[dict] = []  # records what was asked, for assertions

    def queue_json(self, parsed: dict) -> None:
        self._queue.append(parsed)

    def queue_failure(self) -> None:
        self._queue.append(None)

    def call_json(self, system_prompt: str, user_message: str, temperature: float, max_tokens: int) -> CallResult:
        self.calls.append({"system_prompt": system_prompt, "user_message": user_message})
        if not self._queue:
            raise AssertionError("FakeLlmClient has no more responses queued")
        parsed = self._queue.pop(0)
        if parsed is None:
            return CallResult(raw_responses=["not json"], parsed=None, ok=False, attempts=2, error="invalid JSON")
        return CallResult(
            raw_responses=["<fake>"], parsed=parsed, ok=True, attempts=1,
            seconds=0.01, prompt_tokens=10, completion_tokens=5,
        )

    def embed(self, texts: list[str]) -> list[list[float]]:
        raise NotImplementedError("tests using embeddings should fake this directly")
