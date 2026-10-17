<script lang="ts">
	import { page } from '$app/state';
	import {
		finishLetter,
		generateLetter,
		getLetter,
		getUnit,
		patchLetter,
		patchLetterPointers,
		patchLetterSection,
		patchMatchedSections,
		patchThreadIdea
	} from '$lib/api';
	import type { GenerateResult, Letter, LetterSection, SavedUnit } from '$lib/types';

	const jobId = $derived(Number(page.params.id));

	let letter = $state<Letter | null>(null);
	let loading = $state(true);
	let error = $state<string | null>(null);

	let editingPointers = $state<Record<string, boolean>>({});
	let pointerDrafts = $state<Record<string, string>>({});
	let timers: Record<string, ReturnType<typeof setTimeout>> = {};
	let saveStatus = $state<Record<string, string>>({});

	let drawerUnit = $state<SavedUnit | null>(null);
	let drawerQuote = $state<string | null>(null);
	let drawerLoading = $state(false);

	let generated = $state<GenerateResult | null>(null);
	let generating = $state(false);
	let copied = $state(false);

	async function load() {
		loading = true;
		error = null;
		try {
			letter = await getLetter(jobId);
		} catch (e) {
			error = e instanceof Error ? e.message : 'Failed to load.';
		} finally {
			loading = false;
		}
	}

	$effect(() => {
		load();
	});

	function words(text: string): number {
		const m = (text || '').trim().match(/\S+/g);
		return m ? m.length : 0;
	}

	// Server-provided word_count/total_word_count are a snapshot from the
	// last full load -- scheduleSectionSave mutates section.text locally
	// (for responsive typing) without waiting for a round trip, so those
	// snapshots go stale the moment you type. Recomputed live from the
	// text actually on screen instead, same rule as the backend
	// (letter.py's generate_letter_text): skipped sections don't count.
	const totalWordCount = $derived(
		letter ? letter.sections.filter((s) => !s.skipped).reduce((sum, s) => sum + words(s.text), 0) : 0
	);

	function scheduleSectionSave(key: string, text: string) {
		if (!letter) return;
		const section = letter.sections.find((s) => s.key === key);
		if (section) section.text = text;
		saveStatus[key] = 'Saving…';
		clearTimeout(timers[key]);
		timers[key] = setTimeout(async () => {
			try {
				await patchLetterSection(jobId, key, { text });
				saveStatus[key] = 'Saved';
			} catch {
				saveStatus[key] = 'Failed to save';
			}
		}, 900);
	}

	async function toggleSkip(section: LetterSection) {
		section.skipped = !section.skipped;
		await patchLetterSection(jobId, section.key, { skipped: section.skipped });
	}

	function openPointerEdit(section: LetterSection) {
		editingPointers[section.key] = !editingPointers[section.key];
		if (editingPointers[section.key]) {
			pointerDrafts[section.key] = section.pointer_text ?? '';
		}
	}

	async function savePointers(key: string) {
		if (!letter) return;
		const updated = await patchLetterPointers(jobId, key, pointerDrafts[key]);
		letter = updated;
	}

	async function resetPointers(key: string) {
		if (!letter) return;
		const updated = await patchLetterPointers(jobId, key, null);
		letter = updated;
		editingPointers[key] = false;
	}

	async function openDrawer(unitId: number, quote: string | null) {
		drawerLoading = true;
		drawerQuote = quote;
		try {
			drawerUnit = await getUnit(unitId);
		} finally {
			drawerLoading = false;
		}
	}

	function closeDrawer() {
		drawerUnit = null;
		drawerQuote = null;
	}

	async function stepMatchedSections(delta: number) {
		if (!letter) return;
		const next = Math.max(0, letter.matched_sections_setting + delta);
		await patchMatchedSections(next);
		await load();
	}

	async function saveThreadIdea(threadId: number | null, idea: string) {
		if (!threadId) return;
		await patchThreadIdea(threadId, idea);
		await load();
	}

	async function runGenerate() {
		generating = true;
		try {
			generated = await generateLetter(jobId);
			copied = false;
		} finally {
			generating = false;
		}
	}

	function backToEdit() {
		generated = null;
	}

	async function thisIsTheOne() {
		if (!generated) return;
		try {
			await navigator.clipboard.writeText(generated.assembled_text);
			copied = true;
		} catch {
			copied = false;
		}
		letter = await finishLetter(jobId);
	}
</script>

<main class="pb-24">
	{#if loading}
		<p class="p-8 text-slate-500">Loading…</p>
	{:else if error}
		<p class="p-8 text-sm text-red-600">{error}</p>
	{:else if letter}
		<!-- Sticky thread bar -->
		<div class="sticky top-0 z-10 border-b border-slate-200 bg-slate-50 px-4 py-2">
			<div class="mx-auto max-w-3xl space-y-1">
				{#each [{ label: 'Primary', bar: letter.primary }, { label: 'Secondary', bar: letter.secondary }] as { label, bar } (label)}
					<div class="flex items-center gap-2">
						<span class="w-20 shrink-0 text-xs font-semibold tracking-wide text-slate-400 uppercase">{label}</span>
						<input
							class="min-w-0 flex-1 rounded border border-transparent bg-transparent px-1 py-0.5 text-sm font-semibold text-slate-800 hover:border-slate-300 focus:border-slate-400 focus:bg-white focus:outline-none"
							value={bar.edited_idea ?? bar.idea ?? ''}
							disabled={!bar.thread_id}
							onblur={(e) => saveThreadIdea(bar.thread_id, (e.target as HTMLInputElement).value)}
						/>
					</div>
					{#if bar.statements.length > 0}
						<details class="ml-20">
							<summary class="cursor-pointer text-xs text-slate-400">statements ({bar.statements.length})</summary>
							{#each bar.statements as s (s)}
								<p class="mt-0.5 text-xs text-slate-500">{s}</p>
							{/each}
						</details>
					{/if}
				{/each}
			</div>
		</div>

		<div class="mx-auto max-w-3xl p-8">
			<a href={`/jobs/${jobId}/primary-secondary`} class="text-sm text-slate-500 underline">← Back to primary/secondary</a>

			<div class="mt-2 flex items-center justify-between">
				<h1 class="text-2xl font-semibold text-slate-900">Write the letter</h1>
				<span class="text-xs font-mono text-slate-500">{totalWordCount} words in total</span>
			</div>

			<div class="mt-2 flex items-center gap-2 text-sm text-slate-500">
				<span>showing {letter.matched_shown} of {letter.matched_total} matched requirements</span>
				<button class="cursor-pointer rounded border border-slate-300 px-1.5 text-xs" onclick={() => stepMatchedSections(-1)}>−</button>
				<button class="cursor-pointer rounded border border-slate-300 px-1.5 text-xs" onclick={() => stepMatchedSections(1)}>+</button>
			</div>

			<label class="mt-6 block text-sm">
				<span class="text-xs font-medium text-slate-500">Greeting</span>
				<input
					class="mt-1 w-full rounded border border-slate-200 p-2 text-sm"
					value={letter.greeting ?? ''}
					onblur={(e) => patchLetter(jobId, { greeting: (e.target as HTMLInputElement).value })}
				/>
			</label>

			<div class="mt-6 grid gap-10">
				{#each letter.sections as section (section.key)}
					<section class="border-t border-slate-200 pt-6 first:border-0 first:pt-0">
						<div class="flex items-center justify-between">
							<div class="flex flex-wrap items-center gap-2">
								{#if section.kind === 'requirement'}
									<span class="rounded border border-slate-300 px-1.5 py-0.5 text-xs text-slate-500 uppercase">{section.weight}</span>
									<span
										class="rounded px-1.5 py-0.5 text-xs font-medium {section.verdict === 'match'
											? 'bg-emerald-100 text-emerald-800'
											: 'bg-amber-100 text-amber-800'}"
									>
										{section.verdict}
									</span>
								{:else if section.kind === 'weak'}
									<span class="text-xs font-semibold tracking-wide text-slate-400 uppercase">Weak (optional)</span>
								{:else if section.kind === 'gaps'}
									<span class="text-xs font-semibold tracking-wide text-slate-400 uppercase">Gaps (optional)</span>
								{:else if section.key === 'open'}
									<span class="text-xs font-semibold tracking-wide text-slate-400 uppercase">Opening</span>
								{:else if section.key === 'close'}
									<span class="text-xs font-semibold tracking-wide text-slate-400 uppercase">Close</span>
								{/if}
							</div>
							{#if section.kind !== 'plain'}
								<label class="flex items-center gap-1 text-xs text-slate-400">
									<input type="checkbox" checked={section.skipped} onchange={() => toggleSkip(section)} />
									skip
								</label>
							{/if}
						</div>

						{#if section.kind === 'requirement'}
							<p class="mt-2 text-base font-semibold text-slate-900">"{section.requirement_text}"</p>
						{:else if section.kind === 'gaps'}
							{#each section.requirements as r (r.id)}
								<p class="mt-1 text-sm text-slate-700">
									"{r.text}" <span class="text-xs text-slate-400">({r.weight})</span>
								</p>
							{/each}
						{/if}

						{#if section.key === 'open'}
							<!-- Display only -- never inserted into the section text. -->
							<details class="mt-2 rounded border border-slate-200 bg-slate-50 p-2">
								<summary class="cursor-pointer text-xs font-medium text-slate-500">Hint</summary>
								<div class="mt-2 grid gap-1.5 text-xs text-slate-600">
									{#if letter.opening_hint.company || letter.opening_hint.role_title}
										<p>{[letter.opening_hint.role_title, letter.opening_hint.company].filter(Boolean).join(' at ')}</p>
									{/if}
									{#if letter.opening_hint.statement_text}
										<p>
											"{letter.opening_hint.statement_text}"
											{#if letter.opening_hint.statement_quote}
												— "{letter.opening_hint.statement_quote}"
											{/if}
										</p>
									{/if}
									<p class="italic text-slate-400">{letter.opening_hint.question}</p>
								</div>
							</details>
						{:else if section.key === 'close'}
							<details class="mt-2 rounded border border-slate-200 bg-slate-50 p-2">
								<summary class="cursor-pointer text-xs font-medium text-slate-500">Hint</summary>
								<div class="mt-2 grid gap-1.5 text-xs text-slate-600">
									{#if letter.close_hint.uncovered.length > 0}
										<p class="font-medium text-slate-500">Not covered by your units</p>
										{#each letter.close_hint.uncovered as r (r.id)}
											<p>"{r.text}" <span class="text-slate-400">({r.weight})</span></p>
										{/each}
									{/if}
									<p class="italic text-slate-400">{letter.close_hint.question}</p>
								</div>
							</details>
						{/if}

						{#if section.kind === 'requirement' || section.kind === 'weak'}
							<div class="mt-3">
								<div class="flex items-center justify-between">
									<span class="text-xs font-medium text-slate-500">Pointers</span>
									<div class="flex items-center gap-2">
										<span class="rounded px-1.5 py-0.5 text-xs {section.pointers_edited ? 'bg-emerald-100 text-emerald-700' : 'bg-slate-100 text-slate-500'}">
											{section.pointers_edited ? 'edited by you' : 'proposed'}
										</span>
										{#if section.pointers_edited}
											<button class="cursor-pointer text-xs text-slate-400 underline" onclick={() => resetPointers(section.key)}>Reset</button>
										{/if}
										<button class="cursor-pointer text-xs text-slate-400 underline" onclick={() => openPointerEdit(section)}>
											{editingPointers[section.key] ? 'Done' : 'Edit'}
										</button>
									</div>
								</div>
								{#if editingPointers[section.key]}
									<textarea
										class="mt-1 w-full rounded border border-slate-200 p-2 text-sm"
										rows="4"
										bind:value={pointerDrafts[section.key]}
										onblur={() => savePointers(section.key)}
									></textarea>
								{:else if section.kind === 'requirement'}
									<ul class="mt-1 list-disc space-y-1 pl-5 text-sm text-slate-700">
										{#each section.pointers as p (p.unit_id)}
											<li>
												<button class="cursor-pointer text-left underline-offset-2 hover:underline" onclick={() => openDrawer(p.unit_id, p.quote)}>
													{p.line}
												</button>
												{#if p.is_primary}<span class="ml-1 rounded bg-indigo-100 px-1 text-xs text-indigo-700">P</span>{/if}
												{#if p.is_secondary}<span class="ml-1 rounded bg-teal-100 px-1 text-xs text-teal-700">S</span>{/if}
											</li>
										{/each}
									</ul>
								{:else}
									<!-- Weak: grouped per requirement -- the same unit can
									     legitimately point to more than one weak requirement,
									     so each posting line keeps its own pointer list. -->
									{#each section.requirements as r (r.id)}
										<p class="mt-2 text-sm font-medium text-slate-700">
											"{r.text}" <span class="text-xs text-slate-400">({r.weight})</span>
										</p>
										<ul class="mt-1 list-disc space-y-1 pl-5 text-sm text-slate-700">
											{#each r.pointers ?? [] as p (p.unit_id)}
												<li>
													<button class="cursor-pointer text-left underline-offset-2 hover:underline" onclick={() => openDrawer(p.unit_id, p.quote)}>
														{p.line}
													</button>
													{#if p.is_primary}<span class="ml-1 rounded bg-indigo-100 px-1 text-xs text-indigo-700">P</span>{/if}
													{#if p.is_secondary}<span class="ml-1 rounded bg-teal-100 px-1 text-xs text-teal-700">S</span>{/if}
												</li>
											{/each}
										</ul>
									{/each}
								{/if}
							</div>
						{/if}

						{#if !section.skipped || section.kind === 'plain'}
							<textarea
								class="mt-3 w-full rounded border border-slate-200 p-3 text-base leading-relaxed"
								rows="5"
								value={section.text}
								oninput={(e) => scheduleSectionSave(section.key, (e.target as HTMLTextAreaElement).value)}
							></textarea>
							<div class="mt-1 flex justify-between text-xs text-slate-400">
								<span>{saveStatus[section.key] ?? ''}</span>
								<span class="flex items-center gap-2">
									{#if letter.section_char_limit}
										<span class={section.text.length > letter.section_char_limit ? 'font-medium text-red-600' : ''}>
											{section.text.length}/{letter.section_char_limit} chars
										</span>
									{/if}
									<span>{words(section.text)} words</span>
								</span>
							</div>
						{/if}
					</section>
				{/each}
			</div>

			<div class="mt-10 grid gap-3 border-t border-slate-200 pt-6">
				<label class="text-sm">
					<span class="text-xs font-medium text-slate-500">Sign-off</span>
					<textarea
						class="mt-1 w-full rounded border border-slate-200 p-2 text-sm"
						rows="2"
						value={letter.signoff ?? ''}
						onblur={(e) => patchLetter(jobId, { signoff: (e.target as HTMLTextAreaElement).value })}
					></textarea>
				</label>
			</div>

			<div class="mt-6 flex items-center gap-3">
				<button
					class="cursor-pointer rounded-md bg-slate-900 px-4 py-2 text-sm text-white disabled:opacity-40"
					disabled={generating}
					onclick={runGenerate}
				>
					{generating ? 'Generating…' : 'Generate'}
				</button>
				{#if letter.finished}
					<span class="text-xs text-emerald-700">Finished</span>
				{/if}
			</div>

			{#if generated}
				<div class="mt-6 rounded-lg border border-slate-200 bg-slate-50 p-5">
					<p class="text-xs font-medium text-slate-500">Preview ({generated.word_count} words)</p>
					<pre class="mt-2 whitespace-pre-wrap font-serif text-sm text-slate-800">{generated.assembled_text}</pre>
					<div class="mt-3 flex items-center gap-3">
						<button class="cursor-pointer rounded border border-slate-300 px-3 py-1.5 text-sm" onclick={backToEdit}>
							Back to edit
						</button>
						<button class="cursor-pointer rounded-md bg-slate-900 px-3 py-1.5 text-sm text-white" onclick={thisIsTheOne}>
							This is the one
						</button>
						{#if copied}<span class="text-xs text-emerald-700">Copied to clipboard</span>{/if}
					</div>
				</div>
			{/if}
		</div>
	{/if}
</main>

{#if drawerUnit}
	<div class="fixed inset-0 z-20 flex justify-end bg-black/30" onclick={closeDrawer} onkeydown={(e) => e.key === 'Escape' && closeDrawer()} role="presentation">
		<div class="h-full w-full max-w-md overflow-y-auto bg-white p-6" onclick={(e) => e.stopPropagation()} role="presentation">
			<button class="cursor-pointer text-sm text-slate-400" onclick={closeDrawer}>Close ✕</button>
			{#if drawerLoading}
				<p class="mt-4 text-slate-500">Loading…</p>
			{:else}
				<p class="mt-4 text-base font-medium text-slate-900">{drawerUnit.text}</p>
				<div class="mt-4 grid gap-3 text-sm">
					<div>
						<p class="text-xs font-medium text-slate-500">Situation</p>
						<p class="text-slate-700">
							{drawerUnit.context_skipped ? 'not provided' : drawerUnit.context || 'not provided'}
						</p>
					</div>
					<div>
						<p class="text-xs font-medium text-slate-500">Contribution</p>
						<p class="text-slate-700">
							{drawerUnit.contribution_skipped ? 'not provided' : drawerUnit.contribution || 'not provided'}
						</p>
					</div>
					<div>
						<p class="text-xs font-medium text-slate-500">Result</p>
						<p class="text-slate-700">
							{drawerUnit.outcome_skipped ? 'not provided' : drawerUnit.outcome || 'not provided'}
						</p>
					</div>
				</div>
				{#if drawerQuote}
					<p class="mt-4 text-xs font-medium text-slate-500">Verified quote</p>
					<p class="mt-1 rounded bg-amber-100 p-2 text-sm text-amber-900">"{drawerQuote}"</p>
				{/if}
			{/if}
		</div>
	</div>
{/if}
