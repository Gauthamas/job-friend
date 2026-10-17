<script lang="ts">
	import { searchInventory } from '$lib/api';
	import { jobStore } from '$lib/jobStore.svelte';
	import type { UnitSearchResult } from '$lib/types';

	let { requirementId, disabled = false }: { requirementId: number; disabled?: boolean } = $props();

	let open = $state(false);
	let query = $state('');
	let results = $state<UnitSearchResult[]>([]);
	let loading = $state(false);
	let searchError = $state<string | null>(null);
	let searched = $state(false); // distinguishes "haven't searched yet" from "0 matches"
	let attaching = $state<Record<number, boolean>>({});
	// Per-result, not shared with searchError: a failed attach must not blow
	// away the results list the user is still looking at (that was the bug --
	// the two used to share one `error` var in an if/else-if chain, so an
	// attach failure replaced the whole list with a red error line).
	let attachErrors = $state<Record<number, string>>({});

	let inventoryId = $derived(jobStore.flow?.inventory_id ?? null);

	async function search() {
		if (!inventoryId || !query.trim()) return;
		loading = true;
		searchError = null;
		try {
			results = await searchInventory(inventoryId, query.trim());
			searched = true;
		} catch (e) {
			searchError = e instanceof Error ? e.message : 'Search failed.';
		} finally {
			loading = false;
		}
	}

	async function attach(unitId: number) {
		attaching[unitId] = true;
		delete attachErrors[unitId];
		try {
			await jobStore.addUnit(requirementId, unitId);
			results = results.filter((r) => r.unit_id !== unitId);
		} catch (e) {
			attachErrors[unitId] = e instanceof Error ? e.message : 'Failed to add this unit.';
		} finally {
			attaching[unitId] = false;
		}
	}
</script>

{#if !open}
	<button
		class="cursor-pointer text-xs text-slate-500 underline disabled:cursor-not-allowed disabled:no-underline disabled:opacity-50"
		disabled={!inventoryId || disabled}
		title={inventoryId ? undefined : 'Inventory not resolved yet'}
		onclick={() => (open = true)}
	>
		+ Add unit
	</button>
{:else}
	<div class="rounded border border-slate-200 p-2">
		<div class="flex gap-2">
			<input
				class="flex-1 rounded border border-slate-200 px-2 py-1 text-sm"
				placeholder="Search inventory…"
				bind:value={query}
				onkeydown={(e) => e.key === 'Enter' && search()}
			/>
			<button
				class="cursor-pointer rounded border border-slate-300 px-2 py-1 text-sm hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50"
				disabled={!query.trim()}
				onclick={search}
			>
				Search
			</button>
			<button class="cursor-pointer text-sm text-slate-400 hover:text-slate-600" onclick={() => (open = false)}>
				Close
			</button>
		</div>

		{#if loading}
			<p class="mt-2 text-xs text-slate-500">Searching…</p>
		{:else if searchError}
			<p class="mt-2 text-xs text-red-600">{searchError}</p>
		{:else if results.length > 0}
			<ul class="mt-2 space-y-1">
				{#each results as r (r.unit_id)}
					<li>
						<button
							class="flex w-full items-center justify-between gap-2 rounded border border-slate-100 px-2 py-1.5 text-left hover:border-slate-400 hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50"
							disabled={attaching[r.unit_id]}
							onclick={() => attach(r.unit_id)}
						>
							<span class="min-w-0">
								<p class="truncate text-xs text-slate-700">{r.text}</p>
								<p class="text-[10px] text-slate-400">{r.company} — {r.title}</p>
							</span>
							<span class="shrink-0 text-xs font-medium text-slate-500">
								{attaching[r.unit_id] ? 'Adding…' : '+ Add'}
							</span>
						</button>
						{#if attachErrors[r.unit_id]}
							<p class="mt-0.5 text-xs text-red-600">{attachErrors[r.unit_id]}</p>
						{/if}
					</li>
				{/each}
			</ul>
		{:else if searched}
			<p class="mt-2 text-xs text-slate-500">No matching units found.</p>
		{/if}
	</div>
{/if}
