<script lang="ts">
	import { onMount } from 'svelte';
	import { getSettings, patchSettings, resetSetting } from '$lib/api';
	import type { Setting } from '$lib/types';

	const GROUP_ORDER = ['Judging', 'Enrichment', 'Pairs', 'Threads', 'Writing'];

	let settings = $state<Setting[]>([]);
	let loading = $state(true);
	let error = $state<string | null>(null);
	let drafts = $state<Record<string, string>>({});
	let savingKey = $state<string | null>(null);

	onMount(load);

	async function load() {
		loading = true;
		try {
			const res = await getSettings();
			settings = res.settings;
			drafts = {};
			for (const s of settings) drafts[s.key] = displayValue(s);
		} catch (e) {
			error = e instanceof Error ? e.message : 'Failed to load settings.';
		} finally {
			loading = false;
		}
	}

	function displayValue(s: Setting): string {
		if (s.value === null) return '';
		if (s.type === 'bool') return s.value ? 'true' : 'false';
		if (s.type === 'str_list') return Array.isArray(s.value) ? s.value.join(', ') : '';
		return String(s.value);
	}

	function parseValue(s: Setting, raw: string): unknown {
		if (s.type === 'int_or_none' && raw.trim() === '') return null;
		if (s.type === 'bool') return raw === 'true';
		if (s.type === 'int' || s.type === 'int_or_none') return parseInt(raw, 10);
		if (s.type === 'str_list') {
			return raw
				.split(',')
				.map((v) => v.trim())
				.filter((v) => v.length > 0);
		}
		return raw;
	}

	async function save(s: Setting) {
		savingKey = s.key;
		error = null;
		try {
			const value = parseValue(s, drafts[s.key] ?? '');
			const res = await patchSettings({ [s.key]: value });
			settings = res.settings;
			const updated = settings.find((x) => x.key === s.key);
			if (updated) drafts[s.key] = displayValue(updated);
		} catch (e) {
			error = e instanceof Error ? e.message : `Failed to update ${s.key}.`;
		} finally {
			savingKey = null;
		}
	}

	async function reset(s: Setting) {
		savingKey = s.key;
		error = null;
		try {
			const res = await resetSetting(s.key);
			settings = res.settings;
			const updated = settings.find((x) => x.key === s.key);
			if (updated) drafts[s.key] = displayValue(updated);
		} catch (e) {
			error = e instanceof Error ? e.message : `Failed to reset ${s.key}.`;
		} finally {
			savingKey = null;
		}
	}

	function byGroup(group: string): Setting[] {
		return settings.filter((s) => s.group === group);
	}
</script>

<main class="mx-auto max-w-3xl p-8">
	<div class="flex items-center justify-between">
		<h1 class="text-2xl font-semibold text-slate-900">Settings</h1>
		<a href="/inventories" class="text-sm text-slate-500 underline">Back</a>
	</div>
	<p class="mt-2 text-sm text-slate-500">Changes apply to future runs only — anything already judged, proposed, or written stays as it is.</p>

	{#if loading}
		<p class="mt-6 text-slate-500">Loading…</p>
	{:else}
		{#if error}
			<p class="mt-4 rounded-md bg-red-50 p-3 text-sm text-red-700">{error}</p>
		{/if}

		{#each GROUP_ORDER as group (group)}
			{@const items = byGroup(group)}
			{#if items.length}
				<section class="mt-8">
					<h2 class="text-sm font-semibold tracking-wide text-slate-400 uppercase">{group}</h2>
					<div class="mt-3 divide-y divide-slate-100 rounded-md border border-slate-200">
						{#each items as s (s.key)}
							<div class="flex items-center gap-3 p-3">
								<div class="flex-1">
									<div class="font-mono text-sm text-slate-700">{s.key}</div>
									<div class="text-xs text-slate-400">default: {s.default === null ? '(none)' : String(s.default)}</div>
								</div>
								{#if s.type === 'bool'}
									<select bind:value={drafts[s.key]} class="rounded-md border border-slate-300 px-2 py-1 text-sm">
										<option value="true">true</option>
										<option value="false">false</option>
									</select>
								{:else}
									<input
										bind:value={drafts[s.key]}
										class="w-56 rounded-md border border-slate-300 px-2 py-1 text-sm"
									/>
								{/if}
								<button
									onclick={() => save(s)}
									disabled={savingKey === s.key}
									class="cursor-pointer rounded-md bg-slate-900 px-3 py-1 text-sm text-white hover:bg-slate-700 disabled:opacity-50"
								>
									Save
								</button>
								<button
									onclick={() => reset(s)}
									disabled={savingKey === s.key || s.is_default}
									class="cursor-pointer rounded-md border border-slate-300 px-3 py-1 text-sm text-slate-600 hover:bg-slate-50 disabled:opacity-50"
								>
									Reset to default
								</button>
							</div>
						{/each}
					</div>
				</section>
			{/if}
		{/each}
	{/if}
</main>
