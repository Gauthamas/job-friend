<script lang="ts">
	import { page } from '$app/state';

	const jobId = $derived(Number(page.params.id));
</script>

<main class="mx-auto max-w-3xl p-8">
	<a href={`/jobs/${jobId}/enrichment`} class="text-sm text-slate-500 underline">← Back to enrichment</a>
	<h1 class="mt-2 text-2xl font-semibold text-slate-900">Coming soon</h1>
	<p class="mt-1 text-sm text-slate-500">
		Pair building and thread discovery are not built yet -- this is as far as milestone 2 goes.
	</p>
</main>
