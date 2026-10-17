"""Talks to LM Studio's OpenAI-compatible REST endpoint directly with
requests -- no openai SDK, per the stdlib-plus-requests/httpx constraint.
Every request carries a timeout; a client with no timeout can hang the
whole run forever on a stalled model, which is exactly what bit the main
app once already."""

import json
import re
import time
from dataclasses import dataclass, field
from typing import Optional

import requests

_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL)


class LlmTimeout(Exception):
    pass


def strip_think(text: str) -> str:
    """LM Studio separates reasoning into its own field for the models this
    harness uses, so this should rarely trigger -- but if a model ever
    inlines <think> tags in the visible content instead, this keeps them
    out of the JSON we try to parse."""
    return _THINK_RE.sub("", text).strip()


@dataclass
class CallResult:
    raw_responses: list[str] = field(default_factory=list)
    parsed: Optional[dict] = None
    ok: bool = False
    attempts: int = 0
    seconds: float = 0.0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    error: Optional[str] = None
    temperature: float = 0.0  # the value actually placed in the request payload
    finish_reason: Optional[str] = None  # from the last attempt
    truncated: bool = False  # True if any attempt hit finish_reason == "length"

    def to_dict(self) -> dict:
        return {
            "raw_responses": self.raw_responses, "parsed": self.parsed, "ok": self.ok,
            "attempts": self.attempts, "seconds": self.seconds,
            "prompt_tokens": self.prompt_tokens, "completion_tokens": self.completion_tokens,
            "error": self.error, "temperature": self.temperature,
            "finish_reason": self.finish_reason, "truncated": self.truncated,
        }


class LlmClient:
    def __init__(self, endpoint: str, model: str, embed_model: str, request_timeout_s: float, thinking: bool):
        self.endpoint = endpoint.rstrip("/")
        self.model = model
        self.embed_model = embed_model
        self.timeout = request_timeout_s
        self.thinking = thinking

    def _chat_once(self, system_prompt: str, user_message: str, temperature: float, max_tokens: int) -> tuple[str, dict]:
        prefix = "/think" if self.thinking else "/no_think"
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": f"{prefix}\n{system_prompt}"},
                {"role": "user", "content": user_message},
            ],
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": False,
        }
        start = time.monotonic()
        try:
            resp = requests.post(f"{self.endpoint}/chat/completions", json=payload, timeout=self.timeout)
        except requests.exceptions.Timeout as e:
            raise LlmTimeout(f"no response within {self.timeout:.0f}s") from e
        resp.raise_for_status()
        data = resp.json()
        seconds = time.monotonic() - start
        choice = data["choices"][0]
        # LM Studio returns reasoning in its own "reasoning_content" field for
        # these models -- "content" is already answer-only. strip_think()
        # below is a fallback for models/configs that inline <think> tags
        # into content instead.
        content = (choice["message"].get("content") or "")
        usage = data.get("usage") or {}
        meta = {
            "seconds": seconds,
            "prompt_tokens": usage.get("prompt_tokens", 0),
            "completion_tokens": usage.get("completion_tokens", 0),
            "temperature": payload["temperature"],
            "finish_reason": choice.get("finish_reason"),
        }
        return content, meta

    def call_json(self, system_prompt: str, user_message: str, temperature: float, max_tokens: int) -> CallResult:
        """Retries once on invalid JSON, then records the failure --
        never a third attempt, never silently swallowed."""
        result = CallResult()
        result.temperature = temperature  # what every attempt below will send
        for attempt in (1, 2):
            result.attempts = attempt
            try:
                raw, meta = self._chat_once(system_prompt, user_message, temperature, max_tokens)
            except LlmTimeout as e:
                result.error = f"timeout: {e}"
                return result
            result.raw_responses.append(raw)
            result.seconds += meta["seconds"]
            result.prompt_tokens += meta["prompt_tokens"]
            result.completion_tokens += meta["completion_tokens"]
            result.finish_reason = meta["finish_reason"]
            if meta["finish_reason"] == "length":
                result.truncated = True  # sticky across attempts, even if a retry then succeeds

            cleaned = strip_think(raw)
            try:
                result.parsed = json.loads(cleaned)
            except json.JSONDecodeError as e:
                if meta["finish_reason"] == "length":
                    result.error = f"truncated (finish_reason=length, {len(raw)} chars): {e}"
                else:
                    result.error = f"invalid JSON: {e}"
                continue
            result.ok = True
            result.error = None
            return result
        return result  # ok stays False -> caller records this as a failure

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        payload = {"model": self.embed_model, "input": texts}
        try:
            resp = requests.post(f"{self.endpoint}/embeddings", json=payload, timeout=self.timeout)
        except requests.exceptions.Timeout as e:
            raise LlmTimeout(f"embeddings: no response within {self.timeout:.0f}s") from e
        resp.raise_for_status()
        data = resp.json()
        ordered = sorted(data["data"], key=lambda d: d["index"])
        return [d["embedding"] for d in ordered]
