import json

import pytest

from app.llm.incremental_resume_parser import IncrementalResumeParser

SAMPLE = {
    "roles": [
        {
            "company": "Nimbus Retail",
            "title": "Software Engineer II",
            "start": "2019-06",
            "end": "2021-03",
            "section": "work",
            "bullets": [
                "Led mobile checkout efforts across search, cart, and rewards teams",
                'Cut app crash rate by 35%, quote: "great job"',
            ],
        },
        {
            "company": "State University",
            "title": "B.S. Computer Science",
            "start": "2015-08",
            "end": "2019-05",
            "section": "education",
            "bullets": ["Graduated with honors"],
        },
    ]
}

SAMPLE_TEXT = json.dumps(SAMPLE)


def feed_in_chunks(parser: IncrementalResumeParser, text: str, chunk_size: int) -> list:
    events = []
    for i in range(0, len(text), chunk_size):
        events.extend(parser.feed(text[i : i + chunk_size]))
    return events


@pytest.mark.parametrize("chunk_size", [1, 3, 7, 50, len(SAMPLE_TEXT)])
def test_reconstructs_roles_and_bullets_at_any_chunk_size(chunk_size):
    parser = IncrementalResumeParser()
    events = feed_in_chunks(parser, SAMPLE_TEXT, chunk_size)

    role_meta_events = [e for e in events if e.kind == "role_meta"]
    bullet_events = [e for e in events if e.kind == "bullet"]
    role_done_events = [e for e in events if e.kind == "role_done"]

    assert len(role_meta_events) == 2
    assert role_meta_events[0].data["company"] == "Nimbus Retail"
    assert role_meta_events[0].data["section"] == "work"
    assert role_meta_events[1].data["company"] == "State University"
    assert role_meta_events[1].data["section"] == "education"

    assert len(bullet_events) == 3
    assert bullet_events[0].data["text"] == "Led mobile checkout efforts across search, cart, and rewards teams"
    assert bullet_events[1].data["text"] == 'Cut app crash rate by 35%, quote: "great job"'
    assert bullet_events[2].data["text"] == "Graduated with honors"

    assert len(role_done_events) == 2
    assert role_done_events[0].data["bullets"] == SAMPLE["roles"][0]["bullets"]
    assert role_done_events[1].data["bullets"] == SAMPLE["roles"][1]["bullets"]


def test_role_meta_fires_before_bullets_are_known():
    parser = IncrementalResumeParser()
    meta_prefix = SAMPLE_TEXT[: SAMPLE_TEXT.index('"bullets"')]
    events = parser.feed(meta_prefix)

    assert len(events) == 1
    assert events[0].kind == "role_meta"
    assert events[0].data["company"] == "Nimbus Retail"


def test_bullet_index_increments_within_a_role():
    parser = IncrementalResumeParser()
    events = feed_in_chunks(parser, SAMPLE_TEXT, 5)
    bullet_events = [e for e in events if e.kind == "bullet" and e.role_index == 0]
    assert [e.data["bullet_index"] for e in bullet_events] == [0, 1]


def test_raw_dates_are_normalized_in_live_events_same_as_final_parse():
    # The model streams dates as "Apr 2020" etc; ResumeStructureResult
    # normalizes them to "2020-04" for the final result. The live role_meta
    # event must show the same normalized form, not the raw one, so the UI
    # doesn't display one format while streaming and another once done.
    text = json.dumps({"roles": [{
        "company": "Acme", "title": "Engineer", "start": "Apr 2020", "end": "02/2023",
        "section": "work", "bullets": ["did stuff"],
    }]})
    parser = IncrementalResumeParser()
    events = feed_in_chunks(parser, text, 6)

    role_meta = next(e for e in events if e.kind == "role_meta")
    assert role_meta.data["start"] == "2020-04"
    assert role_meta.data["end"] == "2023-02"

    role_done = next(e for e in events if e.kind == "role_done")
    assert role_done.data["start"] == "2020-04"
    assert role_done.data["end"] == "2023-02"


def test_empty_bullets_array_still_emits_role_done():
    text = json.dumps({"roles": [{
        "company": "Acme", "title": "Volunteer", "start": "2020-01", "end": "2020-02",
        "section": "other", "bullets": [],
    }]})
    parser = IncrementalResumeParser()
    events = feed_in_chunks(parser, text, 4)

    kinds = [e.kind for e in events]
    assert kinds == ["role_meta", "role_done"]
    assert events[-1].data["bullets"] == []
