from functools import partial

from app.llm.judge_validation import validate_judge
from app.llm.mock_client import MockLLMClient
from app.llm.runner import run_task_streaming
from app.llm.schemas import JudgeResult
from app.llm.tasks import TaskProfile

# A generic two-attempt task profile, independent of whatever the
# production judge task looks like -- these tests are about
# run_task_streaming's retry/delta mechanics, not judge-specific behavior.
RETRYABLE_TASK = TaskProfile(
    name="judge_like", system_prompt="", response_model=JudgeResult, temperature=0, max_tokens=400, max_attempts=2,
)

VALID_JUDGE = '{"req_id": "R3", "units": [{"id": "U12", "quote": "", "shows": "fits", "needs": "fits", "v": "match"}], "reason": "fits well"}'
INVALID_JUDGE_EXTRA_ID = '{"req_id": "R3", "units": [{"id": "U99", "quote": "", "shows": "bad", "needs": "bad", "v": "match"}], "reason": "bad id"}'


def test_yields_deltas_then_ok_outcome():
    client = MockLLMClient({"judge_like": [VALID_JUDGE]})
    validate = partial(validate_judge, candidate_ids={"U12"}, haystacks={})

    events = list(run_task_streaming(client, RETRYABLE_TASK, "req + candidates", validate_fn=validate))

    delta_events = [e for e in events if e[0] == "delta"]
    outcome_events = [e for e in events if e[0] == "outcome"]
    assert len(delta_events) >= 1
    assert "".join(e[1] for e in delta_events) == VALID_JUDGE
    assert len(outcome_events) == 1
    assert outcome_events[0][1].status == "ok"
    assert outcome_events[0][1].data.req_id == "R3"


def test_retries_and_reports_deltas_on_each_attempt():
    client = MockLLMClient({"judge_like": [INVALID_JUDGE_EXTRA_ID, VALID_JUDGE]})
    validate = partial(validate_judge, candidate_ids={"U12"}, haystacks={})

    events = list(run_task_streaming(client, RETRYABLE_TASK, "req + candidates", validate_fn=validate))

    outcome = next(e for e in events if e[0] == "outcome")[1]
    assert outcome.status == "ok"
    assert len(outcome.metrics) == 2


def test_errors_after_max_attempts():
    client = MockLLMClient({"judge_like": [INVALID_JUDGE_EXTRA_ID, INVALID_JUDGE_EXTRA_ID]})
    validate = partial(validate_judge, candidate_ids={"U12"}, haystacks={})

    events = list(run_task_streaming(client, RETRYABLE_TASK, "req + candidates", validate_fn=validate))

    outcome = next(e for e in events if e[0] == "outcome")[1]
    assert outcome.status == "error"
    assert outcome.data is None
