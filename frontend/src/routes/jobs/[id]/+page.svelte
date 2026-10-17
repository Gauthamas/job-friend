<script lang="ts">
	import { onDestroy, onMount } from 'svelte';
	import { beforeNavigate, goto } from '$app/navigation';
	import { page } from '$app/state';
	import RequirementRow from '$lib/components/RequirementRow.svelte';
	import { getTimingHistory, proceed as apiProceed } from '$lib/api';
	import { jobStore } from '$lib/jobStore.svelte';
	import type { TimingHistory, Weight } from '$lib/types';

	const jobId = $derived(Number(page.params.id));

	// §3.1: which half of the page is showing. Defaults to the JD screen
	// until the first submit, then to the requirements view -- "Edit JD"
	// below switches back without losing anything (submitting again from
	// there, with changed text, is what triggers a resubmit).
	let view = $state<'jd' | 'requirements'>('jd');

	let titleDraft = $state('');
	let jdDraft = $state('');
	let titleSaving = $state(false);
	let companyDraft = $state('');
	let roleTitleDraft = $state('');
	let detailsSaving = $state(false);
	let submittingJd = $state(false);
	let jdError = $state<string | null>(null);
	let showResubmitConfirm = $state(false);
	let retrying = $state(false);
	let elapsedSeconds = $state(0);
	let elapsedTimer: ReturnType<typeof setInterval> | undefined;
	let extractionHistory = $state<TimingHistory | null>(null);

	let addingOpen = $state(false);
	let newText = $state('');
	let newWeight = $state<Weight>('medium');
	let adding = $state(false);
	let addError = $state<string | null>(null);
	let judgingHistory = $state<TimingHistory | null>(null);
	let startingJudging = $state(false);
	let startJudgingError = $state<string | null>(null);
	let finishing = $state(false);
	let bannerDismissed = $state(false);
	let proceedMessage = $state<string | null>(null);
	let proceedNoMatchesConfirm = $state(false);
	let resumingJudging = $state(false);
	let resumeJudgingError = $state<string | null>(null);

	// Exactly what wipe_job_requirements would delete on resubmit -- the
	// confirm text below needs the real count, not just "has it ever been
	// submitted" (which doesn't distinguish "nothing judged yet" from
	// "judgments exist, including ones set by hand").
	let totalJudgmentCount = $derived(
		Object.values(jobStore.entries).reduce((sum, e) => sum + e.judgments.length, 0)
	);

	// §3's "leaving the judging screen" warning.
	let leaveWarning = $state<{ resolve: (goBack: boolean) => void } | null>(null);

	onMount(async () => {
		await jobStore.load(jobId);
		if (jobStore.job) {
			titleDraft = jobStore.job.title;
			jdDraft = jobStore.job.jd_text;
			companyDraft = jobStore.job.company ?? '';
			roleTitleDraft = jobStore.job.role_title ?? '';
			view = jobStore.hasEverSubmitted ? 'requirements' : 'jd';
			if (jobStore.judgingStarted) jobStore.connect(jobId);
		}
		try {
			judgingHistory = await getTimingHistory('judging');
			extractionHistory = await getTimingHistory('extraction');
		} catch {
			judgingHistory = null;
			extractionHistory = null;
		}
	});

	onDestroy(() => {
		jobStore.disconnect();
	});

	// §3: "Leaving the judging screen (in-app navigation) while a window is
	// open shows a warning... Go back cancels the window exactly like
	// Finish and then navigates." Reload/tab close are deliberately not
	// intercepted here (the window continues server-side regardless).
	beforeNavigate((nav) => {
		if (!jobStore.windowOpen || leaveWarning) return;
		nav.cancel();
		leaveWarning = {
			resolve: async (goBack) => {
				leaveWarning = null;
				if (goBack) {
					await jobStore.finish(jobId);
					if (nav.to?.url) goto(nav.to.url.pathname + nav.to.url.search);
				}
			}
		};
	});

	async function saveTitle() {
		if (!jobStore.job || titleDraft.trim() === jobStore.job.title) return;
		titleSaving = true;
		try {
			await jobStore.patchTitle(jobId, titleDraft.trim());
		} finally {
			titleSaving = false;
		}
	}

	async function saveCompany() {
		if (!jobStore.job || companyDraft.trim() === (jobStore.job.company ?? '')) return;
		detailsSaving = true;
		try {
			await jobStore.patchDetails(jobId, { company: companyDraft.trim() || null });
		} finally {
			detailsSaving = false;
		}
	}

	async function saveRoleTitle() {
		if (!jobStore.job || roleTitleDraft.trim() === (jobStore.job.role_title ?? '')) return;
		detailsSaving = true;
		try {
			await jobStore.patchDetails(jobId, { role_title: roleTitleDraft.trim() || null });
		} finally {
			detailsSaving = false;
		}
	}

	function startElapsedTimer() {
		elapsedSeconds = 0;
		const startedAt = Date.now();
		elapsedTimer = setInterval(() => (elapsedSeconds = Math.floor((Date.now() - startedAt) / 1000)), 1000);
	}

	async function submitJd() {
		if (!jobStore.job) return;
		if (jobStore.hasEverSubmitted && totalJudgmentCount > 0 && !showResubmitConfirm) {
			showResubmitConfirm = true;
			return;
		}
		showResubmitConfirm = false;
		submittingJd = true;
		jdError = null;
		startElapsedTimer();
		try {
			await jobStore.submitJd(jobId, jdDraft);
			bannerDismissed = false;
			view = 'requirements';
		} catch (e) {
			jdError = e instanceof Error ? e.message : 'Failed to extract requirements from this JD.';
		} finally {
			submittingJd = false;
			clearInterval(elapsedTimer);
		}
	}

	async function retryExtraction() {
		retrying = true;
		startElapsedTimer();
		try {
			await jobStore.retryExtraction(jobId);
			view = 'requirements';
		} catch (e) {
			jdError = e instanceof Error ? e.message : 'Retry failed.';
		} finally {
			retrying = false;
			clearInterval(elapsedTimer);
		}
	}

	async function startJudging() {
		startingJudging = true;
		startJudgingError = null;
		try {
			await jobStore.startJudging(jobId);
		} catch (e) {
			startJudgingError = e instanceof Error ? e.message : 'Failed to start judging.';
		} finally {
			startingJudging = false;
		}
	}

	async function resumeJudgingClick() {
		resumingJudging = true;
		resumeJudgingError = null;
		try {
			await jobStore.resumeJudging(jobId);
		} catch (e) {
			resumeJudgingError = e instanceof Error ? e.message : 'Failed to resume judging.';
		} finally {
			resumingJudging = false;
		}
	}

	async function finishWindow() {
		finishing = true;
		try {
			await jobStore.finish(jobId);
		} finally {
			finishing = false;
		}
	}

	async function addRequirement() {
		const text = newText.trim();
		if (!text) return;
		adding = true;
		addError = null;
		try {
			await jobStore.addRequirement(jobId, text, newWeight);
			newText = '';
			addingOpen = false;
		} catch (e) {
			addError = e instanceof Error ? e.message : 'Failed to add requirement.';
		} finally {
			adding = false;
		}
	}

	async function clickProceed() {
		proceedMessage = null;
		proceedNoMatchesConfirm = false;
		try {
			const result = await apiProceed(jobId);
			if (!result.ok) {
				proceedMessage = `${result.unjudged_count} requirement${result.unjudged_count === 1 ? '' : 's'} not judged.`;
			} else if (result.no_matches) {
				proceedNoMatchesConfirm = true;
			} else {
				goto(`/jobs/${jobId}/enrichment`);
			}
		} catch (e) {
			const message = e instanceof Error ? e.message : '';
			if (message.startsWith('409')) {
				proceedMessage = 'A judging window is still open.';
			} else {
				proceedMessage = 'Failed to proceed.';
			}
		}
	}

	function elapsedBetween(fromIso: string | null, toIso: string | null): number | null {
		if (!fromIso || !toIso) return null;
		const from = new Date(fromIso.replace(' ', 'T') + 'Z').getTime();
		const to = new Date(toIso.replace(' ', 'T') + 'Z').getTime();
		return Math.max(0, (to - from) / 1000);
	}

	let timeToFirstRow = $derived(elapsedBetween(jobStore.job?.judging_started_at ?? null, jobStore.firstJudgedAt));
	let totalJudgingTime = $derived(elapsedBetween(jobStore.job?.judging_started_at ?? null, jobStore.lastJudgedAt));

	// Real judging state, not just "done or not": a window can close early
	// (see run_judging_window) while requirements are still pending, so
	// "finished" means the window closed, not that everything got judged.
	let judgingStatusLabel = $derived.by(() => {
		if (!jobStore.job?.judging_started_at) return null;
		if (jobStore.windowOpen) return 'running';
		return totalJudgingTime !== null ? `finished in ${totalJudgingTime.toFixed(1)}s` : 'finished';
	});

	let donePercent = $derived(
		jobStore.totalCount > 0 ? Math.round((jobStore.doneCount / jobStore.totalCount) * 100) : null
	);

	// §3: big, prominent countdown in whole minutes, 20 down to 0, plus a
	// seconds readout. judging_deadline is a SQLite "YYYY-MM-DD HH:MM:SS"
	// string (space-separated, UTC) -- needs the same 'T'-swap as
	// elapsedBetween above before appending 'Z', or the browser parses it
	// as local time and the countdown comes out hours off.
	let minutesLeft = $state(0);
	let secondsLeft = $state(0);
	let countdownTimer: ReturnType<typeof setInterval> | undefined;
	$effect(() => {
		clearInterval(countdownTimer);
		if (!jobStore.windowOpen || !jobStore.job?.judging_deadline) return;
		const deadlineMs = new Date(jobStore.job.judging_deadline.replace(' ', 'T') + 'Z').getTime();
		const tick = () => {
			const remainingSeconds = Math.max(0, Math.round((deadlineMs - Date.now()) / 1000));
			minutesLeft = Math.floor(remainingSeconds / 60);
			secondsLeft = remainingSeconds % 60;
		};
		tick();
		countdownTimer = setInterval(tick, 1000);
		return () => clearInterval(countdownTimer);
	});
</script>

<svelte:head>
	<title>{jobStore.job?.title ?? 'Job-Friend'}</title>
</svelte:head>

<main class="mx-auto max-w-3xl p-8 pb-16">
	<a href="/inventories" class="text-sm text-slate-500 underline">← All inventories</a>

	{#if jobStore.loading}
		<p class="mt-6 text-slate-500">Loading…</p>
	{:else if jobStore.error}
		<p class="mt-6 text-sm text-red-600">{jobStore.error}</p>
	{:else if jobStore.job}
		<input
			class="mt-2 w-full rounded border-none bg-transparent text-2xl font-semibold text-slate-900 outline-none focus:bg-slate-50"
			bind:value={titleDraft}
			onblur={saveTitle}
			disabled={titleSaving}
		/>
		{#if jobStore.job.role_title || jobStore.job.company}
			<p class="text-sm text-slate-500">
				{[jobStore.job.role_title, jobStore.job.company].filter(Boolean).join(' at ')}
			</p>
		{/if}

		{#if jobStore.job.extraction_error && view !== 'jd'}
			<!-- §3.1 extraction failure screen -->
			<div class="mt-6 rounded-lg border border-red-200 bg-red-50 p-4">
				<p class="text-sm text-red-800">Extraction failed: {jobStore.job.extraction_error}</p>
				<div class="mt-3 flex items-center gap-3">
					<button
						class="cursor-pointer rounded bg-slate-900 px-3 py-1.5 text-sm text-white disabled:opacity-50"
						disabled={retrying}
						onclick={retryExtraction}
					>
						{retrying ? 'Retrying…' : 'Retry'}
					</button>
					<button class="cursor-pointer text-sm text-slate-500 underline" onclick={() => (view = 'jd')}>
						Back to JD screen
					</button>
				</div>
				{#if retrying}
					<p class="mt-2 text-lg font-medium text-slate-700">{elapsedSeconds}s elapsed</p>
				{/if}
			</div>
		{:else if view === 'jd'}
			<!-- §3.1 JD screen -->
			<div class="mt-6 flex flex-col gap-3">
				<p class="text-sm text-slate-500">Paste the job description. Requirements are extracted and judged against this flow's inventory.</p>
				<div class="flex gap-3">
					<input
						class="w-1/2 rounded border border-slate-200 px-3 py-2 text-sm disabled:bg-slate-50"
						placeholder="Company (optional)"
						bind:value={companyDraft}
						onblur={saveCompany}
						disabled={detailsSaving}
					/>
					<input
						class="w-1/2 rounded border border-slate-200 px-3 py-2 text-sm disabled:bg-slate-50"
						placeholder="Role title (optional)"
						bind:value={roleTitleDraft}
						onblur={saveRoleTitle}
						disabled={detailsSaving}
					/>
				</div>
				<textarea
					class="min-h-[16rem] rounded border border-slate-200 px-3 py-2 text-sm disabled:bg-slate-50"
					placeholder="Paste the full job description here…"
					bind:value={jdDraft}
					disabled={submittingJd}
				></textarea>

				{#if jdError}
					<p class="text-sm text-red-600">{jdError}</p>
				{/if}

				{#if showResubmitConfirm}
					<div class="rounded border border-amber-300 bg-amber-50 p-3 text-sm text-amber-900">
						<p>
						Resubmitting clears {totalJudgmentCount} judgment{totalJudgmentCount === 1 ? '' : 's'}, including ones you
						set by hand.
					</p>
						<div class="mt-2 flex gap-2">
							<button class="cursor-pointer rounded bg-amber-700 px-3 py-1 text-sm text-white" onclick={submitJd}>
								Resubmit anyway
							</button>
							<button class="cursor-pointer text-sm text-slate-600" onclick={() => (showResubmitConfirm = false)}>
								Cancel
							</button>
						</div>
					</div>
				{:else}
					<div class="flex items-center gap-3">
						<button
							class="cursor-pointer self-start rounded-md bg-slate-900 px-4 py-2 text-sm text-white hover:bg-slate-700 disabled:cursor-not-allowed disabled:opacity-50"
							disabled={submittingJd || !jdDraft.trim() || jdDraft === jobStore.job.jd_submitted_text}
							onclick={submitJd}
						>
							{submittingJd ? 'Extracting requirements…' : 'Submit'}
						</button>
						<button
							class="cursor-pointer rounded border border-slate-300 px-4 py-2 text-sm text-slate-600 hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50"
							disabled={!jobStore.hasEverSubmitted}
							onclick={() => (view = 'requirements')}
						>
							Move forward
						</button>
					</div>
				{/if}

				{#if submittingJd}
					<p class="text-2xl font-semibold text-slate-700">
						{elapsedSeconds}s elapsed
					</p>
					{#if extractionHistory?.avg_seconds_total}
						<p class="text-xs text-slate-400">typically ~{Math.round(extractionHistory.avg_seconds_total)}s</p>
					{/if}
				{/if}
			</div>
		{:else}
			<!-- Requirements view -->
			<div class="mt-2 flex items-start justify-between gap-3">
				<div>
					<p class="mt-1 text-sm text-slate-500">
						{jobStore.doneCount} of {jobStore.totalCount} done
						{#if donePercent !== null}· {donePercent}%{/if}
					</p>
					<button class="mt-0.5 cursor-pointer text-xs text-slate-400 underline" onclick={() => (view = 'jd')}>
						Edit JD
					</button>
				</div>
				<button
					class="shrink-0 cursor-pointer rounded-md bg-slate-900 px-4 py-2 text-sm text-white hover:bg-slate-700 disabled:cursor-not-allowed disabled:opacity-40"
					disabled={jobStore.windowOpen}
					onclick={() => (addingOpen = !addingOpen)}
				>
					+ Add requirement
				</button>
			</div>

			{#if !jobStore.judgingStarted}
				<div class="mt-4 flex items-center gap-3 rounded-lg border border-slate-200 bg-slate-50 p-3">
					<p class="flex-1 text-sm text-slate-600">
						Review, edit, or add requirements, then start judging when ready.
					</p>
					<button
						class="shrink-0 cursor-pointer rounded-md bg-slate-900 px-4 py-2 text-sm text-white hover:bg-slate-700 disabled:cursor-not-allowed disabled:opacity-50"
						disabled={startingJudging}
						onclick={startJudging}
					>
						{startingJudging ? 'Starting…' : 'Start judging'}
					</button>
				</div>
				{#if startJudgingError}
					<p class="mt-2 text-sm text-red-600">{startJudgingError}</p>
				{/if}
			{/if}

			<p class="mt-1 text-xs text-slate-400">
				extraction: {jobStore.job.extraction_seconds !== null ? `${jobStore.job.extraction_seconds.toFixed(1)}s` : '—'}
				{#if timeToFirstRow !== null}
					· time to first row: {timeToFirstRow.toFixed(1)}s
				{/if}
				{#if judgingStatusLabel !== null}
					· total judging: {judgingStatusLabel}
				{/if}
			</p>

			{#if jobStore.judgingFinished && !bannerDismissed}
				<div class="mt-2 rounded border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-900">
					<div class="flex items-start justify-between gap-3">
						<p>Judged {jobStore.doneCount} of {jobStore.totalCount}. {jobStore.totalCount - jobStore.doneCount} are left for you to finish manually, or judge the rest automatically below.</p>
						<button class="cursor-pointer text-amber-700 hover:text-amber-900" onclick={() => (bannerDismissed = true)}>✕</button>
					</div>
					<button
						class="mt-2 cursor-pointer rounded bg-amber-700 px-3 py-1 text-sm text-white disabled:cursor-not-allowed disabled:opacity-50"
						disabled={resumingJudging}
						onclick={resumeJudgingClick}
					>
						{resumingJudging ? 'Starting…' : `Judge remaining ${jobStore.totalCount - jobStore.doneCount}`}
					</button>
					{#if resumeJudgingError}
						<p class="mt-1 text-xs text-red-700">{resumeJudgingError}</p>
					{/if}
				</div>
			{/if}

			{#if jobStore.streamError}
				<p class="mt-2 text-xs text-amber-600">{jobStore.streamError} Reconnecting…</p>
			{/if}

			{#if addingOpen}
				<div class="mt-4 flex flex-col gap-2 rounded-lg border border-slate-200 p-3">
					<textarea class="w-full rounded border border-slate-200 px-2 py-1 text-sm" rows="2" placeholder="Requirement text…" bind:value={newText}></textarea>
					<div class="flex items-center gap-2">
						<select class="rounded border border-slate-200 px-2 py-1 text-sm" bind:value={newWeight}>
							<option value="high">High</option>
							<option value="medium">Medium</option>
							<option value="low">Low</option>
						</select>
						<button
							class="cursor-pointer rounded bg-slate-900 px-3 py-1 text-sm text-white disabled:opacity-50"
							disabled={adding || !newText.trim()}
							onclick={addRequirement}
						>
							{adding ? 'Adding…' : 'Add'}
						</button>
						<button class="cursor-pointer text-sm text-slate-500" onclick={() => (addingOpen = false)}>Cancel</button>
					</div>
					{#if addError}
						<p class="text-xs text-red-600">{addError}</p>
					{/if}
				</div>
			{/if}

			<div class="mt-6 space-y-3">
				{#each jobStore.requirementIds as requirementId (requirementId)}
					<RequirementRow {requirementId} />
				{/each}
			</div>

			<div class="mt-6 flex items-center gap-3 border-t border-slate-200 pt-4">
				<button
					class="cursor-pointer rounded-md bg-emerald-700 px-4 py-2 text-sm text-white hover:bg-emerald-800 disabled:cursor-not-allowed disabled:opacity-40"
					disabled={jobStore.windowOpen}
					onclick={clickProceed}
				>
					Proceed
				</button>
				{#if proceedMessage}
					<p class="text-xs text-slate-500">{proceedMessage}</p>
				{/if}
			</div>
			{#if proceedNoMatchesConfirm}
				<div class="mt-2 rounded border border-amber-300 bg-amber-50 p-3 text-sm text-amber-900">
					<p>No units matched, so enrichment and threads will be empty. Continue anyway?</p>
					<div class="mt-2 flex gap-2">
						<button
							class="cursor-pointer rounded bg-amber-700 px-3 py-1 text-sm text-white"
							onclick={() => {
								proceedNoMatchesConfirm = false;
								goto(`/jobs/${jobId}/enrichment`);
							}}
						>
							Continue
						</button>
						<button class="cursor-pointer text-sm text-slate-600" onclick={() => (proceedNoMatchesConfirm = false)}>
							Cancel
						</button>
					</div>
				</div>
			{/if}
		{/if}
	{/if}
</main>

{#if jobStore.job && jobStore.windowOpen}
	<!-- §3 blocking dialog: a dimmed backdrop over the whole page (so
	nothing underneath is clickable) with a small box carrying the
	countdown -- the page itself stays visible through it, just inert. -->
	<div class="fixed inset-0 z-40 flex items-center justify-center bg-black/40">
		<div class="flex flex-col items-center rounded-lg bg-white px-10 py-8 shadow-xl">
			<p class="text-6xl font-bold tabular-nums text-slate-900">
				{minutesLeft}:{secondsLeft.toString().padStart(2, '0')}
			</p>
			<p class="mt-1 text-sm text-slate-500">minutes left in this judging window</p>
			<button
				class="mt-6 cursor-pointer rounded-md border border-slate-300 px-5 py-2.5 text-sm text-slate-700 hover:bg-slate-50 disabled:opacity-50"
				disabled={finishing}
				onclick={finishWindow}
			>
				{finishing ? 'Finishing…' : 'Finish and complete manually'}
			</button>
		</div>
	</div>
{/if}

{#if leaveWarning}
	<div class="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
		<div class="max-w-sm rounded-lg bg-white p-5 shadow-lg">
			<p class="text-sm text-slate-800">
				Judging will stop. Finished results are kept, and you can complete the rest manually.
			</p>
			<div class="mt-4 flex justify-end gap-2">
				<button class="cursor-pointer rounded border border-slate-300 px-3 py-1.5 text-sm" onclick={() => leaveWarning?.resolve(false)}>
					Stay
				</button>
				<button class="cursor-pointer rounded bg-slate-900 px-3 py-1.5 text-sm text-white" onclick={() => leaveWarning?.resolve(true)}>
					Go back
				</button>
			</div>
		</div>
	</div>
{/if}
