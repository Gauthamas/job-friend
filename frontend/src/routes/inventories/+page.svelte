<script lang="ts">
	import { onMount } from 'svelte';
	import { discardInventory, listInventories } from '$lib/api';
	import type { InventoryListItem } from '$lib/types';

	let inventories = $state<InventoryListItem[]>([]);
	let loading = $state(true);
	let error = $state<string | null>(null);
	let discarding = $state<Record<number, boolean>>({});

	onMount(async () => {
		try {
			inventories = await listInventories();
		} catch (e) {
			error = e instanceof Error ? e.message : 'Failed to load inventories.';
		} finally {
			loading = false;
		}
	});

	function formatDate(iso: string): string {
		// dd-mm-yyyy. `iso` is a SQLite "YYYY-MM-DD HH:MM:SS" string, which
		// Date parses fine, but toLocaleDateString()'s format is locale-
		// dependent (mm/dd/yyyy in en-US) — build it explicitly instead.
		const d = new Date(iso.replace(' ', 'T'));
		const dd = String(d.getDate()).padStart(2, '0');
		const mm = String(d.getMonth() + 1).padStart(2, '0');
		return `${dd}-${mm}-${d.getFullYear()}`;
	}

	async function discard(inv: InventoryListItem) {
		discarding[inv.id] = true;
		try {
			await discardInventory(inv.id);
			inventories = inventories.filter((i) => i.id !== inv.id);
		} catch (e) {
			error = e instanceof Error ? e.message : 'Failed to discard inventory.';
		} finally {
			discarding[inv.id] = false;
		}
	}
</script>

<main class="mx-auto max-w-2xl p-8">
	<div class="flex items-center justify-between">
		<h1 class="text-2xl font-semibold text-slate-900">Your inventories</h1>
		<div class="flex items-center gap-3">
			<a href="/flows" class="text-sm text-slate-500 underline">Flows</a>
			<a href="/settings" class="text-sm text-slate-500 underline">Settings</a>
			<a
				href="/inventories/new"
				class="cursor-pointer rounded-md bg-slate-900 px-4 py-2 text-sm text-white hover:bg-slate-700"
			>
				+ New import
			</a>
		</div>
	</div>

	{#if loading}
		<p class="mt-6 text-slate-500">Loading…</p>
	{:else if error}
		<p class="mt-6 text-sm text-red-600">{error}</p>
	{:else if inventories.length === 0}
		<p class="mt-6 text-slate-600">
			No inventories yet. <a class="underline" href="/inventories/new">Import your first resume</a>.
		</p>
	{:else}
		<ul class="mt-6 space-y-2">
			{#each inventories as inv (inv.id)}
				<li class="flex items-stretch gap-2">
					<a
						href="/inventories/{inv.id}/edit"
						class="block flex-1 cursor-pointer rounded-lg border border-slate-200 p-4 hover:border-slate-400"
					>
						<div class="flex items-center justify-between">
							<span class="font-medium text-slate-900">{inv.name}</span>
							<span class="text-xs text-slate-400">{formatDate(inv.created_at)}</span>
						</div>
						<p class="mt-1 text-sm text-slate-500">
							{inv.role_count} role{inv.role_count === 1 ? '' : 's'} · {inv.unit_count} unit{inv.unit_count === 1 ? '' : 's'}
						</p>
					</a>
					{#if inv.role_count === 0}
						<button
							class="shrink-0 cursor-pointer rounded-lg border border-slate-200 px-3 text-sm text-slate-500 hover:border-red-300 hover:text-red-600 disabled:cursor-not-allowed disabled:opacity-50"
							disabled={discarding[inv.id]}
							onclick={() => discard(inv)}
						>
							Discard
						</button>
					{/if}
				</li>
			{/each}
		</ul>
	{/if}
</main>
