from typing import Literal

from pydantic import BaseModel, field_validator

from app.llm.dates import normalize_month

Section = Literal["work", "education", "other"]


class RoleBullets(BaseModel):
    # Field order matters: it's also the order the incremental SSE parser
    # (app/llm/incremental_resume_parser.py) expects fields to stream in,
    # and "bullets" must come last so section is known before bullets arrive.
    company: str
    title: str
    start: str
    end: str
    section: Section
    bullets: list[str]

    @field_validator("start", "end")
    @classmethod
    def _normalize_date(cls, value: str) -> str:
        return normalize_month(value)


class ResumeStructureResult(BaseModel):
    roles: list[RoleBullets]


class Requirement(BaseModel):
    text: str
    weight: str


class RequirementExtractResult(BaseModel):
    requirements: list[Requirement]


class JudgedUnit(BaseModel):
    # Field order matters under LM Studio's schema-constrained decoding
    # (JUDGE_BATCH is structured=True, so this order IS the generation
    # order): fields are generated left-to-right, so the model writes
    # quote, then shows, then needs, then only commits to v last -- never
    # a verdict the preceding fields can't justify. Verified live that an
    # id/v-only order let the model output "match" even when its own
    # (post-hoc) reason said "same domain, different action."
    id: str
    quote: str
    shows: str  # the skill the quote itself demonstrates
    needs: str  # the part of the requirement it would have to satisfy
    v: str


class JudgeResult(BaseModel):
    req_id: str
    units: list[JudgedUnit]
    reason: str


class JudgeBatchResult(BaseModel):
    # One JudgeResult per requirement in the batch, each keyed by its small
    # per-batch id ("1".."judge_batch_size", a string to match req_id) --
    # never the real requirement id (v2 draft 3 §3: "use ids 1..10 in the
    # batch schema and map back to real requirement ids in code").
    results: list[JudgeResult]


# --- Thread discovery (milestone 4) ---

class ProposedThread(BaseModel):
    idea: str
    supporting_statement_ids: list[str]


class ProposeThreadsResult(BaseModel):
    threads: list[ProposedThread]
    unused: list[str]


class AssignUnusedResult(BaseModel):
    thread: str  # a small thread id ("1".."n_threads"), or "none"


class VerifyThreadResult(BaseModel):
    verdict: str  # "yes" | "partly" | "no"
    quote: str
