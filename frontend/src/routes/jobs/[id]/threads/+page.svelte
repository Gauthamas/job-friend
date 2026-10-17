<script lang="ts">
	import { onDestroy } from 'svelte';
	import { goto } from '$app/navigation';
	import { page } from '$app/state';
	import {
		canRunThreads,
		deleteThread,
		getLatestThreads,
		getTimingHistory,
		mergeThreads,
		moveStatementToThread,
		patchThreadIdea,
		promoteThread,
		removeStatementFromThread,
		runThreads
	} from '$lib/api';
	import type { RunThreadsBlockedReason, Thread, ThreadRun, TimingHistory } from '$lib/types';

	const jobId = $derived(Number(page.params.id));

	let run = $state<ThreadRun | null>(null);
	let blocked = $state<RunThreadsBlockedReason | null>(null);
	let loading = $state(true);
	let running = $state(false);
	let error = $state<string | null>(null);
	let editingIdea = $state<Record<number, string>>({});
	let mergeTarget = $state<Record<number, string>>({});
	let belowMinOpen = $state(false);

	// Same live-elapsed-timer pattern as the JD extraction screen.
	let elapsedSeconds = $state(0);
	let elapsedTimer: ReturnType<typeof setInterval> | undefined;
	let threadsHistory = $state<TimingHistory | null>(null);

	function startElapsedTimer() {
		elapsedSeconds = 0;
		const startedAt = Date.now();
		elapsedTimer = setInterval(() => (elapsedSeconds = Math.floor((Date.now() - startedAt) / 1000)), 1000);
	}

	onDestroy(() => clearInterval(elapsedTimer));

	const mainThreads = $derived(run?.threads.filter((t) => !t.below_min) ?? []);
	const belowMinThreads = $derived(run?.threads.filter((t) => t.below_min) ?? []);

	async function load() {
		loading = true;
		error = null;
		try {
			blocked = await canRunThreads(jobId);
			try {
				run = await getLatestThreads(jobId);
			} catch {
				run = null; // no run yet -- not an error
			}
		} catch (e) {
			error = e instanceof Error ? e.message : 'Failed to load.';
		} finally {
			loading = false;
		}
		try {
			threadsHistory = await getTimingHistory('threads');
		} catch {
			threadsHistory = null;
		}
	}

	$effect(() => {
		load();
	});

	async function handleRun() {
		running = true;
		error = null;
		startElapsedTimer();
		try {
			run = await runThreads(jobId);
			blocked = await canRunThreads(jobId);
		} catch (e) {
			error = e instanceof Error ? e.message : 'Failed to run.';
		} finally {
			running = false;
			clearInterval(elapsedTimer);
		}
	}

	function ideaText(thread: Thread): string {
		return thread.edited_idea ?? thread.idea;
	}

	async function saveIdea(thread: Thread) {
		const text = editingIdea[thread.id];
		if (text === undefined || text === ideaText(thread)) return;
		const updated = await patchThreadIdea(thread.id, text);
		if (run) run.threads = run.threads.map((t) => (t.id === updated.id ? updated : t));
	}

	async function handleDelete(thread: Thread) {
		await deleteThread(thread.id);
		if (run) run.threads = run.threads.filter((t) => t.id !== thread.id);
	}

	async function handleRemoveStatement(thread: Thread, statementId: number) {
		const updated = await removeStatementFromThread(thread.id, statementId);
		if (run) run.threads = run.threads.map((t) => (t.id === updated.id ? updated : t));
	}

	async function handleMerge(thread: Thread) {
		const otherId = Number(mergeTarget[thread.id]);
		if (!otherId) return;
		const updated = await mergeThreads(thread.id, otherId);
		if (run) run.threads = run.threads.filter((t) => t.id !== otherId).map((t) => (t.id === updated.id ? updated : t));
	}

	async function handlePromote(thread: Thread) {
		const updated = await promoteThread(thread.id);
		if (run) run.threads = run.threads.map((t) => (t.id === updated.id ? updated : t));
	}

	async function handleMoveStatement(fromThread: Thread, statementId: number, toThreadId: number) {
		const updatedTarget = await moveStatementToThread(toThreadId, statementId);
		if (!run) return;
		run.threads = run.threads.map((t) => {
			if (t.id === toThreadId) return updatedTarget;
			if (t.id === fromThread.id) return { ...t, statements: t.statements.filter((s) => s.statement_id !== statementId) };
			return t;
		});
	}
</script>

<main class="mx-auto max-w-3xl p-8 pb-24">
	<a href={`/jobs/${jobId}/statements`} class="text-sm text-slate-500 underline">← Back to statements</a>

	<h1 class="mt-2 text-2xl font-semibold text-slate-900">Threads</h1>
	<p class="mt-1 text-sm text-slate-500">
		Recurring ideas the model found across your statements. Edit, move, merge, or delete anything -- nothing here
		is final prose.
	</p>

	{#if loading}
		<p class="mt-6 text-slate-500">Loading…</p>
	{:else}
		<div class="mt-4 flex items-center justify-between">
			<button
				class="cursor-pointer rounded-md bg-slate-900 px-4 py-2 text-sm text-white disabled:cursor-not-allowed disabled:opacity-40"
				disabled={blocked?.blocked || running}
				onclick={handleRun}
			>
				{running ? 'Running…' : run ? 'Re-run' : 'Run'}
			</button>
			{#if blocked?.blocked}
				<p class="text-xs text-amber-700">{blocked.reason}</p>
			{/if}
		</div>

		{#if running}
			<p class="mt-2 text-2xl font-semibold text-slate-700">
				{elapsedSeconds}s elapsed
			</p>
			{#if threadsHistory?.avg_seconds_total}
				<p class="text-xs text-slate-400">typically ~{Math.round(threadsHistory.avg_seconds_total)}s</p>
			{/if}
		{:else if run && !run.error && run.seconds_total !== null}
			<p class="mt-1 text-xs text-slate-400">Threads found in {run.seconds_total.toFixed(1)}s</p>
		{/if}

		{#if error}
			<p class="mt-2 text-sm text-red-600">{error}</p>
		{/if}

		{#if run?.error}
			<p class="mt-4 rounded border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
				This run failed: {run.error}
			</p>
		{/if}

		{#if run && mainThreads.length > 0}
			<div class="mt-4 grid gap-4">
				{#each mainThreads as thread (thread.id)}
					<div class="rounded-lg border border-slate-200 p-4">
						<div class="flex items-start justify-between gap-2">
							<input
								class="flex-1 rounded border border-slate-200 px-2 py-1 text-sm font-medium"
								value={ideaText(thread)}
								oninput={(e) => (editingIdea[thread.id] = (e.target as HTMLInputElement).value)}
								onblur={() => saveIdea(thread)}
							/>
							<div class="flex shrink-0 items-center gap-2">
								{#if thread.stale}
									<span class="rounded border border-amber-300 bg-amber-50 px-2 py-0.5 text-xs text-amber-800">
										stale
									</span>
								{/if}
								<button
									class="cursor-pointer text-xs text-red-500 hover:text-red-700"
									onclick={() => handleDelete(thread)}
								>
									Delete
								</button>
							</div>
						</div>

						<div class="mt-3 grid gap-2">
							{#each thread.statements as statement (statement.statement_id)}
								<div class="rounded border border-slate-100 bg-slate-50 p-2 text-sm">
									<p class="text-slate-700">{statement.text}</p>
									<div class="mt-1">
										<p class="text-xs text-slate-500">{statement.unit_a.text}</p>
										<p class="text-xs text-slate-500">{statement.unit_b.text}</p>
									</div>
									<div class="mt-1 flex items-center gap-2">
										<button
											class="cursor-pointer text-xs text-slate-400 hover:text-red-600"
											onclick={() => handleRemoveStatement(thread, statement.statement_id)}
										>
											Remove
										</button>
										{#if mainThreads.length > 1}
											<select
												class="rounded border border-slate-200 px-1 py-0.5 text-xs"
												onchange={(e) => {
													const value = Number((e.target as HTMLSelectElement).value);
													if (value) handleMoveStatement(thread, statement.statement_id, value);
												}}
											>
												<option value="">Move to…</option>
												{#each mainThreads.filter((t) => t.id !== thread.id) as other (other.id)}
													<option value={other.id}>{ideaText(other)}</option>
												{/each}
											</select>
										{/if}
									</div>
								</div>
							{/each}
						</div>

						<div class="mt-3">
							<p class="text-xs font-medium text-slate-500">Units and their verified quotes</p>
							<div class="mt-1 grid gap-1">
								{#each thread.units as tu (tu.unit.id)}
									<div class="text-xs text-slate-600">
										<span class="font-medium">{tu.unit.text}</span>
										{#if tu.quote}
											— "{tu.quote}"
										{:else}
											<span class="text-slate-400">(no verified quote)</span>
										{/if}
									</div>
								{/each}
							</div>
						</div>

						{#if mainThreads.length > 1}
							<div class="mt-3 flex items-center gap-2">
								<select
									class="rounded border border-slate-200 px-1 py-0.5 text-xs"
									bind:value={mergeTarget[thread.id]}
								>
									<option value="">Merge with…</option>
									{#each mainThreads.filter((t) => t.id !== thread.id) as other (other.id)}
										<option value={other.id}>{ideaText(other)}</option>
									{/each}
								</select>
								<button
									class="cursor-pointer rounded border border-slate-300 px-2 py-0.5 text-xs text-slate-600 hover:bg-slate-50"
									onclick={() => handleMerge(thread)}
								>
									Merge into this thread
								</button>
							</div>
						{/if}
					</div>
				{/each}
			</div>
		{:else if run}
			<p class="mt-6 text-sm text-slate-500">This run found no threads.</p>
		{/if}

		{#if belowMinThreads.length > 0}
			<div class="mt-6 rounded-lg border border-slate-200">
				<button
					class="w-full cursor-pointer px-4 py-2 text-left text-sm font-medium text-slate-600"
					onclick={() => (belowMinOpen = !belowMinOpen)}
				>
					{belowMinOpen ? '▾' : '▸'} Below minimum support ({belowMinThreads.length})
				</button>
				{#if belowMinOpen}
					<div class="grid gap-3 border-t border-slate-100 p-4">
						{#each belowMinThreads as thread (thread.id)}
							<div class="rounded border border-slate-100 bg-slate-50 p-3">
								<div class="flex items-start justify-between gap-2">
									<p class="text-sm font-medium text-slate-700">{ideaText(thread)}</p>
									<button
										class="shrink-0 cursor-pointer rounded border border-slate-300 bg-white px-2 py-0.5 text-xs text-slate-600 hover:bg-slate-50"
										onclick={() => handlePromote(thread)}
									>
										Use anyway
									</button>
								</div>
								<p class="mt-1 text-xs text-slate-500">{thread.statements.length} statement(s)</p>
								<div class="mt-2 grid gap-1">
									{#each thread.statements as statement (statement.statement_id)}
										<p class="text-xs text-slate-600">{statement.text}</p>
									{/each}
								</div>
							</div>
						{/each}
					</div>
				{/if}
			</div>
		{/if}

		<div class="mt-6 flex justify-end">
			<button
				class="cursor-pointer rounded-md bg-slate-900 px-4 py-2 text-sm text-white disabled:cursor-not-allowed disabled:opacity-40"
				disabled={!run || mainThreads.length === 0}
				onclick={() => goto(`/jobs/${jobId}/primary-secondary`)}
			>
				Continue
			</button>
		</div>
	{/if}
</main>
