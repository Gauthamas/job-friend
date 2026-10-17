<script lang="ts">
	import { onMount } from 'svelte';
	import { goto } from '$app/navigation';
	import {
		createFlow,
		discardJob,
		getJobProgress,
		listFlowJobs,
		listFlows,
		listInventories,
		restoreJob
	} from '$lib/api';
	import type { Flow, InventoryListItem, JobProgressRoute } from '$lib/types';

	const PROGRESS_PATH: Record<JobProgressRoute, (jobId: number) => string> = {
		job: (id) => `/jobs/${id}`,
		statements: (id) => `/jobs/${id}/statements`,
		threads: (id) => `/jobs/${id}/threads`,
		primary_secondary: (id) => `/jobs/${id}/primary-secondary`,
		write: (id) => `/jobs/${id}/write`
	};

	let flows = $state<Flow[]>([]);
	let inventories = $state<InventoryListItem[]>([]);
	let loading = $state(true);
	let loadError = $state<string | null>(null);

	let newName = $state('');
	let newInventoryId = $state<number | null>(null);
	let creating = $state(false);
	let createError = $state<string | null>(null);
	let openingFlowId = $state<number | null>(null);
	let openError = $state<string | null>(null);
	let showDiscarded = $state(false);
	let discardingFlowId = $state<number | null>(null);
	let discardError = $state<string | null>(null);

	async function loadFlows() {
		flows = await listFlows(showDiscarded);
	}

	onMount(async () => {
		try {
			[, inventories] = await Promise.all([loadFlows(), listInventories()]);
			newInventoryId = inventories[0]?.id ?? null;
		} catch (e) {
			loadError = e instanceof Error ? e.message : 'Failed to load flows.';
		} finally {
			loading = false;
		}
	});

	async function toggleShowDiscarded() {
		showDiscarded = !showDiscarded;
		try {
			await loadFlows();
		} catch (e) {
			loadError = e instanceof Error ? e.message : 'Failed to load flows.';
		}
	}

	async function discardOrRestoreFlow(flow: Flow) {
		if (flow.latest_job_id === null) return;
		discardError = null;
		if (flow.latest_job_discarded_at) {
			discardingFlowId = flow.id;
			try {
				await restoreJob(flow.latest_job_id);
				await loadFlows();
			} catch (e) {
				discardError = e instanceof Error ? e.message : 'Failed to restore.';
			} finally {
				discardingFlowId = null;
			}
			return;
		}
		if (!confirm('This will hide this job and its requirements, judgments, threads and letter from the list. You can restore it later.')) {
			return;
		}
		discardingFlowId = flow.id;
		try {
			await discardJob(flow.latest_job_id);
			await loadFlows();
		} catch (e) {
			discardError = e instanceof Error ? e.message : 'Failed to discard.';
		} finally {
			discardingFlowId = null;
		}
	}

	function inventoryName(inventoryId: number): string {
		return inventories.find((i) => i.id === inventoryId)?.name ?? `Inventory ${inventoryId}`;
	}

	function formatDate(iso: string): string {
		const d = new Date(iso.replace(' ', 'T'));
		const dd = String(d.getDate()).padStart(2, '0');
		const mm = String(d.getMonth() + 1).padStart(2, '0');
		return `${dd}-${mm}-${d.getFullYear()}`;
	}

	async function openFlow(flow: Flow) {
		openingFlowId = flow.id;
		openError = null;
		try {
			const jobs = await listFlowJobs(flow.id);
			if (jobs.length === 0) {
				goto(`/flows/${flow.id}/jobs/new`);
				return;
			}
			// Newest first -- the most recently created job is the one most
			// likely to be "where you left off" for this flow.
			const latest = jobs[0];
			const progress = await getJobProgress(latest.id);
			goto(PROGRESS_PATH[progress.route](latest.id));
		} catch (e) {
			openError = e instanceof Error ? e.message : 'Failed to open this flow.';
		} finally {
			openingFlowId = null;
		}
	}

	async function submit() {
		if (!newName.trim() || newInventoryId === null) return;
		creating = true;
		createError = null;
		try {
			const flow = await createFlow(newName.trim(), newInventoryId);
			goto(`/flows/${flow.id}/jobs/new`);
		} catch (e) {
			createError = e instanceof Error ? e.message : 'Failed to create flow.';
			creating = false;
		}
	}
</script>

<main class="mx-auto max-w-2xl p-8">
	<div class="flex items-center justify-between">
		<h1 class="text-2xl font-semibold text-slate-900">Flows</h1>
		<a href="/inventories" class="text-sm text-slate-500 underline">Inventories</a>
	</div>

	{#if loading}
		<p class="mt-6 text-slate-500">Loading…</p>
	{:else}
		{#if loadError}
			<p class="mt-6 text-sm text-red-600">{loadError}</p>
		{/if}

		<div class="mt-6 rounded-lg border border-slate-200 p-4">
			<h2 class="text-sm font-medium text-slate-700">New flow</h2>
			{#if inventories.length === 0}
				<p class="mt-2 text-sm text-slate-500">
					No inventories yet. <a class="underline" href="/inventories/new">Import one first</a>.
				</p>
			{:else}
				<div class="mt-3 flex flex-col gap-2">
					<input
						class="rounded border border-slate-200 px-3 py-2 text-sm disabled:bg-slate-50"
						placeholder="Flow name"
						bind:value={newName}
						disabled={creating}
					/>
					<select
						class="rounded border border-slate-200 px-3 py-2 text-sm disabled:bg-slate-50"
						bind:value={newInventoryId}
						disabled={creating}
					>
						{#each inventories as inv (inv.id)}
							<option value={inv.id}>{inv.name}</option>
						{/each}
					</select>
					{#if createError}
						<p class="text-sm text-red-600">{createError}</p>
					{/if}
					<button
						class="cursor-pointer rounded-md bg-slate-900 px-4 py-2 text-sm text-white hover:bg-slate-700 disabled:cursor-not-allowed disabled:opacity-50"
						disabled={creating || !newName.trim() || newInventoryId === null}
						onclick={submit}
					>
						{creating ? 'Creating…' : 'Create flow'}
					</button>
				</div>
			{/if}
		</div>

		{#if openError}
			<p class="mt-4 text-sm text-red-600">{openError}</p>
		{/if}
		{#if discardError}
			<p class="mt-4 text-sm text-red-600">{discardError}</p>
		{/if}

		<label class="mt-4 flex items-center gap-2 text-sm text-slate-500">
			<input type="checkbox" checked={showDiscarded} onchange={toggleShowDiscarded} />
			Show discarded
		</label>

		{#if flows.length === 0}
			<p class="mt-6 text-slate-600">No flows yet — create one above.</p>
		{:else}
			<ul class="mt-6 space-y-2">
				{#each flows as flow (flow.id)}
					<li class="rounded-lg border border-slate-200 p-4 {flow.latest_job_discarded_at ? 'opacity-50' : ''}">
						<button
							type="button"
							class="block w-full cursor-pointer text-left disabled:cursor-wait disabled:opacity-60"
							disabled={openingFlowId === flow.id}
							onclick={() => openFlow(flow)}
						>
							<div class="flex items-center justify-between">
								<span class="font-medium text-slate-900">{flow.name}</span>
								<span class="text-xs text-slate-400">
									{openingFlowId === flow.id ? 'Opening…' : formatDate(flow.created_at)}
								</span>
							</div>
							<p class="mt-1 text-sm text-slate-500">{inventoryName(flow.inventory_id)}</p>
						</button>
						{#if flow.latest_job_id !== null}
							<div class="mt-2 flex items-center gap-2">
								{#if flow.latest_job_discarded_at}
									<span class="text-xs text-slate-400">discarded</span>
								{/if}
								<button
									type="button"
									class="cursor-pointer text-xs text-slate-500 hover:underline disabled:cursor-not-allowed disabled:opacity-50"
									disabled={discardingFlowId === flow.id}
									onclick={() => discardOrRestoreFlow(flow)}
								>
									{flow.latest_job_discarded_at ? 'Restore' : 'Discard'}
								</button>
							</div>
						{/if}
					</li>
				{/each}
			</ul>
		{/if}
	{/if}
</main>
