from typing import Literal, Optional

from pydantic import BaseModel

from app.llm.schemas import RoleBullets


class DraftRoles(BaseModel):
    roles: list[RoleBullets]


class CommitUnit(BaseModel):
    text: str
    source: str
    sort_order: int
    context: Optional[str] = None
    contribution: Optional[str] = None
    outcome: Optional[str] = None
    skills_json: Optional[str] = None


class CommitRole(BaseModel):
    company: str
    title: str
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    sort_order: int
    units: list[CommitUnit]


class CommitRequest(BaseModel):
    roles: list[CommitRole]


class CommittedUnit(CommitUnit):
    id: int


class CommittedRole(BaseModel):
    id: int
    company: str
    title: str
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    sort_order: int
    units: list[CommittedUnit]


class CommitResponse(BaseModel):
    inventory_id: int
    roles: list[CommittedRole]


class UnitSearchResultOut(BaseModel):
    unit_id: int
    role_id: int
    company: str
    title: str
    text: str
    context: Optional[str] = None
    contribution: Optional[str] = None
    outcome: Optional[str] = None
    score: float
    matched_substring: bool


class UnitSearchResponse(BaseModel):
    results: list[UnitSearchResultOut]


class UnitOut(BaseModel):
    id: int
    role_id: int
    text: str
    source: str
    sort_order: int
    context: Optional[str] = None
    contribution: Optional[str] = None
    outcome: Optional[str] = None
    skills_json: Optional[str] = None
    context_skipped: bool = False
    contribution_skipped: bool = False
    outcome_skipped: bool = False
    discarded_at: Optional[str] = None


class UnitPatchRequest(BaseModel):
    text: Optional[str] = None
    context: Optional[str] = None
    contribution: Optional[str] = None
    outcome: Optional[str] = None
    skills_json: Optional[str] = None
    context_skipped: Optional[bool] = None
    contribution_skipped: Optional[bool] = None
    outcome_skipped: Optional[bool] = None


class SplitUnitRequest(BaseModel):
    split_at: int


class SplitUnitResponse(BaseModel):
    original: UnitOut
    new_unit: UnitOut


class MergeUnitsRequest(BaseModel):
    other_unit_id: int


class MergeUnitsResponse(BaseModel):
    survivor: UnitOut
    merged_unit_id: int


class AddUnitRequest(BaseModel):
    text: str
    context: Optional[str] = None
    contribution: Optional[str] = None
    outcome: Optional[str] = None
    skills_json: Optional[str] = None


class InventoryRoleOut(BaseModel):
    id: int
    company: str
    title: str
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    sort_order: int
    units: list[UnitOut]
    discarded_at: Optional[str] = None


class RoleOut(BaseModel):
    id: int
    inventory_id: int
    company: str
    title: str
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    sort_order: int
    discarded_at: Optional[str] = None


class InventoryDetailResponse(BaseModel):
    id: int
    name: str
    roles: list[InventoryRoleOut]


class InventoryListItem(BaseModel):
    id: int
    name: str
    created_at: str
    role_count: int
    unit_count: int


class InventoryListResponse(BaseModel):
    inventories: list[InventoryListItem]


class FlowCreateRequest(BaseModel):
    name: str
    inventory_id: int
    profile_id: Optional[int] = None


class FlowOut(BaseModel):
    id: int
    name: str
    inventory_id: int
    profile_id: int
    created_at: str
    # The flow's own most-recently-created job (not filtered by discard) --
    # the one a click already opens, and what the Flows screen's own
    # Discard/Restore button acts on. None if the flow has no jobs yet.
    latest_job_id: Optional[int] = None
    latest_job_discarded_at: Optional[str] = None


class FlowListResponse(BaseModel):
    flows: list[FlowOut]


class TimingHistoryResponse(BaseModel):
    avg_seconds_total: Optional[float] = None
    avg_seconds_to_first_result: Optional[float] = None
    sample_size: int = 0


class JobCreateRequest(BaseModel):
    title: str


class JobPatchRequest(BaseModel):
    # Optional/partial: a field omitted from the request body is left
    # untouched; company/role_title explicitly set to null clears them.
    title: Optional[str] = None
    company: Optional[str] = None
    role_title: Optional[str] = None


class SubmitJdRequest(BaseModel):
    jd_text: str


class JobOut(BaseModel):
    id: int
    flow_id: int
    title: str
    jd_text: str
    jd_submitted_text: Optional[str] = None
    jd_submitted_at: Optional[str] = None
    extraction_error: Optional[str] = None
    created_at: str
    extraction_seconds: Optional[float] = None
    judging_started_at: Optional[str] = None
    judging_deadline: Optional[str] = None
    finished_at: Optional[str] = None
    company: Optional[str] = None
    role_title: Optional[str] = None
    discarded_at: Optional[str] = None


class JobListResponse(BaseModel):
    jobs: list[JobOut]


class JobProgressResponse(BaseModel):
    # The furthest screen this job has reached, inferred from what's
    # actually been saved for it (never a separately tracked flag) --
    # "job" covers both the JD and requirements views on /jobs/{id}
    # itself, which already picks between them on its own.
    route: Literal["job", "statements", "threads", "primary_secondary", "write"]


class RequirementOut(BaseModel):
    id: int
    job_id: int
    text: str
    weight: str
    source: str
    status: str
    reason: Optional[str] = None
    last_error: Optional[str] = None
    sort_order: int
    judged_at: Optional[str] = None
    embed_seconds: Optional[float] = None
    judge_seconds: Optional[float] = None


class RequirementCreateRequest(BaseModel):
    text: str
    weight: str = "medium"


class RequirementPatchRequest(BaseModel):
    text: Optional[str] = None
    weight: Optional[str] = None


class JudgmentOut(BaseModel):
    id: int
    requirement_id: int
    unit_id: int
    score: Optional[float] = None
    model_verdict: Optional[str] = None
    user_verdict: Optional[str] = None
    added_by_user: bool
    created_at: str
    why: Optional[str] = None


class JudgmentPatchRequest(BaseModel):
    user_verdict: Optional[Literal["match", "weak", "none"]] = None


class JudgmentPatchResponse(BaseModel):
    judgment: JudgmentOut
    requirement_verdict: str  # via app.verdicts.requirement_verdict() -- see that docstring
    # Setting a real verdict by hand can complete a pending requirement
    # (no separate "Done" action) -- the frontend needs this to reflect
    # that without a second round trip.
    requirement_status: str


class AttachUnitRequest(BaseModel):
    unit_id: int


class AttachUnitResponse(BaseModel):
    judgment: JudgmentOut
    requirement_verdict: str  # via app.verdicts.requirement_verdict() -- see that docstring
    requirement_status: str


class JobCreateResponse(BaseModel):
    job: JobOut


class RequirementWithJudgments(BaseModel):
    requirement: RequirementOut
    judgments: list[JudgmentOut]
    verdict: str  # derived: "match" | "weak" | "gap" -- see app.verdicts.requirement_verdict


class JobFullMapResponse(BaseModel):
    job: JobOut
    requirements: list[RequirementWithJudgments]


class EnrichmentRequirementRef(BaseModel):
    id: int
    text: str
    weight: str


class EnrichmentUnitOut(BaseModel):
    unit: UnitOut
    matched_requirements: list[EnrichmentRequirementRef]
    complete: bool


class EnrichQuestions(BaseModel):
    context: str
    contribution: str
    outcome: str


class EnrichmentResponse(BaseModel):
    units: list[EnrichmentUnitOut]
    enriched_count: int
    total_count: int
    questions: EnrichQuestions


# --- Pair builder and statements (milestone 3) ---

class StatementOut(BaseModel):
    id: int
    status: Literal["unanswered", "written", "none"]
    text: Optional[str] = None
    autofilled_from_job_id: Optional[int] = None
    autofilled_from_job_title: Optional[str] = None
    autofilled_from_date: Optional[str] = None
    confirmed: bool


class PairOut(BaseModel):
    id: int
    unit_a: UnitOut
    unit_b: UnitOut
    statement: StatementOut


class PairsListResponse(BaseModel):
    pairs: list[PairOut]
    # True once no pair is unanswered and no autofilled statement is
    # unconfirmed -- exactly the Continue gate (§6 rule 9).
    all_ready: bool


class RemovedPairOut(BaseModel):
    unit_a_id: int
    unit_b_id: int
    had_written_statement: bool


class BuildPairsResponse(BaseModel):
    pair_count: int
    removed: list[RemovedPairOut]


class StatementPatchRequest(BaseModel):
    status: Literal["unanswered", "written", "none"]
    text: Optional[str] = None


class AutofillResponse(BaseModel):
    autofilled_count: int


# --- Thread discovery (milestone 4) ---

class ThreadUnitOut(BaseModel):
    unit: UnitOut
    model_verdict: Optional[str] = None
    quote: Optional[str] = None
    user_verdict: Optional[str] = None


class ThreadStatementOut(BaseModel):
    statement_id: int
    text: Optional[str] = None
    unit_a: UnitOut
    unit_b: UnitOut
    origin: Literal["proposed", "assigned", "user"]


class ThreadOut(BaseModel):
    id: int
    idea: str
    edited_idea: Optional[str] = None
    source: Literal["model", "user"]
    stale: bool
    below_min: bool = False
    statements: list[ThreadStatementOut]
    units: list[ThreadUnitOut]


class ThreadRunOut(BaseModel):
    id: int
    job_id: int
    created_at: str
    error: Optional[str] = None
    threads: list[ThreadOut]
    proposed_count: Optional[int] = None
    moved_count: Optional[int] = None
    removed_count: Optional[int] = None
    seconds_total: Optional[float] = None


class ThreadRunSummary(BaseModel):
    id: int
    created_at: str
    error: Optional[str] = None


class ThreadRunHistoryResponse(BaseModel):
    runs: list[ThreadRunSummary]


class RunThreadsBlockedReason(BaseModel):
    blocked: bool
    reason: Optional[str] = None


class ThreadIdeaPatchRequest(BaseModel):
    idea: str


class MoveStatementRequest(BaseModel):
    statement_id: int


class MergeThreadsRequest(BaseModel):
    other_thread_id: int


# --- Primary/secondary ranking (milestone 5) ---

class RankedThreadOut(BaseModel):
    id: int
    idea: str
    edited_idea: Optional[str] = None
    source: Literal["model", "user"]
    stale: bool
    statements: list[ThreadStatementOut]
    units: list[ThreadUnitOut]
    covered_requirements: list[EnrichmentRequirementRef]
    uncovered_requirements: list[EnrichmentRequirementRef]
    support_count: int
    exempt_from_min_support: bool = False


class PrimarySecondarySlot(BaseModel):
    thread: Optional[RankedThreadOut] = None
    choice_stale: bool = False


class PrimarySecondaryResponse(BaseModel):
    primary: PrimarySecondarySlot
    secondary: PrimarySecondarySlot
    other_candidates: list[RankedThreadOut]
    empty_reason: Optional[str] = None


class ChooseThreadRequest(BaseModel):
    thread_id: int
    role: Literal["primary", "secondary"]


class ManualThreadRequest(BaseModel):
    idea: str
    statement_ids: list[int]


# --- Writing view (milestone 6) ---

class PointerOut(BaseModel):
    unit_id: int
    verdict: str
    quote: Optional[str] = None
    line: str
    is_primary: bool
    is_secondary: bool


class RequirementRefOut(BaseModel):
    id: int
    text: str
    weight: str
    # Weak section groups only (§10 point 4) -- empty for Gaps, where
    # there are no units to point to.
    pointers: list[PointerOut] = []


class LetterSectionOut(BaseModel):
    key: str
    kind: Literal["plain", "requirement", "weak", "gaps"]
    text: str
    skipped: bool
    word_count: int
    # requirement/weak only
    requirement_id: Optional[int] = None
    requirement_text: Optional[str] = None
    weight: Optional[str] = None
    verdict: Optional[str] = None
    pointers: list[PointerOut] = []
    proposed_pointer_text: Optional[str] = None
    pointer_text: Optional[str] = None
    pointers_edited: bool = False
    # weak/gaps only
    requirements: list[RequirementRefOut] = []


class ThreadBarOut(BaseModel):
    thread_id: Optional[int] = None
    idea: Optional[str] = None
    edited_idea: Optional[str] = None
    statements: list[str] = []


class OpeningHintOut(BaseModel):
    # Display only -- never inserted into the Opening section's text.
    company: Optional[str] = None
    role_title: Optional[str] = None
    # The primary thread's single strongest supporting statement, exactly
    # as the user wrote it, plus its verified quote if the model found
    # one. Not the thread's name or its full statement list -- that's
    # already in the sticky bar.
    statement_text: Optional[str] = None
    statement_quote: Optional[str] = None
    question: str


class CloseHintOut(BaseModel):
    # Requirements no unit covers at all, high weight first.
    uncovered: list[RequirementRefOut] = []
    question: str


class LetterOut(BaseModel):
    job_id: int
    sections: list[LetterSectionOut]
    matched_shown: int
    matched_total: int
    matched_sections_setting: int
    total_word_count: int
    section_char_limit: Optional[int] = None
    greeting: Optional[str] = None
    signoff: Optional[str] = None
    assembled_text: Optional[str] = None
    finished: bool
    primary: ThreadBarOut
    secondary: ThreadBarOut
    opening_hint: OpeningHintOut
    close_hint: CloseHintOut


class SectionPatchRequest(BaseModel):
    text: Optional[str] = None
    skipped: Optional[bool] = None


class PointerPatchRequest(BaseModel):
    text: Optional[str] = None  # None means Reset to proposed


class LetterPatchRequest(BaseModel):
    greeting: Optional[str] = None
    signoff: Optional[str] = None


class GenerateResponse(BaseModel):
    assembled_text: str
    word_count: int


class MatchedSectionsPatchRequest(BaseModel):
    value: int


# --- Settings persistence (milestone 7) ---

class SettingOut(BaseModel):
    key: str
    group: str
    type: str
    default: object = None
    value: object = None
    is_default: bool


class SettingsResponse(BaseModel):
    settings: list[SettingOut]


class SettingsPatchRequest(BaseModel):
    values: dict[str, object]
