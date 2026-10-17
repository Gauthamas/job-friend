export type UnitSource = 'parsed' | 'manual' | 'later_version';
export type Section = 'work' | 'education' | 'other';

export interface DraftUnit {
	// Client-only id for list rendering/keying; never sent to the server.
	clientId: string;
	text: string;
	source: UnitSource;
	context: string | null;
	contribution: string | null;
	outcome: string | null;
	skillsJson: string | null;
}

export interface DraftRole {
	// Server-assigned index into the streamed roles array; stable for the
	// life of one structuring run, used to route SSE events to this role.
	roleIndex: number;
	company: string;
	title: string;
	start: string;
	end: string;
	section: Section;
	units: DraftUnit[];
	// True until this role's "role_done" SSE event arrives.
	streaming: boolean;
}

export type StructuringStatus = 'idle' | 'structuring' | 'ready' | 'error';

// Raw shapes of the backend's SSE events (app/routers/inventories.py::_sse).
export type InventoryStreamEvent =
	| { event: 'role_meta'; role_index: number; company: string; title: string; start: string; end: string; section: Section }
	| { event: 'bullet'; role_index: number; bullet_index: number; text: string }
	| { event: 'role_done'; role_index: number; company: string; title: string; start: string; end: string; section: Section; bullets: string[] }
	| { event: 'done'; inventory_id: number; draft: { roles: { company: string; title: string; start: string; end: string; section: Section; bullets: string[] }[] } }
	| { event: 'error'; message: string };

export interface CommitUnitPayload {
	text: string;
	source: UnitSource;
	sort_order: number;
	context?: string | null;
	contribution?: string | null;
	outcome?: string | null;
	skills_json?: string | null;
}

export interface CommitRolePayload {
	company: string;
	title: string;
	start_date: string;
	end_date: string;
	sort_order: number;
	units: CommitUnitPayload[];
}

export interface CommitRequestPayload {
	roles: CommitRolePayload[];
}

export interface CommittedUnit extends CommitUnitPayload {
	id: number;
}

export interface CommittedRole extends Omit<CommitRolePayload, 'units'> {
	id: number;
	units: CommittedUnit[];
}

export interface CommitResponse {
	inventory_id: number;
	roles: CommittedRole[];
}

// --- Saved-inventory editor (already-committed data, edited via real API
// calls, unlike the draft store which mutates only in-memory state) ---

export interface SavedUnit {
	id: number;
	role_id: number;
	text: string;
	source: UnitSource;
	sort_order: number;
	context: string | null;
	contribution: string | null;
	outcome: string | null;
	skills_json: string | null;
	context_skipped: boolean;
	contribution_skipped: boolean;
	outcome_skipped: boolean;
	discarded_at: string | null;
}

export interface SavedRole {
	id: number;
	company: string;
	title: string;
	start_date: string | null;
	end_date: string | null;
	sort_order: number;
	units: SavedUnit[];
	discarded_at: string | null;
}

export interface InventoryDetail {
	id: number;
	name: string;
	roles: SavedRole[];
}

export interface InventoryListItem {
	id: number;
	name: string;
	created_at: string;
	role_count: number;
	unit_count: number;
}

export interface UnitPatchPayload {
	text?: string;
	context?: string | null;
	contribution?: string | null;
	outcome?: string | null;
	skills_json?: string | null;
	context_skipped?: boolean;
	contribution_skipped?: boolean;
	outcome_skipped?: boolean;
}

export interface SplitUnitResult {
	original: SavedUnit;
	new_unit: SavedUnit;
}

export interface MergeUnitsResult {
	survivor: SavedUnit;
	merged_unit_id: number;
}

// --- Shared unit-editor view model ---
// RoleCard/UnitRow render either a DraftRole or a SavedRole through this
// common shape, so the two screens (pre-save review, saved editor) use one
// set of components instead of two near-identical trees. `key` is the
// draft's clientId or the saved unit's numeric id — whichever the source is.

export interface UnitViewModel {
	key: string | number;
	text: string;
	source: UnitSource;
	context: string | null;
	contribution: string | null;
	outcome: string | null;
	skillsJson: string | null;
	streaming?: boolean;
	discardedAt?: string | null;
}

export interface EnrichmentPatch {
	context: string | null;
	contribution: string | null;
	outcome: string | null;
	skills_json: string | null;
}

export interface UnitSavePatch extends EnrichmentPatch {
	text: string;
}

export interface RoleViewModel {
	key: string | number;
	company: string;
	title: string;
	start: string;
	end: string;
	units: UnitViewModel[];
	discardedAt?: string | null;
}

// Callbacks a screen wires up differently depending on mode. `onChange`
// fires on every keystroke in text/enrichment fields and never touches the
// network itself: the draft screen points it at draftStore (an instant
// local mutation — there's nothing else to stage), the saved editor points
// it at a local staging map that only reaches the server when the page's
// one Save-all button is clicked. split/merge/delete are real API calls
// immediately in saved mode (each is already its own explicit, confirmed
// action) and local mutations in draft mode. UnitRow/RoleCard don't know
// which mode they're in.
export interface UnitRowActions {
	onChange: (unitKey: string | number, patch: UnitSavePatch) => void;
	split: (unitKey: string | number, splitAt: number) => void;
	merge: (unitKey: string | number, otherUnitKey: string | number) => void;
	delete: (unitKey: string | number) => void;
	// Optional: only the saved editor wires these up (not the pre-commit
	// draft screen, where nothing has been saved yet to discard).
	discard?: (unitKey: string | number) => void;
	restore?: (unitKey: string | number) => void;
}

// --- Requirement map review (mirrors app/api_schemas.py, v2 §3/§9) ---

// v2 draft 3: exactly two values, nothing in between -- a batch call
// writes its result and 'done' together, so there's no visible in-flight
// state at all.
export type RequirementStatus = 'pending' | 'done';
export type RequirementSource = 'extracted' | 'user';
export type Weight = 'high' | 'medium' | 'low';
export type Verdict = 'match' | 'weak' | 'none';
// The requirement-level rollup, always computed backend-side by
// app/verdicts.py::requirement_verdict — never re-derived here.
export type RequirementVerdict = 'match' | 'weak' | 'gap';

export interface Flow {
	id: number;
	name: string;
	inventory_id: number;
	profile_id: number;
	created_at: string;
	latest_job_id: number | null;
	latest_job_discarded_at: string | null;
}

export interface Job {
	id: number;
	flow_id: number;
	title: string;
	jd_text: string;
	jd_submitted_text: string | null;
	jd_submitted_at: string | null;
	extraction_error: string | null;
	created_at: string;
	extraction_seconds: number | null;
	judging_started_at: string | null;
	judging_deadline: string | null;
	finished_at: string | null;
	company: string | null;
	role_title: string | null;
	discarded_at: string | null;
}

export interface Requirement {
	id: number;
	job_id: number;
	text: string;
	weight: Weight;
	source: RequirementSource;
	status: RequirementStatus;
	reason: string | null;
	// Failure text from a timed-out or invalid judge call -- the
	// requirement stays 'pending', there is no separate error status.
	last_error: string | null;
	sort_order: number;
	judged_at: string | null;
	embed_seconds: number | null;
	judge_seconds: number | null;
}

export interface Judgment {
	id: number;
	requirement_id: number;
	unit_id: number;
	score: number | null;
	model_verdict: Verdict | null;
	user_verdict: Verdict | null;
	added_by_user: boolean;
	created_at: string;
	why: string | null;
}

export interface RequirementWithJudgments {
	requirement: Requirement;
	judgments: Judgment[];
	verdict: RequirementVerdict;
}

export interface JobFullMapResponse {
	job: Job;
	requirements: RequirementWithJudgments[];
}

export interface JobCreateResponse {
	job: Job;
}

export interface JobListResponse {
	jobs: Job[];
}

export type JobProgressRoute = 'job' | 'statements' | 'threads' | 'primary_secondary' | 'write';

export interface JobProgress {
	route: JobProgressRoute;
}

export interface JudgmentPatchResponse {
	judgment: Judgment;
	requirement_verdict: RequirementVerdict;
	// Setting a real verdict by hand can complete a pending requirement --
	// there's no separate "Done" action.
	requirement_status: RequirementStatus;
}

export interface AttachUnitResponse {
	judgment: Judgment;
	requirement_verdict: RequirementVerdict;
	requirement_status: RequirementStatus;
}

export interface ProceedResponse {
	ok: boolean;
	no_matches: boolean;
	unjudged_count: number;
}

export interface UnitSearchResult {
	unit_id: number;
	role_id: number;
	company: string;
	title: string;
	text: string;
	context: string | null;
	contribution: string | null;
	outcome: string | null;
	score: number;
	matched_substring: boolean;
}

// Raw shapes of the job SSE stream (app/routers/jobs.py::_sse). v2's
// reduced event set (§3/§7): everything else (requirement_added,
// requirement_status, judgment_updated, progress) is gone -- the
// create-job and add-requirement responses already carry the full
// requirement, and there's no mid-flight state left to report.
// job_updated fires whenever the job row itself changes -- most
// importantly judging_started_at/judging_deadline, which the background
// task sets well after submit-jd's own response already went out with
// them null (see jobs.py for why this is needed).
export type JobStreamEvent =
	| {
			event: 'requirement_judged';
			requirement_id: number;
			judgments: Judgment[];
			reason: string | null;
			verdict: RequirementVerdict;
	  }
	| { event: 'judging_finished'; job_id: number }
	| { event: 'job_updated'; job: Job };

export interface TimingHistory {
	avg_seconds_total: number | null;
	avg_seconds_to_first_result: number | null;
	sample_size: number;
}

// --- Enrichment screen (milestone 2) ---

export interface EnrichmentRequirementRef {
	id: number;
	text: string;
	weight: Weight;
}

export interface EnrichmentUnit {
	unit: SavedUnit;
	matched_requirements: EnrichmentRequirementRef[];
	complete: boolean;
}

export interface EnrichQuestions {
	context: string;
	contribution: string;
	outcome: string;
}

export interface EnrichmentResponse {
	units: EnrichmentUnit[];
	enriched_count: number;
	total_count: number;
	questions: EnrichQuestions;
}

// --- Pair builder and statements (milestone 3) ---

export type StatementStatus = 'unanswered' | 'written' | 'none';

export interface Statement {
	id: number;
	status: StatementStatus;
	text: string | null;
	autofilled_from_job_id: number | null;
	autofilled_from_job_title: string | null;
	autofilled_from_date: string | null;
	confirmed: boolean;
}

export interface Pair {
	id: number;
	unit_a: SavedUnit;
	unit_b: SavedUnit;
	statement: Statement;
}

export interface PairsListResponse {
	pairs: Pair[];
	all_ready: boolean;
}

export interface RemovedPair {
	unit_a_id: number;
	unit_b_id: number;
	had_written_statement: boolean;
}

export interface BuildPairsResponse {
	pair_count: number;
	removed: RemovedPair[];
}

export interface AutofillResponse {
	autofilled_count: number;
}

// --- Thread discovery (milestone 4) ---

export interface ThreadUnit {
	unit: SavedUnit;
	model_verdict: string | null;
	quote: string | null;
	user_verdict: string | null;
}

export interface ThreadStatement {
	statement_id: number;
	text: string | null;
	unit_a: SavedUnit;
	unit_b: SavedUnit;
	origin: 'proposed' | 'assigned' | 'user';
}

export interface Thread {
	id: number;
	idea: string;
	edited_idea: string | null;
	source: 'model' | 'user';
	stale: boolean;
	below_min: boolean;
	statements: ThreadStatement[];
	units: ThreadUnit[];
}

export interface ThreadRun {
	id: number;
	job_id: number;
	created_at: string;
	error: string | null;
	threads: Thread[];
	proposed_count: number | null;
	moved_count: number | null;
	removed_count: number | null;
	seconds_total: number | null;
}

export interface ThreadRunSummary {
	id: number;
	created_at: string;
	error: string | null;
}

export interface ThreadRunHistoryResponse {
	runs: ThreadRunSummary[];
}

export interface RunThreadsBlockedReason {
	blocked: boolean;
	reason: string | null;
}

// --- Primary/secondary ranking (milestone 5) ---

export interface RequirementRef {
	id: number;
	text: string;
	weight: Weight;
	// Weak section groups only (milestone 6) -- empty/absent elsewhere.
	pointers?: LetterPointer[];
}

export interface RankedThread extends Thread {
	covered_requirements: RequirementRef[];
	uncovered_requirements: RequirementRef[];
	support_count: number;
	exempt_from_min_support: boolean;
}

export interface PrimarySecondarySlot {
	thread: RankedThread | null;
	choice_stale: boolean;
}

export interface PrimarySecondaryResponse {
	primary: PrimarySecondarySlot;
	secondary: PrimarySecondarySlot;
	other_candidates: RankedThread[];
	empty_reason: string | null;
}

// --- Writing view (milestone 6) ---

export interface LetterPointer {
	unit_id: number;
	verdict: string;
	quote: string | null;
	line: string;
	is_primary: boolean;
	is_secondary: boolean;
}

export interface LetterSection {
	key: string;
	kind: 'plain' | 'requirement' | 'weak' | 'gaps';
	text: string;
	skipped: boolean;
	word_count: number;
	requirement_id: number | null;
	requirement_text: string | null;
	weight: Weight | null;
	verdict: string | null;
	pointers: LetterPointer[];
	proposed_pointer_text: string | null;
	pointer_text: string | null;
	pointers_edited: boolean;
	requirements: RequirementRef[];
}

export interface ThreadBar {
	thread_id: number | null;
	idea: string | null;
	edited_idea: string | null;
	statements: string[];
}

export interface OpeningHint {
	company: string | null;
	role_title: string | null;
	statement_text: string | null;
	statement_quote: string | null;
	question: string;
}

export interface CloseHint {
	uncovered: RequirementRef[];
	question: string;
}

export interface Letter {
	job_id: number;
	sections: LetterSection[];
	matched_shown: number;
	matched_total: number;
	matched_sections_setting: number;
	total_word_count: number;
	section_char_limit: number | null;
	greeting: string | null;
	signoff: string | null;
	assembled_text: string | null;
	finished: boolean;
	primary: ThreadBar;
	secondary: ThreadBar;
	opening_hint: OpeningHint;
	close_hint: CloseHint;
}

export interface GenerateResult {
	assembled_text: string;
	word_count: number;
}

// --- Settings persistence (milestone 7) ---

export interface Setting {
	key: string;
	group: string;
	type: 'int' | 'float' | 'bool' | 'str' | 'int_or_none' | 'str_list';
	default: unknown;
	value: unknown;
	is_default: boolean;
}

export interface SettingsResponse {
	settings: Setting[];
}
