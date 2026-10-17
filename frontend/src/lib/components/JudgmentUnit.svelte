<script lang="ts">
	import { jobStore } from '$lib/jobStore.svelte';
	import type { Judgment, Verdict } from '$lib/types';

	let { requirementId, judgment, locked = false }: { requirementId: number; judgment: Judgment; locked?: boolean } =
		$props();

	const CYCLE: Verdict[] = ['match', 'weak', 'none'];
	type DisplayVerdict = Verdict | 'pending';

	// Effective verdict = user_verdict ?? model_verdict (§4) -- the backend
	// exposes both raw fields but never this derived one for a judgment, so
	// this is the one place the frontend derives it: a one-line lookup for
	// *display*, not a match/weak/gap rollup (that always comes from the API).
	// Both null means the requirement hasn't been judged yet (auto mode
	// before its call ran, or manual mode before the user set a verdict) --
	// shown as its own neutral "pending" chip, not "none".
	let effective = $derived<DisplayVerdict>(judgment.user_verdict ?? judgment.model_verdict ?? 'pending');

	// v2: no unit_snapshot -- judging reads the unit's current text, so the
	// UI looks it up live from the inventory (see jobStore.units) instead
	// of a frozen copy on the judgment row.
	let unit = $derived(jobStore.units[judgment.unit_id]);

	const COLORS: Record<DisplayVerdict, string> = {
		match: 'bg-emerald-100 text-emerald-800 border-emerald-300',
		weak: 'bg-amber-100 text-amber-800 border-amber-300',
		none: 'bg-slate-100 text-slate-500 border-slate-300',
		pending: 'bg-slate-50 text-slate-400 border-slate-200 border-dashed'
	};

	const LABELS: Record<DisplayVerdict, string> = {
		match: 'match',
		weak: 'weak',
		none: 'no selection',
		pending: 'pending'
	};

	function cycle() {
		if (locked) return;
		// CYCLE.indexOf('pending') is -1 -- (-1 + 1) % 3 lands on index 0
		// ('match'), so clicking a pending chip starts the cycle fresh.
		const next = CYCLE[(CYCLE.indexOf(effective as Verdict) + 1) % CYCLE.length];
		jobStore.cycleVerdict(requirementId, judgment.id, next);
	}
</script>

<div class="flex items-start gap-2 rounded border border-slate-100 px-2 py-1.5 {effective === 'none' ? 'opacity-50' : ''}">
	<button
		class="shrink-0 cursor-pointer rounded border px-2 py-0.5 text-xs font-medium disabled:cursor-not-allowed disabled:opacity-40 {COLORS[effective]}"
		disabled={locked}
		onclick={cycle}
		title="Click to cycle match → weak → none"
	>
		{LABELS[effective]}
	</button>

	<div class="min-w-0 flex-1">
		<p class="text-sm text-slate-800">{unit?.text ?? '…'}</p>
		{#if judgment.why}
			<p class="mt-0.5 text-xs text-slate-500">{judgment.why}</p>
		{/if}
		{#if judgment.added_by_user}
			<span class="mt-0.5 inline-block rounded bg-slate-900 px-1.5 py-0.5 text-[10px] text-white">Added by you</span>
		{/if}
		{#if jobStore.judgmentErrors[judgment.id]}
			<p class="mt-0.5 text-xs text-red-600">{jobStore.judgmentErrors[judgment.id]}</p>
		{/if}
	</div>
</div>
