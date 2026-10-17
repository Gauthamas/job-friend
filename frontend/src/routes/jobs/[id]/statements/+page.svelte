<script lang="ts">
	import { goto } from '$app/navigation';
	import { page } from '$app/state';
	import { autofillPairs, confirmAllStatements, getPairs, startFreshPairs } from '$lib/api';
	import PairCard from '$lib/components/PairCard.svelte';
	import type { PairsListResponse, Statement } from '$lib/types';

	const jobId = $derived(Number(page.params.id));

	let data = $state<PairsListResponse | null>(null);
	let loading = $state(true);
	let error = $state<string | null>(null);
	let index = $state(0);
	let busy = $state(false);

	async function load() {
		loading = true;
		error = null;
		try {
			data = await getPairs(jobId);
		} catch (e) {
			error = e instanceof Error ? e.message : 'Failed to load.';
		} finally {
			loading = false;
		}
	}

	$effect(() => {
		load();
	});

	function handleSaved(statement: Statement) {
		if (!data) return;
		const pair = data.pairs.find((p) => p.statement.id === statement.id);
		if (!pair) return;
		pair.statement = statement;
		data.all_ready = data.pairs.every(
			(p) => p.statement.status !== 'unanswered' && (p.statement.confirmed || p.statement.autofilled_from_job_id === null)
		);
	}

	async function runAutofill() {
		busy = true;
		try {
			await autofillPairs(jobId);
			await load();
		} finally {
			busy = false;
		}
	}

	async function runFresh() {
		busy = true;
		try {
			await startFreshPairs(jobId);
			await load();
		} finally {
			busy = false;
		}
	}

	async function runConfirmAll() {
		busy = true;
		try {
			await confirmAllStatements(jobId);
			await load();
		} finally {
			busy = false;
		}
	}

	const answeredCount = $derived(
		data ? data.pairs.filter((p) => p.statement.status !== 'unanswered').length : 0
	);
	const unansweredCount = $derived(
		data ? data.pairs.filter((p) => p.statement.status === 'unanswered').length : 0
	);
	const unconfirmedAutofillCount = $derived(
		data ? data.pairs.filter((p) => p.statement.autofilled_from_job_id !== null && !p.statement.confirmed).length : 0
	);
	const hasUnconfirmedAutofill = $derived(unconfirmedAutofillCount > 0);
	const currentPair = $derived(data && data.pairs.length > 0 ? data.pairs[index] : null);
</script>

<main class="mx-auto max-w-3xl p-8 pb-24">
	<a href={`/jobs/${jobId}/enrichment`} class="text-sm text-slate-500 underline">← Back to enrichment</a>

	<h1 class="mt-2 text-2xl font-semibold text-slate-900">Statements</h1>
	<p class="mt-1 text-sm text-slate-500">
		For each pair, say what the two have in common, or mark None. Nothing is model-generated here.
	</p>

	{#if loading}
		<p class="mt-6 text-slate-500">Loading…</p>
	{:else if error}
		<p class="mt-6 text-sm text-red-600">{error}</p>
	{:else if data}
		<div class="mt-4 flex flex-wrap items-center justify-between gap-2">
			<p class="text-sm text-slate-600">{answeredCount} of {data.pairs.length}</p>
			<div class="flex gap-2">
				<button
					class="cursor-pointer rounded border border-slate-300 px-3 py-1 text-xs text-slate-600 hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-40"
					disabled={busy}
					onclick={runAutofill}
				>
					Autofill from earlier jobs
				</button>
				<button
					class="cursor-pointer rounded border border-slate-300 px-3 py-1 text-xs text-slate-600 hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-40"
					disabled={busy}
					onclick={runFresh}
				>
					Start fresh
				</button>
				{#if hasUnconfirmedAutofill}
					<button
						class="cursor-pointer rounded border border-amber-300 bg-amber-50 px-3 py-1 text-xs text-amber-800 hover:bg-amber-100 disabled:cursor-not-allowed disabled:opacity-40"
						disabled={busy}
						onclick={runConfirmAll}
					>
						Confirm all
					</button>
				{/if}
			</div>
		</div>

		{#if data.pairs.length === 0}
			<p class="mt-6 text-sm text-slate-500">No pairs were built -- there may be fewer than two matched units.</p>
		{:else if currentPair}
			<div class="mt-4">
				<PairCard pair={currentPair} onSaved={handleSaved} />
			</div>

			<div class="mt-3 flex items-center justify-between">
				<button
					class="cursor-pointer text-sm text-slate-500 underline disabled:cursor-not-allowed disabled:opacity-40"
					disabled={index === 0}
					onclick={() => (index -= 1)}
				>
					← Previous
				</button>
				<span class="text-xs text-slate-400">Pair {index + 1} of {data.pairs.length}</span>
				<button
					class="cursor-pointer text-sm text-slate-500 underline disabled:cursor-not-allowed disabled:opacity-40"
					disabled={index === data.pairs.length - 1}
					onclick={() => (index += 1)}
				>
					Next →
				</button>
			</div>
		{/if}

		<div class="mt-6 flex flex-col items-end gap-1">
			{#if !data.all_ready}
				<p class="text-xs text-amber-700">
					{#if unansweredCount > 0}
						{unansweredCount} pair{unansweredCount === 1 ? '' : 's'} still unanswered.
					{:else if hasUnconfirmedAutofill}
						{unconfirmedAutofillCount} autofilled answer{unconfirmedAutofillCount === 1 ? '' : 's'} still
						need{unconfirmedAutofillCount === 1 ? 's' : ''} confirming -- click "Confirm all" above.
					{/if}
				</p>
			{/if}
			<button
				class="cursor-pointer rounded-md bg-slate-900 px-4 py-2 text-sm text-white disabled:cursor-not-allowed disabled:opacity-40"
				disabled={!data.all_ready}
				onclick={() => goto(`/jobs/${jobId}/threads`)}
			>
				Continue
			</button>
		</div>
	{/if}
</main>
