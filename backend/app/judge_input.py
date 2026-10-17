import json

from app.llm.judge_validation import build_haystack
from app.shortlist import Candidate

UNIT_ID_PREFIX = "U"


def format_unit_id(req_id: str, unit_id: int) -> str:
    """Scoped to req_id -- a batch call judges several requirements at
    once, and two requirements routinely shortlist the same unit (it's a
    good candidate for both). A bare "U50" shared across both candidate
    lists gave the model nothing to tell them apart by, and it would
    sometimes cite a requirement's own-looking id while actually meaning
    the OTHER requirement in the same batch's candidate (job 47,
    requirement 466: "U50" was a candidate of requirement 467, the other
    half of that batch, never offered to 466 at all). Prefixing the id
    with its own req_id makes that confusion structurally impossible: the
    same unit shows up as two different strings ("1.U50" vs "2.U50"), one
    per requirement, so a citation can never leak across requirements."""
    return f"{req_id}.{UNIT_ID_PREFIX}{unit_id}"


def parse_unit_id(scoped_id: str) -> int:
    return int(scoped_id.rsplit(".", 1)[-1][len(UNIT_ID_PREFIX):])


def _candidate_payload(req_id: str, c: Candidate) -> dict:
    """Empty enrichment fields are omitted entirely (not sent as null) to
    keep the judge's input small — same convention used when embedding
    units."""
    payload: dict = {"id": format_unit_id(req_id, c.unit_id), "text": c.text}
    if c.context:
        payload["context"] = c.context
    if c.contribution:
        payload["contribution"] = c.contribution
    if c.outcome:
        payload["outcome"] = c.outcome
    if c.skills:
        payload["skills"] = c.skills
    return payload


def build_candidate_haystacks(req_id: str, candidates: list[Candidate]) -> dict[str, str]:
    """{formatted_unit_id: normalized combined text of every field actually
    sent for that candidate} -- a quote must appear verbatim (post-
    normalization) somewhere in here. Same fields as _candidate_payload,
    so the haystack always matches exactly what the model was shown."""
    return {
        format_unit_id(req_id, c.unit_id): build_haystack(
            c.text, c.context, c.contribution, c.outcome, ", ".join(c.skills) if c.skills else None,
        )
        for c in candidates
    }


def build_judge_batch_message(batch: list[tuple[str, str, list[Candidate]]]) -> str:
    """JSON message for the batch judge task: `batch` is a list of
    (small_req_id, requirement_text, candidates) -- small_req_id is the
    per-batch "1".."judge_batch_size" id, never the real requirement id
    (judging.py owns that mapping). Each candidate's "id" is scoped to its
    own small_req_id (see format_unit_id) so the same unit appearing under
    two requirements never looks like the same token."""
    return json.dumps({
        "requirements": [
            {
                "req_id": small_req_id,
                "text": requirement_text,
                "candidates": [_candidate_payload(small_req_id, c) for c in candidates],
            }
            for small_req_id, requirement_text, candidates in batch
        ],
    })
