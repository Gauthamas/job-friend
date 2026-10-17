"""Milestone 2 smoke test: run each task profile once against the real LM Studio server.
All people, companies and bullets below are fictional.

Run from backend/ with the venv active:
    python smoke_test.py
"""
import json
from functools import partial

from app.config import settings
from app.llm.judge_validation import build_haystack, validate_judge
from app.llm.lmstudio_client import LMStudioClient
from app.llm.runner import run_task
from app.llm.tasks import JUDGE, REQUIREMENT_EXTRACT, RESUME_STRUCTURE

RESUME_TEXT = """
Priya Chattopadhyay
Senior Mobile Engineer

Parcelwise — Senior Android Engineer, Apr 2020 – Feb 2023
• Led the Android rewrite of the courier tracking app used by 40,000 drivers
• Cut cold-start time from 3.1s to 1.4s and set up a snapshot testing suite
  adopted by all four mobile teams
• Built an offline sync layer so deliveries could be logged without network

Loanlane — Android Engineer, Aug 2016 – Mar 2020
• Built the borrower onboarding flow from scratch; 250,000+ installs
• Raised crash-free sessions from 94% to 99.4% by tracing failure paths and fixing root causes
• Coached two interns through their first production releases
"""

JD_TEXT = """
Android SDK Engineer — Brightbid (AdTech)

Brightbid's SDK is embedded in over 3,000 publisher apps. You will:
- Build rendering for new interactive ad formats
- Own error handling and crash resilience inside the SDK
- Instrument attribution and analytics events
- Keep the SDK compatible across Android versions and device makers
- Write integration docs and answer publisher developers on GitHub

Perks: remote-first, annual offsite, home office stipend.
"""

JUDGE_INPUT = {
    "req_id": "R2",
    "requirement": "Own error handling and crash resilience inside the SDK",
    "candidates": [
        {"id": "U5", "text": "Raised crash-free sessions from 94% to 99.4% by tracing failure paths and fixing root causes"},
        {"id": "U3", "text": "Built an offline sync layer so deliveries could be logged without network"},
        {"id": "U6", "text": "Coached two interns through their first production releases"},
    ],
}


def show(name, outcome):
    print(f"\n=== {name} ===")
    print("status:", outcome.status)
    print("data:", outcome.data.model_dump_json(indent=2) if outcome.data else None)
    print("metrics:", outcome.metrics)


if __name__ == "__main__":
    # Real network calls -- deliberately not at module level, so importing
    # this file (e.g. if a test runner ever collects it) can't trigger them.
    client = LMStudioClient(settings.lm_studio_base_url, settings.llm_model)

    show("resume_structure", run_task(client, RESUME_STRUCTURE, RESUME_TEXT))
    show("requirement_extract", run_task(client, REQUIREMENT_EXTRACT, JD_TEXT))

    judge_candidate_ids = {c["id"] for c in JUDGE_INPUT["candidates"]}
    judge_haystacks = {c["id"]: build_haystack(c["text"]) for c in JUDGE_INPUT["candidates"]}
    judge_validate = partial(validate_judge, candidate_ids=judge_candidate_ids, haystacks=judge_haystacks)
    show("judge", run_task(client, JUDGE, json.dumps(JUDGE_INPUT), validate_fn=judge_validate))
