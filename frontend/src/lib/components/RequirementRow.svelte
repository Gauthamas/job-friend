<script lang="ts">
	import AddUnitSearch from './AddUnitSearch.svelte';
	import JudgmentUnit from './JudgmentUnit.svelte';
	import { jobStore } from '$lib/jobStore.svelte';
	import type { RequirementVerdict, Weight } from '$lib/types';

	let { requirementId }: { requirementId: number } = $props();

	let entry = $derived(jobStore.entries[requirementId]);
	// §3's edit block mirrors the server-side 409s: while the window is
	// open the blocking dialog covers the page, but these controls are
	// disabled too so nothing underneath it is clickable in a way that
	// would just bounce off a 409.
	let locked = $derived(jobStore.windowOpen);

	let editing = $state(false);
	let editText = $state('');
	let editWeight = $state<Weight>('medium');
	let saving = $state(false);
	let saveError = $state<string | null>(null);
	let deleting = $state(false);
	let debugOpen = $state(false);
	let markingNoMatch = $state(false);

	function startEdit() {
		editText = entry.requirement.text;
		editWeight = entry.requirement.weight;
		saveError = null;
		editing = true;
	}

	async function save() {
		saving = true;
		saveError = null;
		try {
			await jobStore.editRequirement(requirementId, { text: editText, weight: editWeight });
			editing = false;
		} catch (e) {
			saveError = e instanceof Error ? e.message : 'Failed to save.';
		} finally {
			saving = false;
		}
	}

	async function remove() {
		deleting = true;
		try {
			await jobStore.deleteRequirement(requirementId);
		} catch (e) {
			deleting = false;
			saveError = e instanceof Error ? e.message : 'Failed to delete.';
		}
	}

	async function markNoMatch() {
		markingNoMatch = true;
		saveError = null;
		try {
			await jobStore.markNoMatch(requirementId);
		} catch (e) {
			saveError = e instanceof Error ? e.message : 'Failed to mark as no match.';
		} finally {
			markingNoMatch = false;
		}
	}

	const WEIGHT_LABEL: Record<Weight, string> = { high: 'High', medium: 'Medium', low: 'Low' };

	const VERDICT_STYLE: Record<RequirementVerdict, string> = {
		match: 'bg-emerald-100 text-emerald-800 border-emerald-300',
		weak: 'bg-amber-100 text-amber-800 border-amber-300',
		gap: 'bg-slate-100 text-slate-500 border-slate-300'
	};
</script>

{#if entry}
	<div class="rounded-lg border border-slate-200 p-4">
		{#if editing}
			<div class="flex flex-col gap-2">
				<textarea class="w-full rounded border border-slate-200 px-2 py-1 text-sm" rows="2" bind:value={editText}></textarea>
				<div class="flex items-center gap-2">
					<select class="rounded border border-slate-200 px-2 py-1 text-sm" bind:value={editWeight}>
						<option value="high">High</option>
						<option value="medium">Medium</option>
						<option value="low">Low</option>
					</select>
					<button
						class="cursor-pointer rounded bg-slate-900 px-3 py-1 text-sm text-white disabled:opacity-50"
						disabled={saving}
						onclick={save}
					>
						{saving ? 'Saving…' : 'Save'}
					</button>
					<button class="cursor-pointer text-sm text-slate-500" onclick={() => (editing = false)}>Cancel</button>
				</div>
			</div>
		{:else}
			<div class="flex items-start justify-between gap-3">
				<p class="text-sm text-slate-900">{entry.requirement.text}</p>
				<div class="flex shrink-0 items-center gap-2">
					<span class="rounded border border-slate-200 px-2 py-0.5 text-xs text-slate-500">
						{WEIGHT_LABEL[entry.requirement.weight]}
					</span>
					{#if entry.requirement.status === 'pending'}
						<span class="rounded border border-slate-300 bg-slate-100 px-2 py-0.5 text-xs font-medium text-slate-500">
							pending
						</span>
					{:else}
						<span class="rounded border px-2 py-0.5 text-xs font-medium {VERDICT_STYLE[entry.verdict]}">
							{entry.verdict}
						</span>
					{/if}
					{#if entry.requirement.reason === 'marked by user'}
						<span class="rounded border border-slate-300 bg-slate-100 px-2 py-0.5 text-xs text-slate-500">
							marked by you
						</span>
					{/if}
					<button
						class="cursor-pointer text-xs text-slate-400 hover:text-slate-700 disabled:cursor-not-allowed disabled:opacity-40"
						disabled={locked}
						onclick={startEdit}
					>
						Edit
					</button>
					<button
						class="cursor-pointer text-xs text-slate-400 hover:text-slate-700 disabled:cursor-not-allowed disabled:opacity-40"
						disabled={locked || markingNoMatch}
						onclick={markNoMatch}
					>
						No match
					</button>
					<button
						class="cursor-pointer text-xs text-slate-400 hover:text-red-600 disabled:cursor-not-allowed disabled:opacity-40"
						disabled={locked || deleting}
						onclick={remove}
					>
						Delete
					</button>
				</div>
			</div>
		{/if}

		{#if saveError}
			<p class="mt-1 text-xs text-red-600">{saveError}</p>
		{/if}

		{#if entry.requirement.status === 'pending'}
			<div class="mt-2 min-w-0">
				<p class="text-xs text-slate-400">Pending — set a verdict below, or leave it as a gap</p>
				{#if entry.requirement.last_error}
					<p class="mt-0.5 text-xs text-red-600">{entry.requirement.last_error}</p>
				{/if}
			</div>
		{:else if entry.requirement.reason && entry.requirement.reason !== 'marked by user'}
			<p class="mt-2 text-xs text-slate-500">{entry.requirement.reason}</p>
		{/if}

		{#if entry.judgments.length > 0}
			<div class="mt-3 space-y-1.5">
				{#each entry.judgments as judgment (judgment.id)}
					<JudgmentUnit {requirementId} {judgment} {locked} />
				{/each}
			</div>
		{/if}

		<div class="mt-3 flex items-center justify-between">
			<AddUnitSearch {requirementId} disabled={locked} />
			{#if entry.judgments.length > 0 || entry.requirement.embed_seconds !== null}
				<button class="cursor-pointer text-xs text-slate-400 underline" onclick={() => (debugOpen = !debugOpen)}>
					{debugOpen ? 'Hide' : 'Show'} debug detail
				</button>
			{/if}
		</div>

		{#if debugOpen}
			<div class="mt-2 overflow-x-auto rounded border border-slate-100 bg-slate-50 p-2">
				{#if entry.requirement.embed_seconds !== null || entry.requirement.judge_seconds !== null}
					<p class="mb-2 text-xs text-slate-500">
						embedding: {entry.requirement.embed_seconds !== null ? `${entry.requirement.embed_seconds.toFixed(2)}s` : '—'}
						· judge llm: {entry.requirement.judge_seconds !== null ? `${entry.requirement.judge_seconds.toFixed(2)}s` : '—'}
					</p>
				{/if}
				<table class="w-full text-left text-xs">
					<thead>
						<tr class="text-slate-400">
							<th class="pr-3 font-normal">unit</th>
							<th class="pr-3 font-normal">score</th>
							<th class="pr-3 font-normal">model_verdict</th>
							<th class="pr-3 font-normal">user_verdict</th>
							<th class="font-normal">why</th>
						</tr>
					</thead>
					<tbody>
						{#each entry.judgments as judgment (judgment.id)}
							<tr class="border-t border-slate-200 text-slate-600">
								<td class="pr-3 py-1">U{judgment.unit_id}</td>
								<td class="pr-3 py-1">{judgment.score !== null ? judgment.score.toFixed(3) : '—'}</td>
								<td class="pr-3 py-1">{judgment.model_verdict ?? '—'}</td>
								<td class="pr-3 py-1">{judgment.user_verdict ?? '—'}</td>
								<td class="py-1">{judgment.why ?? '—'}</td>
							</tr>
						{/each}
					</tbody>
				</table>
			</div>
		{/if}
	</div>
{/if}
