import {
	attachUnit as apiAttachUnit,
	deleteRequirement as apiDeleteRequirement,
	finishWindow as apiFinishWindow,
	getFlow,
	getInventory,
	getJob,
	markNoMatch as apiMarkNoMatch,
	patchJobDetails as apiPatchJobDetails,
	patchJobTitle as apiPatchJobTitle,
	patchJudgment as apiPatchJudgment,
	patchRequirement as apiPatchRequirement,
	addRequirement as apiAddRequirement,
	resumeJudging as apiResumeJudging,
	retryExtraction as apiRetryExtraction,
	startJudging as apiStartJudging,
	submitJd as apiSubmitJd,
	streamJobEvents
} from './api';
import type { Flow, Job, Judgment, JobStreamEvent, Requirement, RequirementVerdict, SavedUnit, Verdict } from './types';

interface RequirementEntry {
	requirement: Requirement;
	judgments: Judgment[];
	verdict: RequirementVerdict;
}

class JobStore {
	job = $state<Job | null>(null);
	// Resolved separately (Job only carries flow_id) -- needed for the
	// "Add unit" search, which is scoped to an inventory, not a job.
	flow = $state<Flow | null>(null);
	// v2: judgment rows carry no unit text at all (unit_snapshot is gone --
	// judging reads the unit's current text, never a frozen copy), so the
	// UI looks it up live from the inventory instead. Keyed by unit id.
	units = $state<Record<number, SavedUnit>>({});
	// Keyed by requirement id, in a plain object so Svelte 5's $state proxy
	// tracks per-key mutation. Row order comes from requirementIds, which is
	// re-sorted by sort_order whenever a requirement is added/loaded.
	entries = $state<Record<number, RequirementEntry>>({});
	requirementIds = $state<number[]>([]);

	loading = $state(false);
	error = $state<string | null>(null);
	streamError = $state<string | null>(null);

	// Per-judgment optimistic-update failure message, keyed by judgment id,
	// so one failed chip click doesn't block or blank out other rows.
	judgmentErrors = $state<Record<number, string>>({});

	// True once the server has told us the window ended (judging_finished).
	// Drives the "Judged X of Y..." banner (§3).
	judgingFinished = $state(false);

	private abortController: AbortController | null = null;
	// Set by load()/connect() so other methods can re-arm the stream
	// without the caller having to thread jobId through everywhere.
	private jobId: number | null = null;
	// True only while the connect() loop below is actively running. Without
	// this, calling connect() again while a loop is mid-stream would spawn a
	// second concurrent loop instead of reusing the live one.
	private streaming = false;

	doneCount = $derived(this.requirementIds.filter((id) => this.entries[id]?.requirement.status === 'done').length);
	totalCount = $derived(this.requirementIds.length);
	allDone = $derived(this.requirementIds.length > 0 && this.doneCount === this.requirementIds.length);

	// Timing: derived from persisted timestamps, not a client-side
	// stopwatch, so it survives a refresh/reconnect.
	firstJudgedAt = $derived.by(() => {
		const timestamps = this.requirementIds
			.map((id) => this.entries[id]?.requirement.judged_at)
			.filter((t): t is string => !!t)
			.sort();
		return timestamps[0] ?? null;
	});
	lastJudgedAt = $derived.by(() => {
		const timestamps = this.requirementIds
			.map((id) => this.entries[id]?.requirement.judged_at)
			.filter((t): t is string => !!t)
			.sort();
		return timestamps[timestamps.length - 1] ?? null;
	});
	// "Running" is derived exactly as the backend derives it (§3): now <
	// judging_deadline. There's no client-side notion of "still processing"
	// beyond this -- once judging_finished arrives, this always reads false.
	windowOpen = $derived.by(() => {
		if (this.judgingFinished) return false;
		const deadline = this.job?.judging_deadline;
		if (!deadline) return false;
		return new Date(deadline + 'Z').getTime() > Date.now();
	});

	// §3.1: the JD screen's Submit button is enabled only when the current
	// draft differs from what was last submitted (null counts as "never").
	hasEverSubmitted = $derived(this.job?.jd_submitted_text !== null && this.job?.jd_submitted_text !== undefined);

	// Judging no longer starts automatically after extraction -- this
	// mirrors the backend's own rule for "has it ever started" (never
	// "is it running now"): a judging_deadline, or a requirement already
	// judged, counts even for a job that started the old automatic way.
	judgingStarted = $derived(this.job?.judging_deadline != null || this.firstJudgedAt !== null);

	private upsertRequirement(req: Requirement) {
		if (!this.entries[req.id]) {
			this.entries[req.id] = { requirement: req, judgments: [], verdict: 'gap' };
			this.requirementIds = [...this.requirementIds, req.id].sort(
				(a, b) => (this.entries[a]?.requirement.sort_order ?? 0) - (this.entries[b]?.requirement.sort_order ?? 0)
			);
		} else {
			this.entries[req.id].requirement = req;
		}
	}

	private applyFullMap(job: Job, requirements: RequirementEntry[]) {
		this.job = job;
		this.entries = {};
		for (const item of requirements) this.entries[item.requirement.id] = item;
		this.requirementIds = requirements
			.map((r) => r.requirement.id)
			.sort((a, b) => this.entries[a].requirement.sort_order - this.entries[b].requirement.sort_order);
	}

	async load(jobId: number) {
		this.jobId = jobId;
		this.loading = true;
		this.error = null;
		this.judgingFinished = false;
		let flowId: number;
		try {
			const body = await getJob(jobId);
			this.applyFullMap(body.job, body.requirements);
			flowId = body.job.flow_id;
		} catch (e) {
			this.error = e instanceof Error ? e.message : 'Failed to load job.';
			this.loading = false;
			return;
		}
		this.loading = false;

		// Best-effort: the "Add unit" search just stays disabled if this fails.
		try {
			this.flow = await getFlow(flowId);
		} catch {
			this.flow = null;
			return;
		}

		// Best-effort: a judgment row just shows no text if this fails.
		try {
			const inventory = await getInventory(this.flow.inventory_id);
			const units: Record<number, SavedUnit> = {};
			for (const role of inventory.roles) {
				for (const unit of role.units) units[unit.id] = unit;
			}
			this.units = units;
		} catch {
			this.units = {};
		}
	}

	// Opens the SSE stream. Idempotent event handler below tolerates the
	// server replaying requirement_judged for already-known rows on a fresh
	// connection (see jobs.py). No-op if a loop is already running, and the
	// stream naturally ends once judging_finished arrives or the job has
	// nothing left to watch for.
	async connect(jobId: number) {
		this.jobId = jobId;
		if (this.streaming) return;

		this.disconnect();
		this.abortController = new AbortController();
		const signal = this.abortController.signal;
		this.streaming = true;

		try {
			let attempts = 0;
			while (!signal.aborted && !this.judgingFinished && !this.allDone && attempts < 5) {
				try {
					this.streamError = null;
					await streamJobEvents(jobId, (event) => this.applyEvent(event), signal);
					attempts = 0; // a clean stream end resets backoff
				} catch (e) {
					if (signal.aborted) break;
					attempts += 1;
					this.streamError = e instanceof Error ? e.message : 'Live updates disconnected.';
					await new Promise((r) => setTimeout(r, Math.min(1000 * attempts, 5000)));
				}
			}
		} finally {
			this.streaming = false;
		}
	}

	disconnect() {
		this.abortController?.abort();
		this.abortController = null;
	}

	private applyEvent(event: JobStreamEvent) {
		if (event.event === 'requirement_judged') {
			const entry = this.entries[event.requirement_id];
			if (!entry) return; // deleted locally since the event was queued server-side
			entry.judgments = event.judgments;
			entry.verdict = event.verdict;
			entry.requirement = { ...entry.requirement, status: 'done', reason: event.reason };
		} else if (event.event === 'judging_finished') {
			this.judgingFinished = true;
		} else if (event.event === 'job_updated') {
			this.job = event.job;
		}
	}

	async patchTitle(jobId: number, title: string) {
		const job = await apiPatchJobTitle(jobId, title);
		this.job = job;
	}

	// Optional, user-typed, saved the same way the title is -- no model
	// call, never blocked by an open window.
	async patchDetails(jobId: number, payload: { company?: string | null; role_title?: string | null }) {
		const job = await apiPatchJobDetails(jobId, payload);
		this.job = job;
	}

	// §3.1: first submit, or a resubmit of changed JD text (the caller is
	// responsible for the "this will discard..." confirm before calling).
	// A resubmit wipes this job's requirements -- reload fully rather than
	// patch piecemeal. Extraction alone never starts judging now, so this
	// doesn't connect() -- startJudging() below does, once there's
	// actually something worth polling for.
	async submitJd(jobId: number, jdText: string) {
		const body = await apiSubmitJd(jobId, jdText);
		this.applyFullMap(body.job, body.requirements);
		this.judgingFinished = false;
	}

	async retryExtraction(jobId: number) {
		const body = await apiRetryExtraction(jobId);
		this.applyFullMap(body.job, body.requirements);
		this.judgingFinished = false;
	}

	// The review step's explicit continuation -- same shape as submitJd:
	// the response's own judging_deadline is still null (only set inside
	// the detached background task), so connect() is what actually shows
	// the window once job_updated/requirement_judged events catch it up.
	async startJudging(jobId: number) {
		const job = await apiStartJudging(jobId);
		this.job = job;
		this.judgingFinished = false;
		this.connect(jobId);
	}

	// Bug B's companion: resumes a window that closed with requirements
	// still pending (the window ran out, or its background task died).
	// Same shape as startJudging -- a brand-new window, same reconnect.
	async resumeJudging(jobId: number) {
		const job = await apiResumeJudging(jobId);
		this.job = job;
		this.judgingFinished = false;
		this.connect(jobId);
	}

	// Finish button, or "Go back" on the leave-while-judging warning.
	async finish(jobId: number) {
		const job = await apiFinishWindow(jobId);
		this.job = job;
	}

	async addRequirement(jobId: number, text: string, weight: string) {
		const req = await apiAddRequirement(jobId, text, weight);
		this.upsertRequirement(req);
	}

	// §3 rule 10: editing text/weight never touches verdicts or status.
	async editRequirement(requirementId: number, payload: { text?: string; weight?: string }) {
		const req = await apiPatchRequirement(requirementId, payload);
		const entry = this.entries[requirementId];
		if (entry) entry.requirement = req;
	}

	async deleteRequirement(requirementId: number) {
		await apiDeleteRequirement(requirementId);
		delete this.entries[requirementId];
		this.requirementIds = this.requirementIds.filter((id) => id !== requirementId);
	}

// Optimistic: flips the chip immediately, rolls back and shows an inline
	// error if the PATCH fails. Never computes match/weak/gap itself — the
	// backend hands back the requirement's updated verdict directly.
	// Setting a real verdict can also complete a pending requirement (no
	// separate "Done" action) -- requirement_status reflects that.
	async cycleVerdict(requirementId: number, judgmentId: number, next: Verdict) {
		const entry = this.entries[requirementId];
		if (!entry) return;
		const judgment = entry.judgments.find((j) => j.id === judgmentId);
		if (!judgment) return;

		const previous = judgment.user_verdict;
		judgment.user_verdict = next;
		delete this.judgmentErrors[judgmentId];

		try {
			const result = await apiPatchJudgment(judgmentId, next);
			judgment.user_verdict = result.judgment.user_verdict;
			judgment.why = result.judgment.why;
			entry.verdict = result.requirement_verdict;
			entry.requirement = { ...entry.requirement, status: result.requirement_status };
		} catch (e) {
			judgment.user_verdict = previous;
			this.judgmentErrors[judgmentId] = e instanceof Error ? e.message : 'Failed to update verdict.';
		}
	}

	async addUnit(requirementId: number, unitId: number) {
		const entry = this.entries[requirementId];
		if (!entry) return;
		const result = await apiAttachUnit(requirementId, unitId);
		entry.judgments = [...entry.judgments, result.judgment];
		entry.verdict = result.requirement_verdict;
		entry.requirement = { ...entry.requirement, status: result.requirement_status };
	}

	// Manual "No match": clears every selection and marks the requirement
	// done with no match (reads as a gap). No model call; to undo, the user
	// attaches a unit or sets a verdict as usual.
	async markNoMatch(requirementId: number) {
		const result = await apiMarkNoMatch(requirementId);
		const entry = this.entries[requirementId];
		if (!entry) return;
		entry.judgments = result.judgments;
		entry.verdict = result.verdict;
		entry.requirement = result.requirement;
	}
}

export const jobStore = new JobStore();
