<script lang="ts">
	import UnitRow from './UnitRow.svelte';
	import { formatMonthYear, parseMonthYear } from '$lib/dateFormat';
	import type { RoleViewModel, UnitRowActions } from '$lib/types';

	let {
		role,
		disabled,
		headerEditable,
		onSaveHeader,
		actions,
		onAddUnit,
		addDisabled,
		onDiscardRole,
		onRestoreRole
	}: {
		role: RoleViewModel;
		disabled: boolean;
		headerEditable: boolean;
		onSaveHeader?: (patch: { company: string; title: string; start: string; end: string }) => void;
		actions: UnitRowActions;
		onAddUnit: (text: string) => void;
		addDisabled: boolean;
		onDiscardRole?: () => void;
		onRestoreRole?: () => void;
	} = $props();

	// start/end are edited as "Month YYYY" (matching how the saved editor
	// displays them) but stored as "YYYY-MM" — the format already committed
	// and what the backend's own date normalizer produces.
	let originalStart = $derived(formatMonthYear(role.start));
	let originalEnd = $derived(formatMonthYear(role.end));

	let company = $state('');
	let title = $state('');
	let start = $state('');
	let end = $state('');
	$effect(() => {
		company = role.company;
		title = role.title;
		start = originalStart;
		end = originalEnd;
	});
	function autoGrow(e: Event) {
		const el = e.target as HTMLTextAreaElement;
		el.style.height = 'auto';
		el.style.height = `${el.scrollHeight}px`;
	}

	// No "Save role" button: every keystroke applies the change to local
	// state immediately (not just on blur) — same as every other field on
	// this page, and nothing here is a separate network call anyway.
	function reportHeaderChange() {
		const changed = company !== role.company || title !== role.title || start !== originalStart || end !== originalEnd;
		if (!changed) return;
		onSaveHeader?.({
			company,
			title,
			start: parseMonthYear(start) ?? start,
			end: parseMonthYear(end) ?? end
		});
	}

	let newUnitText = $state('');
	function addUnit() {
		const text = newUnitText.trim();
		if (!text) return;
		onAddUnit(text);
		newUnitText = '';
	}

	function discardOrRestoreRole() {
		if (role.discardedAt) {
			onRestoreRole?.();
			return;
		}
		if (confirm('This will hide this role and its units from matching. You can restore it later.')) {
			onDiscardRole?.();
		}
	}
</script>

<section class="rounded-lg border border-slate-300 p-4 {role.discardedAt ? 'opacity-50' : ''}">
	{#if onDiscardRole || onRestoreRole}
		<div class="mb-2 flex justify-end">
			<button class="cursor-pointer text-xs text-slate-500 hover:underline disabled:cursor-not-allowed disabled:opacity-50" {disabled} onclick={discardOrRestoreRole}>
				{role.discardedAt ? 'Restore role' : 'Discard role'}
			</button>
		</div>
	{/if}
	{#if headerEditable}
		<div class="flex flex-col gap-1">
			<textarea
				class="w-full resize-none overflow-hidden rounded border border-slate-200 px-2 py-1 font-semibold disabled:bg-slate-50"
				rows="1"
				bind:value={company}
				oninput={(e) => { autoGrow(e); reportHeaderChange(); }}
				{disabled}
			></textarea>
			<textarea
				class="w-full resize-none overflow-hidden rounded border border-slate-200 px-2 py-1 text-slate-600 disabled:bg-slate-50"
				rows="1"
				bind:value={title}
				oninput={(e) => { autoGrow(e); reportHeaderChange(); }}
				{disabled}
			></textarea>
			<div class="flex items-center gap-3">
				<input class="min-w-[7rem] flex-1 rounded border border-slate-200 px-2 py-1 text-sm text-slate-500 disabled:bg-slate-50" placeholder="Month YYYY" bind:value={start} oninput={reportHeaderChange} {disabled} />
				<span class="text-slate-400">–</span>
				<input class="min-w-[7rem] flex-1 rounded border border-slate-200 px-2 py-1 text-sm text-slate-500 disabled:bg-slate-50" placeholder="Month YYYY" bind:value={end} oninput={reportHeaderChange} {disabled} />
			</div>
		</div>
	{:else}
		<div>
			<span class="font-semibold">{role.company}</span>
			<span class="text-slate-600"> — {role.title}</span>
			<span class="ml-2 text-sm text-slate-400">{formatMonthYear(role.start)} – {formatMonthYear(role.end)}</span>
		</div>
	{/if}

	<div class="mt-3 space-y-2">
		{#each role.units as unit (unit.key)}
			<UnitRow {unit} siblings={role.units} {disabled} {actions} />
		{/each}
	</div>

	<div class="mt-3 flex gap-2">
		<input
			class="flex-1 rounded border border-slate-200 px-2 py-1 text-sm disabled:bg-slate-50"
			placeholder="New unit text…"
			bind:value={newUnitText}
			disabled={addDisabled}
			onkeydown={(e) => e.key === 'Enter' && addUnit()}
		/>
		<button
			class="cursor-pointer rounded border border-slate-300 px-3 py-1.5 text-sm hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50"
			disabled={addDisabled || !newUnitText.trim()}
			onclick={addUnit}
		>
			+ Add unit
		</button>
	</div>
</section>
