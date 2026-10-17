<script lang="ts">
	import EnrichmentForm from './EnrichmentForm.svelte';
	import type { UnitRowActions, UnitViewModel } from '$lib/types';

	let { unit, siblings, disabled, actions }: {
		unit: UnitViewModel;
		siblings: UnitViewModel[];
		disabled: boolean;
		actions: UnitRowActions;
	} = $props();

	function parseSkills(raw: string | null): string[] {
		if (!raw) return [];
		try {
			const parsed = JSON.parse(raw);
			return Array.isArray(parsed) ? parsed.map(String) : [];
		} catch {
			return [];
		}
	}

	// Seeded and kept in sync via the effect below, not the initializer:
	// `unit` is replaced wholesale after a save (both stores do this), but
	// this component instance persists (keyed by unit.key in the parent's
	// {#each}), so these must track prop changes, not just the first mount.
	let text = $state('');
	let context = $state('');
	let contribution = $state('');
	let outcome = $state('');
	let skills = $state<string[]>([]);

	$effect(() => {
		text = unit.text;
		context = unit.context ?? '';
		contribution = unit.contribution ?? '';
		outcome = unit.outcome ?? '';
		skills = parseSkills(unit.skillsJson);
	});

	let splitting = $state(false);
	let splitTextarea = $state<HTMLTextAreaElement | undefined>();
	let mergeTargetKey = $state<string | number | ''>('');

	let mergeCandidates = $derived(siblings.filter((s) => s.key !== unit.key));

	// No per-field/per-unit Save button: every keystroke (the text
	// textarea's oninput below, or EnrichmentForm's onChange for its own
	// fields) reports the current combined state live, so the page's Save
	// button enables immediately rather than waiting for blur. Draft mode
	// applies the change instantly to local state; the saved editor only
	// stages it locally too — nothing reaches the server until the page's
	// one Save-all button.
	function reportChange() {
		if (!text.trim()) return;
		const changed =
			text !== unit.text ||
			context !== (unit.context ?? '') ||
			contribution !== (unit.contribution ?? '') ||
			outcome !== (unit.outcome ?? '') ||
			JSON.stringify(skills) !== JSON.stringify(parseSkills(unit.skillsJson));
		if (!changed) return;
		actions.onChange(unit.key, {
			text,
			context: context.trim() || null,
			contribution: contribution.trim() || null,
			outcome: outcome.trim() || null,
			skills_json: skills.length > 0 ? JSON.stringify(skills) : null
		});
	}

	function confirmSplit() {
		const pos = splitTextarea?.selectionStart ?? Math.floor(unit.text.length / 2);
		actions.split(unit.key, pos);
		splitting = false;
	}

	function doMerge() {
		if (mergeTargetKey === '') return;
		actions.merge(unit.key, mergeTargetKey);
		mergeTargetKey = '';
	}

	function discardOrRestore() {
		if (unit.discardedAt) {
			actions.restore?.(unit.key);
			return;
		}
		if (confirm('This will hide this unit from matching. You can restore it later.')) {
			actions.discard?.(unit.key);
		}
	}
</script>

<div class="rounded-md border border-slate-200 p-3 {unit.discardedAt ? 'opacity-50' : ''}">
	<div class="flex items-start gap-2">
		<span
			class="mt-1 shrink-0 rounded px-1.5 py-0.5 text-xs"
			class:bg-slate-100={unit.source === 'parsed'}
			class:text-slate-600={unit.source === 'parsed'}
			class:bg-amber-100={unit.source === 'manual'}
			class:text-amber-800={unit.source === 'manual'}
		>
			{unit.source}
		</span>
		{#if unit.streaming}
			<span class="mt-1 shrink-0 text-xs text-slate-400">generating…</span>
		{/if}
		<textarea
			class="min-h-[3rem] w-full resize-y rounded border border-slate-200 p-2 text-sm disabled:bg-slate-50 disabled:text-slate-500"
			bind:value={text}
			oninput={reportChange}
			{disabled}
		></textarea>
	</div>

	{#if splitting}
		<div class="mt-2 rounded bg-slate-50 p-2">
			<p class="mb-1 text-xs text-slate-500">Click in the text where the split should go, then confirm.</p>
			<textarea bind:this={splitTextarea} class="w-full rounded border border-slate-300 p-2 text-sm" value={unit.text}
			></textarea>
			<div class="mt-2 flex gap-2">
				<button class="cursor-pointer rounded bg-slate-900 px-2 py-1 text-xs text-white" onclick={confirmSplit}>Split here</button>
				<button class="cursor-pointer rounded border border-slate-300 px-2 py-1 text-xs" onclick={() => (splitting = false)}>Cancel</button>
			</div>
		</div>
	{/if}

	<div class="mt-3 border-t border-slate-100 pt-3">
		<EnrichmentForm bind:context bind:contribution bind:outcome bind:skills {disabled} onChange={reportChange} />
	</div>

	<div class="mt-3 flex flex-wrap items-center gap-3 text-xs text-slate-600">
		<button class="cursor-pointer hover:underline disabled:cursor-not-allowed disabled:opacity-50" {disabled} onclick={() => (splitting = true)}>
			Split
		</button>

		{#if mergeCandidates.length > 0}
			<span class="flex items-center gap-1">
				Merge with
				<select class="rounded border border-slate-200 px-1 py-0.5" bind:value={mergeTargetKey} {disabled}>
					<option value="">choose…</option>
					{#each mergeCandidates as candidate (candidate.key)}
						<option value={candidate.key}>{candidate.text.slice(0, 40)}</option>
					{/each}
				</select>
				<button
					class="cursor-pointer text-slate-900 underline disabled:cursor-not-allowed disabled:opacity-50"
					disabled={disabled || mergeTargetKey === ''}
					onclick={doMerge}
				>
					Merge
				</button>
			</span>
		{/if}

		<button
			class="cursor-pointer text-red-600 hover:underline disabled:cursor-not-allowed disabled:opacity-50"
			{disabled}
			onclick={() => actions.delete(unit.key)}
		>
			Delete
		</button>

		{#if actions.discard || actions.restore}
			<button
				class="cursor-pointer hover:underline disabled:cursor-not-allowed disabled:opacity-50"
				{disabled}
				onclick={discardOrRestore}
			>
				{unit.discardedAt ? 'Restore' : 'Discard'}
			</button>
		{/if}
	</div>
</div>
