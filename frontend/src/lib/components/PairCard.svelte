<script lang="ts">
	import { patchStatement } from '$lib/api';
	import type { Pair, SavedUnit, Statement, StatementStatus } from '$lib/types';

	let {
		pair,
		onSaved
	}: {
		pair: Pair;
		onSaved: (statement: Statement) => void;
	} = $props();

	let text = $state(pair.statement.text ?? '');
	let saving = $state(false);
	let saveError = $state<string | null>(null);

	// A new PairCard instance per pair.id (parent keys the view by it), so
	// this only needs to resync when the SAME instance's underlying pair
	// data changes shape from a save elsewhere (autofill, confirm-all).
	$effect(() => {
		text = pair.statement.text ?? '';
	});

	async function save(status: StatementStatus, body: string | null) {
		saving = true;
		saveError = null;
		try {
			const updated = await patchStatement(pair.statement.id, { status, text: body });
			onSaved(updated);
		} catch (e) {
			saveError = e instanceof Error ? e.message : 'Failed to save.';
		} finally {
			saving = false;
		}
	}

	function onBlur() {
		const trimmed = text.trim();
		if (trimmed === (pair.statement.text ?? '') && pair.statement.status === 'written') return;
		if (!trimmed) return;
		save('written', trimmed);
	}

	function toggleNone() {
		if (pair.statement.status === 'none') {
			save('unanswered', null); // re-opens the text box
		} else {
			text = '';
			save('none', null);
		}
	}

	function labelFor(unit: SavedUnit): { label: string; value: string | null; skipped: boolean }[] {
		return [
			{ label: 'Situation', value: unit.context, skipped: unit.context_skipped },
			{ label: 'Contribution', value: unit.contribution, skipped: unit.contribution_skipped },
			{ label: 'Result', value: unit.outcome, skipped: unit.outcome_skipped }
		];
	}
</script>

<div class="rounded-lg border border-slate-200 p-5">
	<div class="grid gap-4 sm:grid-cols-2">
		{#each [pair.unit_a, pair.unit_b] as unit (unit.id)}
			<div class="rounded border border-slate-100 bg-slate-50 p-3">
				<p class="text-sm font-medium text-slate-900">{unit.text}</p>
				<div class="mt-2 grid gap-1.5">
					{#each labelFor(unit) as field (field.label)}
						<div class="text-xs">
							<span class="font-medium text-slate-500">{field.label}:</span>
							<span class="text-slate-600">
								{field.skipped ? 'not provided' : field.value || 'not provided'}
							</span>
						</div>
					{/each}
				</div>
			</div>
		{/each}
	</div>

	{#if pair.statement.autofilled_from_job_id !== null}
		<p class="mt-3 inline-block rounded-full border border-amber-200 bg-amber-50 px-2 py-0.5 text-xs text-amber-800">
			autofilled from {pair.statement.autofilled_from_job_title ?? 'an earlier job'}
			{#if pair.statement.autofilled_from_date}· {pair.statement.autofilled_from_date.slice(0, 10)}{/if}
		</p>
	{/if}

	<div class="mt-3">
		<div class="flex items-center justify-between gap-2">
			<span class="text-sm font-medium text-slate-700">What do these two have in common?</span>
			{#if saving}<span class="text-xs text-slate-400">Saving…</span>{/if}
		</div>
		<textarea
			class="mt-1 w-full rounded border border-slate-200 p-2 text-sm disabled:bg-slate-50 disabled:text-slate-400"
			rows="2"
			disabled={pair.statement.status === 'none'}
			placeholder={pair.statement.status === 'none' ? 'Marked as none' : ''}
			bind:value={text}
			onblur={onBlur}
		></textarea>
		<button
			type="button"
			class="mt-1 cursor-pointer rounded border px-2 py-0.5 text-xs {pair.statement.status === 'none'
				? 'border-slate-400 bg-slate-100 text-slate-700'
				: 'border-slate-300 text-slate-500 hover:bg-slate-50'}"
			onclick={toggleNone}
		>
			{pair.statement.status === 'none' ? 'Undo None' : 'None'}
		</button>
	</div>

	{#if saveError}
		<p class="mt-2 text-xs text-red-600">{saveError}</p>
	{/if}
</div>
