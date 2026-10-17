<script lang="ts">
	import { patchUnit } from '$lib/api';
	import type { EnrichmentUnit, EnrichQuestions, SavedUnit } from '$lib/types';

	let {
		entry,
		questions,
		onSaved
	}: {
		entry: EnrichmentUnit;
		questions: EnrichQuestions;
		onSaved: (unit: SavedUnit) => void;
	} = $props();

	type Field = 'context' | 'contribution' | 'outcome';
	const FIELDS: { field: Field; label: string }[] = [
		{ field: 'context', label: questions.context },
		{ field: 'contribution', label: questions.contribution },
		{ field: 'outcome', label: questions.outcome }
	];

	// Local editable copies, seeded once from the unit this card was built
	// for -- the parent keys the {#each} by unit id, so a new unit means a
	// new card instance, not a prop change on this one.
	let values = $state<Record<Field, string>>({
		context: entry.unit.context ?? '',
		contribution: entry.unit.contribution ?? '',
		outcome: entry.unit.outcome ?? ''
	});
	let skipped = $state<Record<Field, boolean>>({
		context: entry.unit.context_skipped,
		contribution: entry.unit.contribution_skipped,
		outcome: entry.unit.outcome_skipped
	});
	let saving = $state<Record<Field, boolean>>({ context: false, contribution: false, outcome: false });
	let saveError = $state<string | null>(null);

	async function saveField(field: Field, patch: Record<string, string | boolean | null>) {
		saving[field] = true;
		saveError = null;
		try {
			const updated = await patchUnit(entry.unit.id, patch);
			values[field] = (updated[field] as string | null) ?? '';
			skipped[field] = updated[`${field}_skipped` as const];
			onSaved(updated);
		} catch (e) {
			saveError = e instanceof Error ? e.message : 'Failed to save.';
		} finally {
			saving[field] = false;
		}
	}

	// Skills: same tag-chip editor and the same patchUnit() save as the
	// inventory edit screen's EnrichmentForm -- re-embeds the skills field
	// on save there too, via the same code path.
	function parseSkills(raw: string | null): string[] {
		if (!raw) return [];
		try {
			const parsed = JSON.parse(raw);
			return Array.isArray(parsed) ? parsed : [];
		} catch {
			return [];
		}
	}

	let skills = $state<string[]>(parseSkills(entry.unit.skills_json));
	let skillInput = $state('');
	let skillsSaving = $state(false);

	async function saveSkills() {
		skillsSaving = true;
		saveError = null;
		try {
			const updated = await patchUnit(entry.unit.id, {
				skills_json: skills.length > 0 ? JSON.stringify(skills) : null
			});
			skills = parseSkills(updated.skills_json);
			onSaved(updated);
		} catch (e) {
			saveError = e instanceof Error ? e.message : 'Failed to save.';
		} finally {
			skillsSaving = false;
		}
	}

	function addSkill() {
		const tag = skillInput.trim();
		if (tag && !skills.includes(tag)) {
			skills = [...skills, tag];
			saveSkills();
		}
		skillInput = '';
	}

	function onSkillKeydown(e: KeyboardEvent) {
		if (e.key === 'Enter' || e.key === ',') {
			e.preventDefault();
			addSkill();
		} else if (e.key === 'Backspace' && !skillInput && skills.length > 0) {
			skills = skills.slice(0, -1);
			saveSkills();
		}
	}

	function removeSkill(tag: string) {
		skills = skills.filter((s) => s !== tag);
		saveSkills();
	}

	// Saving real text always clears that field's skip flag -- "nothing to
	// add" and "here's my answer" are mutually exclusive states.
	function onBlur(field: Field) {
		const text = values[field].trim();
		const unchanged = text === (entry.unit[field] ?? '') && skipped[field] === entry.unit[`${field}_skipped`];
		if (unchanged) return;
		saveField(field, { [field]: text || null, [`${field}_skipped`]: false });
	}

	function nothingToAdd(field: Field) {
		values[field] = '';
		saveField(field, { [field]: null, [`${field}_skipped`]: true });
	}
</script>

<div class="rounded-lg border border-slate-200 p-4 {entry.complete ? 'bg-emerald-50/40' : ''}">
	<div class="flex items-start justify-between gap-3">
		<p class="text-sm text-slate-900">{entry.unit.text}</p>
		<span
			class="shrink-0 rounded border px-2 py-0.5 text-xs font-medium {entry.complete
				? 'border-emerald-300 bg-emerald-100 text-emerald-800'
				: 'border-slate-300 bg-slate-100 text-slate-500'}"
		>
			{entry.complete ? 'enriched' : 'needs answers'}
		</span>
	</div>

	<div class="mt-1 flex flex-wrap gap-1">
		{#each entry.matched_requirements as req (req.id)}
			<span class="rounded border border-slate-200 bg-slate-50 px-2 py-0.5 text-xs text-slate-500">
				{req.text}
			</span>
		{/each}
	</div>

	<div class="mt-3 grid gap-3">
		{#each FIELDS as { field, label } (field)}
			<div>
				<div class="flex items-center justify-between gap-2">
					<span class="text-xs font-medium text-slate-600">{label}</span>
					{#if saving[field]}
						<span class="text-xs text-slate-400">Saving…</span>
					{/if}
				</div>
				<textarea
					class="mt-1 w-full rounded border border-slate-200 p-2 text-sm disabled:bg-slate-50 disabled:text-slate-400"
					rows="2"
					disabled={skipped[field]}
					placeholder={skipped[field] ? 'Marked as nothing to add' : ''}
					bind:value={values[field]}
					onblur={() => onBlur(field)}
				></textarea>
				<button
					type="button"
					class="mt-1 cursor-pointer rounded border px-2 py-0.5 text-xs {skipped[field]
						? 'border-slate-400 bg-slate-100 text-slate-700'
						: 'border-slate-300 text-slate-500 hover:bg-slate-50'}"
					onclick={() => (skipped[field] ? saveField(field, { [`${field}_skipped`]: false }) : nothingToAdd(field))}
				>
					{skipped[field] ? 'Undo "nothing to add"' : 'Nothing to add'}
				</button>
			</div>
		{/each}

		<div>
			<div class="flex items-center justify-between gap-2">
				<span class="text-xs font-medium text-slate-600">Skills</span>
				{#if skillsSaving}
					<span class="text-xs text-slate-400">Saving…</span>
				{/if}
			</div>
			<div class="mt-1 flex flex-wrap items-center gap-1 rounded border border-slate-200 p-2">
				{#each skills as tag (tag)}
					<span class="flex items-center gap-1 rounded-full bg-slate-100 px-2 py-0.5 text-xs text-slate-700">
						{tag}
						<button
							type="button"
							class="cursor-pointer text-slate-400 hover:text-slate-700"
							onclick={() => removeSkill(tag)}
						>
							×
						</button>
					</span>
				{/each}
				<input
					class="min-w-[6rem] flex-1 border-0 text-sm outline-none"
					placeholder="Add a skill, press Enter"
					bind:value={skillInput}
					onkeydown={onSkillKeydown}
					onblur={addSkill}
				/>
			</div>
		</div>
	</div>

	{#if saveError}
		<p class="mt-2 text-xs text-red-600">{saveError}</p>
	{/if}
</div>
