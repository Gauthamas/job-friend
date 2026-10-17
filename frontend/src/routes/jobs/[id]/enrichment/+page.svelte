<script lang="ts">
	import { goto } from '$app/navigation';
	import { page } from '$app/state';
	import { buildPairs, getEnrichment } from '$lib/api';
	import EnrichmentUnitCard from '$lib/components/EnrichmentUnitCard.svelte';
	import type { EnrichmentResponse, SavedUnit } from '$lib/types';

	const jobId = $derived(Number(page.params.id));

	let data = $state<EnrichmentResponse | null>(null);
	let loading = $state(true);
	let error = $state<string | null>(null);
	let continuing = $state(false);

	$effect(() => {
		loading = true;
		error = null;
		getEnrichment(jobId)
			.then((resp) => (data = resp))
			.catch((e) => (error = e instanceof Error ? e.message : 'Failed to load.'))
			.finally(() => (loading = false));
	});

	function handleSaved(updated: SavedUnit) {
		if (!data) return;
		const entry = data.units.find((u) => u.unit.id === updated.id);
		if (!entry) return;
		entry.unit = updated;
		entry.complete =
			(!!updated.context || updated.context_skipped) &&
			(!!updated.contribution || updated.contribution_skipped) &&
			(!!updated.outcome || updated.outcome_skipped);
		data.enriched_count = data.units.filter((u) => u.complete).length;
	}

	const allComplete = $derived(data !== null && data.units.length === data.enriched_count);

	async function handleContinue() {
		continuing = true;
		error = null;
		try {
			await buildPairs(jobId);
			goto(`/jobs/${jobId}/statements`);
		} catch (e) {
			error = e instanceof Error ? e.message : 'Failed to build pairs.';
			continuing = false;
		}
	}
</script>

<main class="mx-auto max-w-3xl p-8 pb-24">
	<a href={`/jobs/${jobId}`} class="text-sm text-slate-500 underline">← Back to requirements</a>

	<h1 class="mt-2 text-2xl font-semibold text-slate-900">Enrichment</h1>
	<p class="mt-1 text-sm text-slate-500">
		For each unit that matched a requirement, answer what you can. Nothing is model-generated here.
	</p>

	{#if loading}
		<p class="mt-6 text-slate-500">Loading…</p>
	{:else if error}
		<p class="mt-6 text-sm text-red-600">{error}</p>
	{:else if data}
		<div class="mt-4 flex items-center justify-between">
			<p class="text-sm text-slate-600">{data.enriched_count} of {data.total_count} units enriched</p>
			<button
				class="cursor-pointer rounded-md bg-slate-900 px-4 py-2 text-sm text-white disabled:cursor-not-allowed disabled:opacity-40"
				disabled={!allComplete || continuing}
				onclick={handleContinue}
			>
				{continuing ? 'Building pairs…' : 'Continue'}
			</button>
		</div>

		{#if data.units.length === 0}
			<p class="mt-6 text-sm text-slate-500">No units matched a requirement, so there is nothing to enrich.</p>
		{:else}
			<div class="mt-4 grid gap-3">
				{#each data.units as entry (entry.unit.id)}
					<EnrichmentUnitCard {entry} questions={data.questions} onSaved={handleSaved} />
				{/each}
			</div>
		{/if}
	{/if}
</main>
