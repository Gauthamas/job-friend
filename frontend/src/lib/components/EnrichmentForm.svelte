<script lang="ts">
	// Purely presentational now — no state, no save button of its own.
	// The parent (UnitRow) owns these values via two-way binding, so one
	// "Save" button there covers text + enrichment together.
	let {
		context = $bindable(''),
		contribution = $bindable(''),
		outcome = $bindable(''),
		skills = $bindable<string[]>([]),
		disabled,
		onChange
	}: {
		context: string;
		contribution: string;
		outcome: string;
		skills: string[];
		disabled: boolean;
		// Fired on every real edit (not on the bind: sync itself), so the
		// parent can light up its Save button live instead of on blur.
		onChange: () => void;
	} = $props();

	let skillInput = $state('');

	function addSkill() {
		const tag = skillInput.trim();
		if (tag && !skills.includes(tag)) {
			skills = [...skills, tag];
			onChange();
		}
		skillInput = '';
	}

	function onSkillKeydown(e: KeyboardEvent) {
		if (e.key === 'Enter' || e.key === ',') {
			e.preventDefault();
			addSkill();
		} else if (e.key === 'Backspace' && !skillInput && skills.length > 0) {
			skills = skills.slice(0, -1);
			onChange();
		}
	}

	function removeSkill(tag: string) {
		skills = skills.filter((s) => s !== tag);
		onChange();
	}
</script>

<div class="grid gap-2 text-sm">
	<label class="grid gap-1">
		<span class="text-xs font-medium text-slate-500">Context</span>
		<textarea
			class="rounded border border-slate-200 p-2 disabled:bg-slate-50"
			rows="2"
			bind:value={context}
			oninput={onChange}
			{disabled}
		></textarea>
	</label>
	<label class="grid gap-1">
		<span class="text-xs font-medium text-slate-500">Contribution</span>
		<textarea
			class="rounded border border-slate-200 p-2 disabled:bg-slate-50"
			rows="2"
			bind:value={contribution}
			oninput={onChange}
			{disabled}
		></textarea>
	</label>
	<label class="grid gap-1">
		<span class="text-xs font-medium text-slate-500">Outcome</span>
		<textarea
			class="rounded border border-slate-200 p-2 disabled:bg-slate-50"
			rows="2"
			bind:value={outcome}
			oninput={onChange}
			{disabled}
		></textarea>
	</label>

	<div class="grid gap-1">
		<span class="text-xs font-medium text-slate-500">Skills</span>
		<div class="flex flex-wrap items-center gap-1 rounded border border-slate-200 p-2">
			{#each skills as tag (tag)}
				<span class="flex items-center gap-1 rounded-full bg-slate-100 px-2 py-0.5 text-xs text-slate-700">
					{tag}
					<button
						type="button"
						class="cursor-pointer text-slate-400 hover:text-slate-700 disabled:cursor-not-allowed"
						{disabled}
						onclick={() => removeSkill(tag)}
					>
						×
					</button>
				</span>
			{/each}
			<input
				class="min-w-[6rem] flex-1 border-0 text-sm outline-none disabled:bg-transparent"
				placeholder="Add a skill, press Enter"
				bind:value={skillInput}
				onkeydown={onSkillKeydown}
				onblur={addSkill}
				{disabled}
			/>
		</div>
	</div>
</div>
