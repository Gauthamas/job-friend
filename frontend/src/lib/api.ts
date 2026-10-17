import type {
	AutofillResponse,
	BuildPairsResponse,
	CommitRequestPayload,
	CommitResponse,
	AttachUnitResponse,
	EnrichmentResponse,
	Flow,
	GenerateResult,
	InventoryDetail,
	InventoryListItem,
	InventoryStreamEvent,
	Job,
	JobCreateResponse,
	JobFullMapResponse,
	JobListResponse,
	JobProgress,
	JobStreamEvent,
	JudgmentPatchResponse,
	Letter,
	MergeUnitsResult,
	PairsListResponse,
	PrimarySecondaryResponse,
	ProceedResponse,
	Requirement,
	RequirementWithJudgments,
	RunThreadsBlockedReason,
	SavedUnit,
	SettingsResponse,
	SplitUnitResult,
	Statement,
	StatementStatus,
	Thread,
	ThreadRun,
	TimingHistory,
	UnitPatchPayload,
	UnitSearchResult,
	Verdict
} from './types';

async function unwrap<T>(res: Response): Promise<T> {
	if (!res.ok) {
		const body = await res.text();
		throw new Error(`${res.status}: ${body}`);
	}
	return res.json();
}

// Reads the inventory-creation endpoint's SSE stream ("data: {...}\n\n" per
// event) and calls onEvent for each one, including the terminal "done" or
// "error" event. Resolves once the stream ends.
async function readInventorySse(res: Response, onEvent: (event: InventoryStreamEvent) => void): Promise<void> {
	if (!res.ok || !res.body) {
		const body = await res.text();
		throw new Error(`${res.status}: ${body}`);
	}

	const reader = res.body.getReader();
	const decoder = new TextDecoder();
	let buffer = '';

	while (true) {
		const { done, value } = await reader.read();
		if (done) break;
		buffer += decoder.decode(value, { stream: true });

		let blockEnd: number;
		while ((blockEnd = buffer.indexOf('\n\n')) !== -1) {
			const block = buffer.slice(0, blockEnd);
			buffer = buffer.slice(blockEnd + 2);
			const line = block.split('\n').find((l) => l.startsWith('data: '));
			if (!line) continue;
			onEvent(JSON.parse(line.slice('data: '.length)));
		}
	}
}

export async function createInventoryFromText(
	name: string,
	text: string,
	onEvent: (event: InventoryStreamEvent) => void
): Promise<void> {
	const form = new FormData();
	form.set('name', name);
	form.set('text', text);
	const res = await fetch('/api/inventories', { method: 'POST', body: form });
	return readInventorySse(res, onEvent);
}

export async function createInventoryFromFile(
	name: string,
	file: File,
	onEvent: (event: InventoryStreamEvent) => void
): Promise<void> {
	const form = new FormData();
	form.set('name', name);
	form.set('file', file);
	const res = await fetch('/api/inventories', { method: 'POST', body: form });
	return readInventorySse(res, onEvent);
}

export async function commitInventory(
	inventoryId: number,
	payload: CommitRequestPayload
): Promise<CommitResponse> {
	const res = await fetch(`/api/inventories/${inventoryId}/commit`, {
		method: 'POST',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify(payload)
	});
	return unwrap(res);
}

export async function listInventories(): Promise<InventoryListItem[]> {
	const res = await fetch('/api/inventories');
	const body = await unwrap<{ inventories: InventoryListItem[] }>(res);
	return body.inventories;
}

export async function discardInventory(inventoryId: number): Promise<void> {
	const res = await fetch(`/api/inventories/${inventoryId}`, { method: 'DELETE' });
	if (!res.ok) {
		const body = await res.text();
		throw new Error(`${res.status}: ${body}`);
	}
}

export async function getInventory(inventoryId: number, includeDiscarded = false): Promise<InventoryDetail> {
	const res = await fetch(`/api/inventories/${inventoryId}${includeDiscarded ? '?include_discarded=true' : ''}`);
	return unwrap(res);
}

export async function getUnit(unitId: number): Promise<SavedUnit> {
	const res = await fetch(`/api/units/${unitId}`);
	return unwrap(res);
}

export async function patchUnit(unitId: number, payload: UnitPatchPayload): Promise<SavedUnit> {
	const res = await fetch(`/api/units/${unitId}`, {
		method: 'PATCH',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify(payload)
	});
	return unwrap(res);
}

export async function deleteUnit(unitId: number): Promise<void> {
	const res = await fetch(`/api/units/${unitId}`, { method: 'DELETE' });
	if (!res.ok) {
		const body = await res.text();
		throw new Error(`${res.status}: ${body}`);
	}
}

export async function discardUnit(unitId: number): Promise<SavedUnit> {
	const res = await fetch(`/api/units/${unitId}/discard`, { method: 'POST' });
	return unwrap(res);
}

export async function restoreUnit(unitId: number): Promise<SavedUnit> {
	const res = await fetch(`/api/units/${unitId}/restore`, { method: 'POST' });
	return unwrap(res);
}

export async function discardRole(roleId: number): Promise<{ id: number; discarded_at: string | null }> {
	const res = await fetch(`/api/roles/${roleId}/discard`, { method: 'POST' });
	return unwrap(res);
}

export async function restoreRole(roleId: number): Promise<{ id: number; discarded_at: string | null }> {
	const res = await fetch(`/api/roles/${roleId}/restore`, { method: 'POST' });
	return unwrap(res);
}

export async function splitUnit(unitId: number, splitAt: number): Promise<SplitUnitResult> {
	const res = await fetch(`/api/units/${unitId}/split`, {
		method: 'POST',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify({ split_at: splitAt })
	});
	return unwrap(res);
}

export async function mergeUnits(targetUnitId: number, otherUnitId: number): Promise<MergeUnitsResult> {
	const res = await fetch(`/api/units/${targetUnitId}/merge`, {
		method: 'POST',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify({ other_unit_id: otherUnitId })
	});
	return unwrap(res);
}

export async function addSavedUnit(
	roleId: number,
	payload: { text: string; context?: string | null; contribution?: string | null; outcome?: string | null; skills_json?: string | null }
): Promise<SavedUnit> {
	const res = await fetch(`/api/roles/${roleId}/units`, {
		method: 'POST',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify(payload)
	});
	return unwrap(res);
}

// --- Requirement map review ---

export async function listFlows(includeDiscarded = false): Promise<Flow[]> {
	const res = await fetch(`/api/flows${includeDiscarded ? '?include_discarded=true' : ''}`);
	const body = await unwrap<{ flows: Flow[] }>(res);
	return body.flows;
}

export async function createFlow(name: string, inventoryId: number): Promise<Flow> {
	const res = await fetch('/api/flows', {
		method: 'POST',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify({ name, inventory_id: inventoryId })
	});
	return unwrap(res);
}

export async function getFlow(flowId: number): Promise<Flow> {
	const res = await fetch(`/api/flows/${flowId}`);
	return unwrap(res);
}

// §3.1: job creation is now just a title -- the JD screen handles
// extraction via submitJd below.
export async function createJob(flowId: number, title: string): Promise<JobCreateResponse> {
	const res = await fetch(`/api/flows/${flowId}/jobs`, {
		method: 'POST',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify({ title })
	});
	return unwrap(res);
}

export async function listFlowJobs(flowId: number): Promise<Job[]> {
	const res = await fetch(`/api/flows/${flowId}/jobs`);
	const body = await unwrap<JobListResponse>(res);
	return body.jobs;
}

export async function getJobProgress(jobId: number): Promise<JobProgress> {
	const res = await fetch(`/api/jobs/${jobId}/progress`);
	return unwrap(res);
}

export async function patchJobTitle(jobId: number, title: string): Promise<Job> {
	const res = await fetch(`/api/jobs/${jobId}`, {
		method: 'PATCH',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify({ title })
	});
	return unwrap(res);
}

export async function patchJobDetails(
	jobId: number,
	payload: { company?: string | null; role_title?: string | null }
): Promise<Job> {
	const res = await fetch(`/api/jobs/${jobId}`, {
		method: 'PATCH',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify(payload)
	});
	return unwrap(res);
}

export async function discardJob(jobId: number): Promise<Job> {
	const res = await fetch(`/api/jobs/${jobId}/discard`, { method: 'POST' });
	return unwrap(res);
}

export async function restoreJob(jobId: number): Promise<Job> {
	const res = await fetch(`/api/jobs/${jobId}/restore`, { method: 'POST' });
	return unwrap(res);
}

export async function submitJd(jobId: number, jdText: string): Promise<JobFullMapResponse> {
	const res = await fetch(`/api/jobs/${jobId}/submit-jd`, {
		method: 'POST',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify({ jd_text: jdText })
	});
	return unwrap(res);
}

export async function retryExtraction(jobId: number): Promise<JobFullMapResponse> {
	const res = await fetch(`/api/jobs/${jobId}/retry-extraction`, { method: 'POST' });
	return unwrap(res);
}

// Judging no longer starts automatically after extraction -- this is the
// explicit continuation, after the user has had a chance to review/edit
// requirements.
export async function startJudging(jobId: number): Promise<Job> {
	const res = await fetch(`/api/jobs/${jobId}/start-judging`, { method: 'POST' });
	return unwrap(res);
}

export async function resumeJudging(jobId: number): Promise<Job> {
	const res = await fetch(`/api/jobs/${jobId}/resume-judging`, { method: 'POST' });
	return unwrap(res);
}

export async function finishWindow(jobId: number): Promise<Job> {
	const res = await fetch(`/api/jobs/${jobId}/finish`, { method: 'POST' });
	return unwrap(res);
}

export async function proceed(jobId: number): Promise<ProceedResponse> {
	const res = await fetch(`/api/jobs/${jobId}/proceed`, { method: 'POST' });
	return unwrap(res);
}

export async function getJob(jobId: number): Promise<JobFullMapResponse> {
	const res = await fetch(`/api/jobs/${jobId}`);
	return unwrap(res);
}

export async function getEnrichment(jobId: number): Promise<EnrichmentResponse> {
	const res = await fetch(`/api/jobs/${jobId}/enrichment`);
	return unwrap(res);
}

export async function buildPairs(jobId: number): Promise<BuildPairsResponse> {
	const res = await fetch(`/api/jobs/${jobId}/pairs/build`, { method: 'POST' });
	return unwrap(res);
}

export async function getPairs(jobId: number): Promise<PairsListResponse> {
	const res = await fetch(`/api/jobs/${jobId}/pairs`);
	return unwrap(res);
}

export async function autofillPairs(jobId: number): Promise<AutofillResponse> {
	const res = await fetch(`/api/jobs/${jobId}/pairs/autofill`, { method: 'POST' });
	return unwrap(res);
}

export async function startFreshPairs(jobId: number): Promise<void> {
	const res = await fetch(`/api/jobs/${jobId}/pairs/fresh`, { method: 'POST' });
	await unwrap(res);
}

export async function confirmAllStatements(jobId: number): Promise<void> {
	const res = await fetch(`/api/jobs/${jobId}/statements/confirm-all`, { method: 'POST' });
	await unwrap(res);
}

export async function patchStatement(
	statementId: number,
	body: { status: StatementStatus; text?: string | null }
): Promise<Statement> {
	const res = await fetch(`/api/statements/${statementId}`, {
		method: 'PATCH',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify(body)
	});
	return unwrap(res);
}

export async function canRunThreads(jobId: number): Promise<RunThreadsBlockedReason> {
	const res = await fetch(`/api/jobs/${jobId}/threads/can-run`);
	return unwrap(res);
}

export async function runThreads(jobId: number): Promise<ThreadRun> {
	const res = await fetch(`/api/jobs/${jobId}/threads/run`, { method: 'POST' });
	return unwrap(res);
}

export async function getLatestThreads(jobId: number): Promise<ThreadRun> {
	const res = await fetch(`/api/jobs/${jobId}/threads`);
	return unwrap(res);
}

export async function patchThreadIdea(threadId: number, idea: string): Promise<Thread> {
	const res = await fetch(`/api/threads/${threadId}`, {
		method: 'PATCH',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify({ idea })
	});
	return unwrap(res);
}

export async function deleteThread(threadId: number): Promise<void> {
	const res = await fetch(`/api/threads/${threadId}`, { method: 'DELETE' });
	if (!res.ok) throw new Error(`${res.status}: ${await res.text()}`);
}

export async function moveStatementToThread(threadId: number, statementId: number): Promise<Thread> {
	const res = await fetch(`/api/threads/${threadId}/statements`, {
		method: 'POST',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify({ statement_id: statementId })
	});
	return unwrap(res);
}

export async function removeStatementFromThread(threadId: number, statementId: number): Promise<Thread> {
	const res = await fetch(`/api/threads/${threadId}/statements/${statementId}`, { method: 'DELETE' });
	return unwrap(res);
}

export async function mergeThreads(threadId: number, otherThreadId: number): Promise<Thread> {
	const res = await fetch(`/api/threads/${threadId}/merge`, {
		method: 'POST',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify({ other_thread_id: otherThreadId })
	});
	return unwrap(res);
}

export async function createManualThread(jobId: number, idea: string, statementIds: number[]): Promise<Thread> {
	const res = await fetch(`/api/jobs/${jobId}/threads/manual`, {
		method: 'POST',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify({ idea, statement_ids: statementIds })
	});
	return unwrap(res);
}

export async function getPrimarySecondary(jobId: number): Promise<PrimarySecondaryResponse> {
	const res = await fetch(`/api/jobs/${jobId}/primary-secondary`);
	return unwrap(res);
}

export async function suggestPrimarySecondary(jobId: number): Promise<PrimarySecondaryResponse> {
	const res = await fetch(`/api/jobs/${jobId}/primary-secondary/suggest`, { method: 'POST' });
	return unwrap(res);
}

export async function choosePrimarySecondary(
	jobId: number,
	threadId: number,
	role: 'primary' | 'secondary'
): Promise<PrimarySecondaryResponse> {
	const res = await fetch(`/api/jobs/${jobId}/primary-secondary/choose`, {
		method: 'POST',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify({ thread_id: threadId, role })
	});
	return unwrap(res);
}

export async function swapPrimarySecondary(jobId: number): Promise<PrimarySecondaryResponse> {
	const res = await fetch(`/api/jobs/${jobId}/primary-secondary/swap`, { method: 'POST' });
	return unwrap(res);
}

export async function clearSecondary(jobId: number): Promise<PrimarySecondaryResponse> {
	const res = await fetch(`/api/jobs/${jobId}/primary-secondary/secondary`, { method: 'DELETE' });
	return unwrap(res);
}

export async function getLetter(jobId: number): Promise<Letter> {
	const res = await fetch(`/api/jobs/${jobId}/letter`);
	return unwrap(res);
}

export async function patchLetter(jobId: number, body: { greeting?: string; signoff?: string }): Promise<Letter> {
	const res = await fetch(`/api/jobs/${jobId}/letter`, {
		method: 'PATCH',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify(body)
	});
	return unwrap(res);
}

export async function patchLetterSection(
	jobId: number,
	key: string,
	body: { text?: string; skipped?: boolean }
): Promise<Letter> {
	const res = await fetch(`/api/jobs/${jobId}/letter/sections/${key}`, {
		method: 'PATCH',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify(body)
	});
	return unwrap(res);
}

export async function patchLetterPointers(jobId: number, key: string, text: string | null): Promise<Letter> {
	const res = await fetch(`/api/jobs/${jobId}/letter/pointers/${key}`, {
		method: 'PATCH',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify({ text })
	});
	return unwrap(res);
}

export async function generateLetter(jobId: number): Promise<GenerateResult> {
	const res = await fetch(`/api/jobs/${jobId}/letter/generate`, { method: 'POST' });
	return unwrap(res);
}

export async function finishLetter(jobId: number): Promise<Letter> {
	const res = await fetch(`/api/jobs/${jobId}/letter/finish`, { method: 'POST' });
	return unwrap(res);
}

export async function patchMatchedSections(value: number): Promise<{ value: number }> {
	const res = await fetch(`/api/settings/matched-sections`, {
		method: 'PATCH',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify({ value })
	});
	return unwrap(res);
}

export async function getSettings(): Promise<SettingsResponse> {
	const res = await fetch(`/api/settings`);
	return unwrap(res);
}

export async function patchSettings(values: Record<string, unknown>): Promise<SettingsResponse> {
	const res = await fetch(`/api/settings`, {
		method: 'PATCH',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify({ values })
	});
	return unwrap(res);
}

export async function resetSetting(key: string): Promise<SettingsResponse> {
	const res = await fetch(`/api/settings/${key}`, { method: 'DELETE' });
	return unwrap(res);
}

export async function promoteThread(threadId: number): Promise<Thread> {
	const res = await fetch(`/api/threads/${threadId}/promote`, { method: 'POST' });
	return unwrap(res);
}

export async function addRequirement(jobId: number, text: string, weight: string): Promise<Requirement> {
	const res = await fetch(`/api/jobs/${jobId}/requirements`, {
		method: 'POST',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify({ text, weight })
	});
	return unwrap(res);
}

export async function patchRequirement(
	requirementId: number,
	payload: { text?: string; weight?: string }
): Promise<Requirement> {
	const res = await fetch(`/api/requirements/${requirementId}`, {
		method: 'PATCH',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify(payload)
	});
	return unwrap(res);
}

export async function deleteRequirement(requirementId: number): Promise<void> {
	const res = await fetch(`/api/requirements/${requirementId}`, { method: 'DELETE' });
	if (!res.ok) {
		const body = await res.text();
		throw new Error(`${res.status}: ${body}`);
	}
}

export async function patchJudgment(judgmentId: number, userVerdict: Verdict | null): Promise<JudgmentPatchResponse> {
	const res = await fetch(`/api/judgments/${judgmentId}`, {
		method: 'PATCH',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify({ user_verdict: userVerdict })
	});
	return unwrap(res);
}

export async function attachUnit(requirementId: number, unitId: number): Promise<AttachUnitResponse> {
	const res = await fetch(`/api/requirements/${requirementId}/units`, {
		method: 'POST',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify({ unit_id: unitId })
	});
	return unwrap(res);
}

export async function markNoMatch(requirementId: number): Promise<RequirementWithJudgments> {
	const res = await fetch(`/api/requirements/${requirementId}/no-match`, { method: 'POST' });
	return unwrap(res);
}

export async function searchInventory(inventoryId: number, q: string): Promise<UnitSearchResult[]> {
	const res = await fetch(`/api/inventories/${inventoryId}/search?q=${encodeURIComponent(q)}`);
	const body = await unwrap<{ results: UnitSearchResult[] }>(res);
	return body.results;
}

export async function getTimingHistory(phase: 'extraction' | 'judging' | 'threads'): Promise<TimingHistory> {
	const res = await fetch(`/api/timing-history?phase=${phase}`);
	return unwrap(res);
}

// Same manual reader-loop pattern as readInventorySse (see its comment) —
// used here instead of native EventSource so both SSE consumers in the app
// share one implementation.
export function streamJobEvents(
	jobId: number,
	onEvent: (event: JobStreamEvent) => void,
	signal: AbortSignal
): Promise<void> {
	return (async () => {
		const res = await fetch(`/api/jobs/${jobId}/events`, { signal });
		if (!res.ok || !res.body) {
			const body = await res.text();
			throw new Error(`${res.status}: ${body}`);
		}

		const reader = res.body.getReader();
		const decoder = new TextDecoder();
		let buffer = '';

		while (true) {
			const { done, value } = await reader.read();
			if (done) break;
			buffer += decoder.decode(value, { stream: true });

			let blockEnd: number;
			while ((blockEnd = buffer.indexOf('\n\n')) !== -1) {
				const block = buffer.slice(0, blockEnd);
				buffer = buffer.slice(blockEnd + 2);
				const line = block.split('\n').find((l) => l.startsWith('data: '));
				if (!line) continue;
				onEvent(JSON.parse(line.slice('data: '.length)));
			}
		}
	})();
}
