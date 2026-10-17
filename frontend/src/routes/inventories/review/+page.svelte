<script lang="ts">
	import { goto } from '$app/navigation';
	import { commitInventory } from '$lib/api';
	import RoleCard from '$lib/components/RoleCard.svelte';
	import { draftStore } from '$lib/draftStore.svelte';
	import type { CommitResponse, DraftRole, RoleViewModel, UnitRowActions } from '$lib/types';

	let saving = $state(false);
	let saveError = $state<string | null>(null);
	let saved = $state<CommitResponse | null>(null);
	let excludedOpen = $state(false);

	// Editing/saving/promoting only unlock once the authoritative "done"
	// event has landed. While actively streaming, everything is read-only —
	// the live roles/bullets are a preview, not yet safe to edit.
	let readonly = $derived(draftStore.status === 'structuring');
	let canSave = $derived(!readonly && draftStore.inventoryId !== null && !saving);

	function toViewModel(role: DraftRole): RoleViewModel {
		return {
			key: role.roleIndex,
			company: role.company,
			title: role.title,
			start: role.start,
			end: role.end,
			units: role.units.map((u) => ({
				key: u.clientId,
				text: u.text,
				source: u.source,
				context: u.context,
				contribution: u.contribution,
				outcome: u.outcome,
				skillsJson: u.skillsJson,
				streaming: role.streaming
			}))
		};
	}

	function actionsFor(roleIndex: number): UnitRowActions {
		return {
			onChange: (unitKey, patch) => draftStore.editUnit(roleIndex, unitKey as string, patch),
			split: (unitKey, splitAt) => draftStore.splitUnit(roleIndex, unitKey as string, splitAt),
			merge: (unitKey, otherKey) => draftStore.mergeUnits(roleIndex, unitKey as string, otherKey as string),
			delete: (unitKey) => draftStore.deleteUnit(roleIndex, unitKey as string)
		};
	}

	async function save() {
		if (draftStore.inventoryId === null) return;
		saveError = null;
		saving = true;
		try {
			saved = await commitInventory(draftStore.inventoryId, draftStore.toCommitPayload());
		} catch (e) {
			saveError = e instanceof Error ? e.message : 'Something went wrong saving the inventory.';
		} finally {
			saving = false;
		}
	}

	function startAnother() {
		draftStore.reset();
		goto('/inventories/new');
	}
</script>

<main class="mx-auto max-w-3xl p-8 pb-24">
	<h1 class="text-2xl font-semibold text-slate-900">Review your inventory</h1>

	{#if draftStore.status === 'idle'}
		<p class="mt-4 text-slate-600">
			No draft loaded. <a class="underline" href="/inventories/new">Start an import</a>.
		</p>
	{:else if saved}
		<div class="mt-6 rounded-lg border border-emerald-300 bg-emerald-50 p-6">
			<p class="font-medium text-emerald-900">
				Saved {saved.roles.length} role{saved.roles.length === 1 ? '' : 's'} and
				{saved.roles.reduce((n, r) => n + r.units.length, 0)} units to inventory #{saved.inventory_id}.
			</p>
			<div class="mt-4 flex gap-2">
				<a
					href="/inventories/{saved.inventory_id}/edit"
					class="cursor-pointer rounded bg-slate-900 px-4 py-2 text-white hover:bg-slate-700"
				>
					Open in editor
				</a>
				<button
					class="cursor-pointer rounded border border-slate-300 px-4 py-2 hover:bg-slate-50"
					onclick={startAnother}
				>
					Import another resume
				</button>
			</div>
		</div>
	{:else}
		{#if draftStore.status === 'structuring'}
			<p class="mt-1 text-slate-600">
				Structuring your resume — roles and bullets appear below as they are generated.
			</p>
		{:else if draftStore.status === 'error'}
			<div class="mt-4 rounded-md border border-red-300 bg-red-50 p-3 text-sm text-red-700">
				{draftStore.errorMessage}. What arrived before the error is kept below — edit and save it,
				or <a class="underline" href="/inventories/new">start over</a>.
			</div>
		{:else}
			<p class="mt-1 text-slate-600">
				Edit, split, merge, delete or add bullets below. Nothing is saved until you click Save.
			</p>
		{/if}

		<div class="mt-6 space-y-6">
			{#each draftStore.roles as role (role.roleIndex)}
				<RoleCard
					role={toViewModel(role)}
					disabled={readonly}
					headerEditable={true}
					onSaveHeader={(patch) => draftStore.editRoleHeader(role.roleIndex, patch)}
					actions={actionsFor(role.roleIndex)}
					onAddUnit={(text) => draftStore.addUnit(role.roleIndex, text)}
					addDisabled={readonly}
				/>
			{/each}
		</div>

		{#if draftStore.excludedRoles.length > 0}
			<div class="mt-6">
				<button class="cursor-pointer text-sm text-slate-500 underline" onclick={() => (excludedOpen = !excludedOpen)}>
					{excludedOpen ? 'Hide' : 'Show'} {draftStore.excludedRoles.length} excluded (education / other)
				</button>
				{#if excludedOpen}
					<div class="mt-3 space-y-3">
						{#each draftStore.excludedRoles as role (role.roleIndex)}
							<div class="rounded-md border border-slate-200 bg-slate-50 p-3">
								<div class="flex items-center justify-between gap-2">
									<div>
										<span class="font-medium">{role.company}</span>
										<span class="text-slate-500"> — {role.title}</span>
										<span class="ml-2 rounded bg-slate-200 px-1.5 py-0.5 text-xs text-slate-600">
											{role.section}
										</span>
									</div>
									<button
										class="shrink-0 cursor-pointer rounded border border-slate-300 px-2 py-1 text-xs hover:bg-white disabled:cursor-not-allowed disabled:opacity-50"
										disabled={readonly}
										onclick={() => draftStore.promote(role.roleIndex)}
									>
										Promote to work
									</button>
								</div>
								<ul class="mt-2 list-disc pl-5 text-sm text-slate-600">
									{#each role.units as unit (unit.clientId)}
										<li>{unit.text}</li>
									{/each}
								</ul>
							</div>
						{/each}
					</div>
				{/if}
			</div>
		{/if}

		{#if saveError}
			<p class="mt-4 text-sm text-red-600">{saveError}</p>
		{/if}

		<div class="fixed inset-x-0 bottom-0 border-t border-slate-200 bg-white p-4">
			<div class="mx-auto max-w-3xl">
				<button
					class="cursor-pointer rounded-md bg-slate-900 px-5 py-2.5 text-white disabled:cursor-not-allowed disabled:opacity-50"
					disabled={!canSave}
					onclick={save}
				>
					{#if draftStore.status === 'structuring'}
						Generating…
					{:else}
						{saving ? 'Saving…' : 'Save'}
					{/if}
				</button>
			</div>
		</div>
	{/if}
</main>
