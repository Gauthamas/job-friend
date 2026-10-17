<script lang="ts">
	import { goto } from '$app/navigation';
	import { page } from '$app/state';
	import {
		choosePrimarySecondary,
		clearSecondary,
		getPrimarySecondary,
		suggestPrimarySecondary,
		swapPrimarySecondary
	} from '$lib/api';
	import type { PrimarySecondaryResponse, RankedThread } from '$lib/types';

	const jobId = $derived(Number(page.params.id));

	let data = $state<PrimarySecondaryResponse | null>(null);
	let loading = $state(true);
	let busy = $state(false);
	let error = $state<string | null>(null);

	async function load() {
		loading = true;
		error = null;
		try {
			data = await getPrimarySecondary(jobId);
		} catch (e) {
			error = e instanceof Error ? e.message : 'Failed to load.';
		} finally {
			loading = false;
		}
	}

	$effect(() => {
		load();
	});

	async function run(action: () => Promise<PrimarySecondaryResponse>) {
		busy = true;
		error = null;
		try {
			data = await action();
		} catch (e) {
			error = e instanceof Error ? e.message : 'Action failed.';
		} finally {
			busy = false;
		}
	}

	function ideaText(thread: RankedThread): string {
		return thread.edited_idea ?? thread.idea;
	}
</script>

<main class="mx-auto max-w-4xl p-8 pb-24">
	<a href={`/jobs/${jobId}/threads`} class="text-sm text-slate-500 underline">← Back to threads</a>

	<h1 class="mt-2 text-2xl font-semibold text-slate-900">Primary and secondary</h1>
	<p class="mt-1 text-sm text-slate-500">
		The two threads carried into the letter. Pick whatever fits best -- nothing here is final.
	</p>

	{#if loading}
		<p class="mt-6 text-slate-500">Loading…</p>
	{:else if error}
		<p class="mt-6 text-sm text-red-600">{error}</p>
	{:else if data}
		<div class="mt-4 flex items-center justify-between">
			<button
				class="cursor-pointer rounded border border-slate-300 px-3 py-1 text-xs text-slate-600 hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-40"
				disabled={busy}
				onclick={() => run(() => suggestPrimarySecondary(jobId))}
			>
				Suggest again
			</button>
			{#if data.primary.thread && data.secondary.thread}
				<button
					class="cursor-pointer rounded border border-slate-300 px-3 py-1 text-xs text-slate-600 hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-40"
					disabled={busy}
					onclick={() => run(() => swapPrimarySecondary(jobId))}
				>
					Swap primary / secondary
				</button>
			{/if}
		</div>

		{#if data.empty_reason}
			<div class="mt-6 rounded border border-slate-200 bg-slate-50 p-4 text-sm text-slate-600">
				<p>{data.empty_reason}</p>
				<p class="mt-1 text-xs text-slate-500">
					You can still write a thread by hand on the Threads screen and use it here.
				</p>
			</div>
		{/if}

		<div class="mt-4 grid gap-4 sm:grid-cols-2">
			{#each [{ label: 'Primary', slot: data.primary }, { label: 'Secondary', slot: data.secondary }] as { label, slot } (label)}
				<div class="rounded-lg border border-slate-200 p-4">
					<div class="flex items-center justify-between">
						<span class="text-xs font-semibold tracking-wide text-slate-400 uppercase">{label}</span>
						{#if slot.choice_stale}
							<span class="rounded border border-amber-300 bg-amber-50 px-2 py-0.5 text-xs text-amber-800">
								re-check -- changed since chosen
							</span>
						{/if}
						{#if label === 'Secondary' && slot.thread}
							<button
								class="cursor-pointer text-xs text-slate-400 hover:text-red-600"
								onclick={() => run(() => clearSecondary(jobId))}
							>
								Clear
							</button>
						{/if}
					</div>

					{#if slot.thread}
						<p class="mt-2 text-base font-medium text-slate-900">{ideaText(slot.thread)}</p>

						<div class="mt-2">
							<p class="text-xs font-medium text-slate-500">Supporting statements</p>
							{#each slot.thread.statements as s (s.statement_id)}
								<p class="mt-0.5 text-xs text-slate-600">{s.text}</p>
							{/each}
						</div>

						<div class="mt-2">
							<p class="text-xs font-medium text-slate-500">Covered requirements</p>
							{#each slot.thread.covered_requirements as r (r.id)}
								<p class="mt-0.5 text-xs text-emerald-700">{r.text} <span class="text-slate-400">({r.weight})</span></p>
							{/each}
							{#if slot.thread.covered_requirements.length === 0}
								<p class="text-xs text-slate-400">None</p>
							{/if}
						</div>

						<div class="mt-2">
							<p class="text-xs font-medium text-slate-500">Uncovered requirements</p>
							{#each slot.thread.uncovered_requirements as r (r.id)}
								<p class="mt-0.5 text-xs text-slate-500">{r.text} <span class="text-slate-400">({r.weight})</span></p>
							{/each}
						</div>

						<div class="mt-2">
							<p class="text-xs font-medium text-slate-500">Units</p>
							{#each slot.thread.units as tu (tu.unit.id)}
								<p class="mt-0.5 text-xs text-slate-600">
									{tu.unit.text}
									{#if tu.quote}— "{tu.quote}" ({tu.model_verdict}){/if}
								</p>
							{/each}
						</div>
					{:else}
						<p class="mt-2 text-sm text-slate-400">Not chosen yet.</p>
					{/if}
				</div>
			{/each}
		</div>

		{#if data.other_candidates.length > 0}
			<div class="mt-6">
				<p class="text-sm font-medium text-slate-700">Other threads</p>
				<div class="mt-2 grid gap-2">
					{#each data.other_candidates as thread (thread.id)}
						<div class="flex items-center justify-between rounded border border-slate-200 p-2 text-sm">
							<span>{ideaText(thread)}</span>
							<div class="flex gap-2">
								<button
									class="cursor-pointer rounded border border-slate-300 px-2 py-0.5 text-xs text-slate-600 hover:bg-slate-50"
									onclick={() => run(() => choosePrimarySecondary(jobId, thread.id, 'primary'))}
								>
									Use as primary
								</button>
								<button
									class="cursor-pointer rounded border border-slate-300 px-2 py-0.5 text-xs text-slate-600 hover:bg-slate-50"
									onclick={() => run(() => choosePrimarySecondary(jobId, thread.id, 'secondary'))}
								>
									Use as secondary
								</button>
							</div>
						</div>
					{/each}
				</div>
			</div>
		{/if}

		<div class="mt-6 flex justify-end">
			<button
				class="cursor-pointer rounded-md bg-slate-900 px-4 py-2 text-sm text-white disabled:cursor-not-allowed disabled:opacity-40"
				disabled={!data.primary.thread}
				onclick={() => goto(`/jobs/${jobId}/write`)}
			>
				Continue
			</button>
			{#if !data.primary.thread}
				<p class="ml-2 self-center text-xs text-slate-400">Choose a primary thread first.</p>
			{/if}
		</div>
	{/if}
</main>
