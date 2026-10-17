<script lang="ts">
	import { goto } from '$app/navigation';
	import { page } from '$app/state';
	import { createJob } from '$lib/api';

	const flowId = $derived(Number(page.params.id));

	let title = $state('');
	let submitting = $state(false);
	let error = $state<string | null>(null);

	// §3.1: job creation is now just a heading -- the JD screen (on the job
	// page itself) handles extraction once the job exists.
	async function create() {
		if (!title.trim()) return;
		submitting = true;
		error = null;
		try {
			const result = await createJob(flowId, title.trim());
			goto(`/jobs/${result.job.id}`);
		} catch (e) {
			error = e instanceof Error ? e.message : 'Failed to create the job.';
			submitting = false;
		}
	}
</script>

<main class="mx-auto max-w-2xl p-8">
	<h1 class="text-2xl font-semibold text-slate-900">New job</h1>
	<p class="mt-1 text-sm text-slate-500">Give it a name -- you will paste the job description on the next screen.</p>

	<div class="mt-6 flex flex-col gap-3">
		<input
			class="rounded border border-slate-200 px-3 py-2 text-sm disabled:bg-slate-50"
			placeholder="Job title"
			bind:value={title}
			disabled={submitting}
			onkeydown={(e) => e.key === 'Enter' && create()}
		/>

		{#if error}
			<p class="text-sm text-red-600">{error}</p>
		{/if}

		<button
			class="cursor-pointer self-start rounded-md bg-slate-900 px-4 py-2 text-sm text-white hover:bg-slate-700 disabled:cursor-not-allowed disabled:opacity-50"
			disabled={submitting || !title.trim()}
			onclick={create}
		>
			{submitting ? 'Creating…' : 'Create'}
		</button>
	</div>
</main>
