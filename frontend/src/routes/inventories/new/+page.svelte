<script lang="ts">
	import { goto } from '$app/navigation';
	import { draftStore } from '$lib/draftStore.svelte';

	// Persisted so a page reload (e.g. Vite's HMR hard-reloading a
	// backgrounded tab once its dev-server websocket drops) doesn't wipe
	// what was typed/pasted. A chosen File can't be serialized, so only
	// name/mode/text survive — a picked PDF must be re-chosen after a reload.
	const FORM_STORAGE_KEY = 'job-friend-upload-form-v1';

	function loadSavedForm(): { name: string; mode: 'text' | 'file'; text: string } {
		const fallback = { name: 'My Resume', mode: 'text' as const, text: '' };
		if (typeof sessionStorage === 'undefined') return fallback;
		try {
			const raw = sessionStorage.getItem(FORM_STORAGE_KEY);
			return raw ? { ...fallback, ...JSON.parse(raw) } : fallback;
		} catch {
			return fallback;
		}
	}

	const saved = loadSavedForm();
	let name = $state(saved.name);
	let mode = $state<'text' | 'file'>(saved.mode);
	let text = $state(saved.text);
	let file = $state<File | null>(null);
	let submitting = $state(false);
	let error = $state<string | null>(null);

	$effect(() => {
		if (typeof sessionStorage === 'undefined') return;
		try {
			sessionStorage.setItem(FORM_STORAGE_KEY, JSON.stringify({ name, mode, text }));
		} catch {
			// Not critical — just means a reload won't restore the form.
		}
	});

	function onFileChange(e: Event) {
		const input = e.target as HTMLInputElement;
		file = input.files?.[0] ?? null;
	}

	async function submit() {
		error = null;
		if (mode === 'text' && !text.trim()) {
			error = 'Paste your resume text first.';
			return;
		}
		if (mode === 'file' && !file) {
			error = 'Choose a PDF file first.';
			return;
		}

		submitting = true;
		// Not awaited: the review screen shows roles/bullets as they stream
		// in, so we navigate immediately rather than waiting here. The fetch
		// itself keeps running regardless of which page is mounted, since
		// draftStore is a module-level singleton.
		draftStore.startStructuring(
			name,
			mode === 'text' ? { mode: 'text', text } : { mode: 'file', file: file as File }
		);
		try {
			sessionStorage.removeItem(FORM_STORAGE_KEY);
		} catch {
			// Not critical.
		}
		await goto('/inventories/review');
	}
</script>

<main class="mx-auto max-w-2xl p-8">
	<h1 class="text-2xl font-semibold text-slate-900">Import your resume</h1>
	<p class="mt-1 text-slate-600">
		Upload a PDF or paste text. The model proposes roles and bullets — you will review everything
		before anything is saved.
	</p>

	<div class="mt-6">
		<label class="block text-sm font-medium text-slate-700" for="inv-name">Inventory name</label>
		<input
			id="inv-name"
			class="mt-1 w-full rounded-md border border-slate-300 px-3 py-2"
			bind:value={name}
		/>
	</div>

	<div class="mt-6 flex gap-4 text-sm">
		<label class="flex items-center gap-2">
			<input type="radio" bind:group={mode} value="text" />
			Paste text
		</label>
		<label class="flex items-center gap-2">
			<input type="radio" bind:group={mode} value="file" />
			Upload PDF
		</label>
	</div>

	{#if mode === 'text'}
		<textarea
			class="mt-3 h-64 w-full rounded-md border border-slate-300 p-3 font-mono text-sm"
			placeholder="Paste your resume text here..."
			bind:value={text}
		></textarea>
	{:else}
		<input
			class="mt-3 block w-full cursor-pointer rounded-md border border-slate-300 text-sm text-slate-600
				file:mr-4 file:cursor-pointer file:rounded-md file:border-0 file:bg-slate-900 file:px-4
				file:py-2 file:text-sm file:font-medium file:text-white hover:file:bg-slate-700"
			type="file"
			accept="application/pdf"
			onchange={onFileChange}
		/>
	{/if}

	{#if error}
		<p class="mt-3 text-sm text-red-600">{error}</p>
	{/if}

	<button
		class="mt-6 cursor-pointer rounded-md bg-slate-900 px-4 py-2 text-white disabled:cursor-not-allowed disabled:opacity-50"
		disabled={submitting}
		onclick={submit}
	>
		Continue to review
	</button>
</main>
