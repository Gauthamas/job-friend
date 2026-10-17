"""Regression coverage for job 47's cross-requirement id confusion: a
batch call judges several requirements at once, and the same unit
routinely gets shortlisted for more than one of them. Candidate ids are
scoped to their own req_id (app/judge_input.py's format_unit_id) so that
unit never looks like the same token under two different requirements."""

from app.judge_input import build_candidate_haystacks, build_judge_batch_message, format_unit_id, parse_unit_id
from app.shortlist import Candidate


def _candidate(unit_id: int, text: str = "did the thing") -> Candidate:
    return Candidate(unit_id=unit_id, text=text, context=None, contribution=None, outcome=None, skills=[], score=0.5)


def test_format_unit_id_is_scoped_to_its_req_id():
    assert format_unit_id("1", 50) == "1.U50"
    assert format_unit_id("2", 50) == "2.U50"
    assert format_unit_id("1", 50) != format_unit_id("2", 50)


def test_parse_unit_id_recovers_the_real_unit_id():
    assert parse_unit_id("1.U50") == 50
    assert parse_unit_id("12.U999") == 999


def test_the_same_unit_shortlisted_for_two_requirements_gets_two_different_ids():
    shared = _candidate(50)
    haystacks_a = build_candidate_haystacks("1", [shared])
    haystacks_b = build_candidate_haystacks("2", [shared])
    assert set(haystacks_a.keys()) == {"1.U50"}
    assert set(haystacks_b.keys()) == {"2.U50"}
    assert haystacks_a.keys().isdisjoint(haystacks_b.keys())


def test_batch_message_candidate_ids_are_scoped_per_requirement():
    batch = [
        ("1", "Req A", [_candidate(52), _candidate(63)]),
        ("2", "Req B", [_candidate(52), _candidate(50)]),
    ]
    message = build_judge_batch_message(batch)
    import json
    parsed = json.loads(message)
    ids_by_req = {r["req_id"]: {c["id"] for c in r["candidates"]} for r in parsed["requirements"]}
    assert ids_by_req["1"] == {"1.U52", "1.U63"}
    assert ids_by_req["2"] == {"2.U52", "2.U50"}
    # Unit 52 is a candidate of both requirements, but under different ids.
    assert "2.U52" not in ids_by_req["1"]
    assert "1.U52" not in ids_by_req["2"]
