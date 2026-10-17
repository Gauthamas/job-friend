import logging
from dataclasses import dataclass
from typing import Callable, Iterator, Optional

from pydantic import BaseModel, ValidationError

from app.llm.base import CallMetrics, LLMClient, LlmTimeout, StreamEvent
from app.llm.tasks import TaskProfile

logger = logging.getLogger("job_friend.llm")


@dataclass
class TaskOutcome:
    status: str  # "ok" | "error"
    data: Optional[BaseModel]
    metrics: list[CallMetrics]
    # Human-readable reason for the last failed attempt -- None on "ok".
    # Surfaced to the user (e.g. requirement.reason on a judge failure), so
    # it's a short, readable string, not a raw exception dump.
    error: Optional[str] = None


def run_task(
    client: LLMClient,
    task: TaskProfile,
    user_message: str,
    validate_fn: Optional[Callable[[BaseModel], list[str]]] = None,
) -> TaskOutcome:
    metrics: list[CallMetrics] = []
    last_error: Optional[str] = None

    for attempt in range(1, task.max_attempts + 1):
        try:
            raw, call_metrics = client.complete(task, user_message)
        except LlmTimeout as e:
            # Not retried: a stalled model would just stall again for another
            # full timeout, so the timeout is this call's outcome.
            logger.warning("llm_call task=%s attempt=%d %s", task.name, attempt, e)
            return TaskOutcome(status="error", data=None, metrics=metrics, error="Model call timed out.")
        metrics.append(call_metrics)
        logger.info(
            "llm_call task=%s attempt=%d seconds=%.2f prompt_tokens=%d completion_tokens=%d",
            task.name, attempt, call_metrics.seconds,
            call_metrics.prompt_tokens, call_metrics.completion_tokens,
        )

        try:
            parsed = task.response_model.model_validate_json(raw)
        except ValidationError as e:
            logger.warning("llm_call task=%s attempt=%d schema_invalid: %s", task.name, attempt, e)
            last_error = "Model response did not match the expected format."
            continue

        errors = validate_fn(parsed) if validate_fn else []
        if errors:
            logger.warning("llm_call task=%s attempt=%d validation_errors=%s", task.name, attempt, errors)
            last_error = "; ".join(errors)
            continue

        return TaskOutcome(status="ok", data=parsed, metrics=metrics)

    return TaskOutcome(status="error", data=None, metrics=metrics, error=last_error)


def run_task_streaming(
    client: LLMClient,
    task: TaskProfile,
    user_message: str,
    validate_fn: Optional[Callable[[BaseModel], list[str]]] = None,
) -> Iterator[StreamEvent]:
    """Same behavior as run_task (parse, validate, retry up to max_attempts),
    but yields ("delta", text_chunk) as the model streams, then exactly one
    ("outcome", TaskOutcome) at the end."""
    metrics: list[CallMetrics] = []
    last_error: Optional[str] = None

    for attempt in range(1, task.max_attempts + 1):
        raw: Optional[str] = None
        call_metrics: Optional[CallMetrics] = None

        try:
            for event in client.complete_stream(task, user_message):
                if event[0] == "delta":
                    yield ("delta", event[1])
                else:
                    _, raw, call_metrics = event
        except LlmTimeout as e:
            logger.warning("llm_call task=%s attempt=%d %s", task.name, attempt, e)
            yield ("outcome", TaskOutcome(status="error", data=None, metrics=metrics, error="Model call timed out."))
            return

        metrics.append(call_metrics)
        logger.info(
            "llm_call task=%s attempt=%d seconds=%.2f prompt_tokens=%d completion_tokens=%d",
            task.name, attempt, call_metrics.seconds,
            call_metrics.prompt_tokens, call_metrics.completion_tokens,
        )

        try:
            parsed = task.response_model.model_validate_json(raw)
        except ValidationError as e:
            logger.warning("llm_call task=%s attempt=%d schema_invalid: %s", task.name, attempt, e)
            last_error = "Model response did not match the expected format."
            continue

        errors = validate_fn(parsed) if validate_fn else []
        if errors:
            logger.warning("llm_call task=%s attempt=%d validation_errors=%s", task.name, attempt, errors)
            last_error = "; ".join(errors)
            continue

        yield ("outcome", TaskOutcome(status="ok", data=parsed, metrics=metrics))
        return

    yield ("outcome", TaskOutcome(status="error", data=None, metrics=metrics, error=last_error))
