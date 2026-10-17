from functools import partial

from app.llm.judge_validation import validate_judge
from app.llm.mock_client import MockLLMClient
from app.llm.runner import run_task
from app.llm.schemas import JudgeResult
from app.llm.tasks import REQUIREMENT_EXTRACT, TaskProfile

# A generic two-attempt task profile, independent of whatever the
# production judge task looks like -- these tests are about run_task's
# retry mechanics, not judge-specific behavior.
RETRYABLE_TASK = TaskProfile(
    name="judge_like", system_prompt="", response_model=JudgeResult, temperature=0, max_tokens=400, max_attempts=2,
)

VALID_JUDGE = '{"req_id": "R3", "units": [{"id": "U12", "quote": "", "shows": "fits", "needs": "fits", "v": "match"}], "reason": "fits well"}'
INVALID_JUDGE_EXTRA_ID = '{"req_id": "R3", "units": [{"id": "U99", "quote": "", "shows": "bad", "needs": "bad", "v": "match"}], "reason": "bad id"}'
MALFORMED_JSON = "not json at all"


def test_succeeds_on_first_attempt():
    client = MockLLMClient({"judge_like": [VALID_JUDGE]})
    validate = partial(validate_judge, candidate_ids={"U12"}, haystacks={})
    outcome = run_task(client, RETRYABLE_TASK, "req + candidates", validate_fn=validate)
    assert outcome.status == "ok"
    assert outcome.data.req_id == "R3"
    assert len(outcome.metrics) == 1


def test_retries_once_then_succeeds():
    client = MockLLMClient({"judge_like": [INVALID_JUDGE_EXTRA_ID, VALID_JUDGE]})
    validate = partial(validate_judge, candidate_ids={"U12"}, haystacks={})
    outcome = run_task(client, RETRYABLE_TASK, "req + candidates", validate_fn=validate)
    assert outcome.status == "ok"
    assert len(outcome.metrics) == 2


def test_errors_after_max_attempts():
    client = MockLLMClient({"judge_like": [INVALID_JUDGE_EXTRA_ID, INVALID_JUDGE_EXTRA_ID]})
    validate = partial(validate_judge, candidate_ids={"U12"}, haystacks={})
    outcome = run_task(client, RETRYABLE_TASK, "req + candidates", validate_fn=validate)
    assert outcome.status == "error"
    assert outcome.data is None
    assert len(outcome.metrics) == RETRYABLE_TASK.max_attempts


def test_malformed_json_counts_as_invalid_attempt():
    client = MockLLMClient({"judge_like": [MALFORMED_JSON, VALID_JUDGE]})
    validate = partial(validate_judge, candidate_ids={"U12"}, haystacks={})
    outcome = run_task(client, RETRYABLE_TASK, "req + candidates", validate_fn=validate)
    assert outcome.status == "ok"
    assert len(outcome.metrics) == 2


def test_single_attempt_task_does_not_retry():
    client = MockLLMClient({"requirement_extract": [MALFORMED_JSON]})
    outcome = run_task(client, REQUIREMENT_EXTRACT, "jd text")
    assert outcome.status == "error"
    assert len(outcome.metrics) == 1
