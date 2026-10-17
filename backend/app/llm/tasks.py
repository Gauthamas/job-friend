import re
from dataclasses import dataclass
from pathlib import Path
from typing import Type

from pydantic import BaseModel

from app.config import settings
from app.llm.schemas import (
    AssignUnusedResult,
    JudgeBatchResult,
    ProposeThreadsResult,
    RequirementExtractResult,
    ResumeStructureResult,
    VerifyThreadResult,
)

PROMPTS_DIR = Path(__file__).resolve().parent.parent.parent / "prompts"
_PLACEHOLDER_RE = re.compile(r"\{(\w+)\}")


def _load_prompt(name: str, **values: str) -> str:
    """Reads backend/prompts/{name}.txt and fills {word} placeholders that
    are in `values` -- not plain str.format(), which would choke on the
    literal JSON braces the prompt shows as the output shape."""
    template = (PROMPTS_DIR / f"{name}.txt").read_text(encoding="utf-8")

    def _sub(m: re.Match) -> str:
        key = m.group(1)
        return str(values[key]) if key in values else m.group(0)

    return _PLACEHOLDER_RE.sub(_sub, template)

NO_THINK = "/no_think"
THINK = "/think"

MAX_QUOTE_WORDS = 15
MAX_SHOWS_WORDS = 8
MAX_NEEDS_WORDS = 8

@dataclass
class TaskProfile:
    name: str
    system_prompt: str
    response_model: Type[BaseModel]
    temperature: float
    max_tokens: int
    max_attempts: int = 1
    # False skips response_format entirely (no schema-constrained decoding).
    structured: bool = True
    # Recorded on run_timing rows so historical timing stats can be grouped
    # by which prompt text produced them. Bump by hand when a prompt's
    # wording changes materially.
    prompt_version: str = "1"
    # Idle (read) timeout: the longest the client waits without receiving
    # any bytes before the call is abandoned.
    timeout_s: float = 1000.0
    # Hard cap on the whole call, however much text keeps trickling in.
    total_timeout_s: float = 3600.0

    def response_format(self) -> dict:
        return {
            "type": "json_schema",
            "json_schema": {
                "name": self.name,
                "schema": self.response_model.model_json_schema(),
            },
        }


RESUME_STRUCTURE = TaskProfile(
    name="resume_structure",
    system_prompt=f"""{NO_THINK}
You turn resume text into structured roles and bullets. Output JSON only, matching the
given schema. Copy bullet wording exactly; do not rewrite, embellish, or summarize.
Split compound bullets ("built X and led Y") into separate bullets. For example,
"Cut cold-start time from 3.7s to 1.9s and set up a snapshot testing suite" becomes
two bullets: "Cut cold-start time from 3.7s to 1.9s" and "set up a snapshot testing
suite" — copied verbatim, not reworded. A role with no bullets gets one bullet made
from its description.

Classify every role's "section":
- "work": a job, internship, contract, or freelance role. Internships count
  as work. Founding, running, or being self-employed at a company also
  counts as work (titles like "Founder", "Co-Founder", "Owner").
- "education": a degree, diploma, or academic program.
- "other": anything else (volunteering, certifications listed as a role, projects).""",
    response_model=ResumeStructureResult,
    temperature=0,
    max_tokens=3000,
    max_attempts=1,
)

REQUIREMENT_EXTRACT = TaskProfile(
    name="requirement_extract",
    system_prompt=f"""{NO_THINK}
You extract job requirements from a job description. Output JSON only, matching the
given schema. Produce 5-12 requirements. Merge duplicates. Skip boilerplate (benefits,
EEO text, company boilerplate).

A posting may describe what it needs under several different headings
(Responsibilities, Accountabilities, Duties, Requirements, Qualifications, or
similar, in any combination) -- read all of them, not only a section literally
named "Requirements". Treat a stated responsibility or duty as a requirement too
whenever it implies a skill, experience, or credential the candidate must have;
do not take requirements from only one section while ignoring the rest.
Duties listed without any heading (for example an introductory block of bullet
points before the first heading) count exactly like duties under a heading.

Each requirement gets a weight:
- "high": stated as required/must-have, or is core to the main responsibility of the role.
- "medium": mentioned as a skill or responsibility but not emphasized as critical.
- "low": nice-to-have language, or a minor/peripheral mention.""",
    response_model=RequirementExtractResult,
    temperature=0,
    max_tokens=2000,
    max_attempts=1,
    prompt_version="2",
)

_JUDGE_RULES = """
You judge whether candidate experience units satisfy a job requirement. Judge only
from the text given. Never claim a match from inference.

List only units rated match or weak for each requirement. Never write "none" as a
unit's verdict. Do not list a unit just because it is the closest candidate --
if nothing clears "weak", the units list is empty. Only list units that matter;
omit units that clearly do not match -- an empty units list is a valid answer.
Be concise: aim for about 100 tokens per requirement. For each listed unit fill
the fields in this order:
1. quote: exact words copied from the unit's text, one continuous span, no
   ellipses, maximum {MAX_QUOTE_WORDS} words.
2. shows: the specific skill the quote itself demonstrates, at most
   {MAX_SHOWS_WORDS} words. Describe only what the quote says -- never infer
   beyond it, and never mention a skill the quote does not show.
3. needs: the specific part of the requirement this unit would have to satisfy,
   at most {MAX_NEEDS_WORDS} words, in the requirement's own terms.
4. v: decided from what you just wrote --
   "match": the quote shows the specific skill the requirement names.
   "weak": the quote shows a clearly narrower or partial piece of that
   specific skill (for example "UI library projects" for "build SDKs and
   libraries").
   "none": the only overlap is the platform, domain, or general engineering
   (Android, leading projects, debugging, refactoring, writing code).
   Platform words in the requirement ("on Android") never count as overlap.
   If unsure between weak and none, answer none. But if the quote shows
   direct professional work in the area the requirement names, answer
   match; for experience-level requirements (years, platform, language)
   any bullet showing real professional work in that area is a match.

Examples:
- needs "Build REST APIs for a payments backend"; quote "Designed REST
  endpoints for an invoicing service" -> shows "building REST APIs" ->
  weak (right skill, different domain).
- needs "Experience with iOS push notifications"; quote "Led the mobile
  team across three product launches" -> shows "leading a mobile team" ->
  none (general work, not the skill).
- needs "3+ years of Python"; quote "Built data pipelines in Python for
  four years" -> shows "professional Python work" -> match.
- needs "Write and maintain unit tests"; quote "Wrote and maintained the
  unit test suite for a billing module" -> shows "writing unit tests" ->
  match.

reason: one short sentence about what the quotes show, not a restatement of the
requirement.""".format(
    MAX_QUOTE_WORDS=MAX_QUOTE_WORDS, MAX_SHOWS_WORDS=MAX_SHOWS_WORDS, MAX_NEEDS_WORDS=MAX_NEEDS_WORDS,
)

# v2 draft 3 §3: one call judges up to judge_batch_size requirements. Each
# requirement is given a small per-batch id ("1".."N", never the real
# requirement id -- judging.py maps it back) so the model's output doesn't
# need to repeat long real ids. Output JSON only, matching the given
# schema: {"results": [{"req_id": "<small id>", "units": [...], "reason": "..."}]}.
_JUDGE_BATCH_TRAILER = """
Output JSON only, matching the given schema:
{"results": [{"req_id": "<small id>", "units": [...], "reason": "..."}]}

You will receive several requirements, each with its own small id (req_id) and its
own candidate units. Judge each requirement independently, using only its own
candidates. Include exactly one result per requirement you were given, using its
same req_id.

Each candidate's "id" already starts with its own req_id (for example "1.U9" is a
candidate of requirement "1"). The same underlying unit can be a candidate of more
than one requirement, each time under a different id -- always copy a unit's id
exactly as given under the requirement you are judging; never reuse an id that
appeared under a different requirement, even if it looks like a good match there too.

Example (unrelated domain), requirement req_id "1", "Design REST APIs":
{"results": [{"req_id": "1", "units": [{"id": "1.U9", "quote": "designed REST endpoints", "shows": "designing REST APIs", "needs": "designing REST APIs", "v": "match"}], "reason": "directly matches"}]}"""

JUDGE_BATCH = TaskProfile(
    name="judge_batch",
    # judge_batch_thinking picks /think vs /no_think -- thinking was
    # previously turned off because a single batch call was observed
    # taking 1600+ seconds with /think at the old larger batch size; now
    # re-enabled at a smaller batch_size/higher judge_start_min_left to
    # see whether thinking improves verdict quality within that budget.
    system_prompt=f"{THINK if settings.judge_batch_thinking else NO_THINK}{_JUDGE_RULES}{_JUDGE_BATCH_TRAILER}",
    response_model=JudgeBatchResult,
    temperature=0,
    max_tokens=settings.judge_max_tokens,
    max_attempts=1,
)

# §7: thread discovery. All three thinking off, temp 0.2, no retries
# (max_attempts=1), stream=True (set at the client level, same as
# JUDGE_BATCH) consumed as one document.
_THREAD_THINK_PREFIX = THINK if settings.thread_thinking else NO_THINK

PROPOSE_THREADS = TaskProfile(
    name="propose_threads",
    system_prompt=f"{_THREAD_THINK_PREFIX}\n" + _load_prompt(
        "propose_threads", n_threads=settings.n_threads, min_support=settings.min_support,
    ),
    response_model=ProposeThreadsResult,
    temperature=0.2,
    max_tokens=settings.propose_threads_max_tokens,
    max_attempts=1,
)

ASSIGN_UNUSED = TaskProfile(
    name="assign_unused",
    system_prompt=f"{_THREAD_THINK_PREFIX}\n" + _load_prompt("assign_unused"),
    response_model=AssignUnusedResult,
    temperature=0.2,
    max_tokens=settings.assign_unused_max_tokens,
    max_attempts=1,
)

VERIFY_THREAD = TaskProfile(
    name="verify_thread",
    system_prompt=f"{_THREAD_THINK_PREFIX}\n" + _load_prompt("verify_thread"),
    response_model=VerifyThreadResult,
    temperature=0.2,
    max_tokens=settings.verify_thread_max_tokens,
    max_attempts=1,
)

