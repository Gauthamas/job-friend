<script lang="ts">
	import { page } from '$app/state';
	import RoleCard from '$lib/components/RoleCard.svelte';
	import { savedInventoryStore } from '$lib/savedInventoryStore.svelte';
	import type { RoleViewModel, SavedRole, UnitRowActions } from '$lib/types';

	const inventoryId = $derived(Number(page.params.id));

	$effect(() => {
		savedInventoryStore.load(inventoryId);
	});

	function toViewModel(role: SavedRole): RoleViewModel {
		return {
			key: role.id,
			company: role.company,
			title: role.title,
			start: role.start_date ?? '',
			end: role.end_date ?? '',
			discardedAt: role.discarded_at,
			units: role.units.map((u) => ({
				key: u.id,
				text: u.text,
				source: u.source,
				context: u.context,
				contribution: u.contribution,
				outcome: u.outcome,
				skillsJson: u.skills_json,
				discardedAt: u.discarded_at
			}))
		};
	}

	function actionsFor(roleId: number): UnitRowActions {
		return {
			onChange: (unitKey, patch) => savedInventoryStore.recordEdit(roleId, unitKey as number, patch),
			split: (unitKey, splitAt) => savedInventoryStore.splitUnit(roleId, unitKey as number, splitAt),
			merge: (unitKey, otherKey) => savedInventoryStore.mergeUnits(roleId, unitKey as number, otherKey as number),
			delete: (unitKey) => savedInventoryStore.deleteUnit(roleId, unitKey as number),
			discard: (unitKey) => savedInventoryStore.discardUnit(roleId, unitKey as number),
			restore: (unitKey) => savedInventoryStore.restoreUnit(roleId, unitKey as number)
		};
	}

	function isPending(roleId: number): boolean {
		const role = savedInventoryStore.inventory?.roles.find((r) => r.id === roleId);
		if (!role) return false;
		return role.units.some((u) => savedInventoryStore.pending[u.id]) || !!savedInventoryStore.pending[-roleId];
	}

	let addingRoleOpen = $state(false);
	let newCompany = $state('');
	let newTitle = $state('');
	let newStart = $state('');
	let newEnd = $state('');
	let newPresent = $state(false);

	async function submitAddRole() {
		if (!newCompany.trim() || !newTitle.trim()) return;
		await savedInventoryStore.addRole({
			company: newCompany.trim(),
			title: newTitle.trim(),
			start_date: newStart.trim(),
			end_date: newPresent ? '' : newEnd.trim()
		});
		if (!savedInventoryStore.addRoleError) {
			newCompany = '';
			newTitle = '';
			newStart = '';
			newEnd = '';
			newPresent = false;
			addingRoleOpen = false;
		}
	}
</script>

<main class="mx-auto max-w-3xl p-8 pb-24">
	<a href="/inventories" class="text-sm text-slate-500 underline">← All inventories</a>

	{#if savedInventoryStore.loading}
		<p class="mt-6 text-slate-500">Loading…</p>
	{:else if !savedInventoryStore.inventory}
		<p class="mt-6 text-sm text-red-600">{savedInventoryStore.error ?? 'Inventory not found.'}</p>
	{:else}
		<h1 class="mt-2 text-2xl font-semibold text-slate-900">{savedInventoryStore.inventory.name}</h1>
		<p class="mt-1 text-sm text-slate-500">
			Edit text and enrichment below, then Save. Split, merge, delete and add-unit apply immediately.
		</p>

		<label class="mt-3 flex items-center gap-2 text-sm text-slate-500">
			<input
				type="checkbox"
				checked={savedInventoryStore.showDiscarded}
				onchange={() => savedInventoryStore.toggleShowDiscarded()}
			/>
			Show discarded
		</label>

		{#if savedInventoryStore.error}
			<p class="mt-3 text-sm text-red-600">{savedInventoryStore.error}</p>
		{/if}

		<div class="mt-6 space-y-6">
			{#each savedInventoryStore.inventory.roles as role (role.id)}
				<RoleCard
					role={toViewModel(role)}
					disabled={isPending(role.id)}
					headerEditable={false}
					actions={actionsFor(role.id)}
					onAddUnit={(text) => savedInventoryStore.addUnit(role.id, text)}
					addDisabled={!!savedInventoryStore.pending[-role.id]}
					onDiscardRole={() => savedInventoryStore.discardRole(role.id)}
					onRestoreRole={() => savedInventoryStore.restoreRole(role.id)}
				/>
			{/each}
		</div>

		<div class="mt-6">
			{#if addingRoleOpen}
				<div class="rounded-lg border border-slate-300 p-4">
					<div class="grid gap-2">
						<input class="rounded border border-slate-200 px-2 py-1 text-sm" placeholder="Company" bind:value={newCompany} />
						<input class="rounded border border-slate-200 px-2 py-1 text-sm" placeholder="Title" bind:value={newTitle} />
						<div class="flex items-center gap-3">
							<input class="min-w-[7rem] flex-1 rounded border border-slate-200 px-2 py-1 text-sm" placeholder="Start" bind:value={newStart} />
							<span class="text-slate-400">–</span>
							<input
								class="min-w-[7rem] flex-1 rounded border border-slate-200 px-2 py-1 text-sm disabled:bg-slate-50"
								placeholder="End"
								bind:value={newEnd}
								disabled={newPresent}
							/>
							<label class="flex items-center gap-1 text-xs text-slate-500">
								<input type="checkbox" bind:checked={newPresent} />
								Present
							</label>
						</div>
					</div>
					{#if savedInventoryStore.addRoleError}
						<p class="mt-2 text-sm text-red-600">{savedInventoryStore.addRoleError}</p>
					{/if}
					<div class="mt-3 flex gap-2">
						<button
							class="cursor-pointer rounded bg-slate-900 px-3 py-1.5 text-sm text-white disabled:cursor-not-allowed disabled:opacity-50"
							disabled={savedInventoryStore.addingRole || !newCompany.trim() || !newTitle.trim()}
							onclick={submitAddRole}
						>
							{savedInventoryStore.addingRole ? 'Saving…' : 'Save role'}
						</button>
						<button class="cursor-pointer text-sm text-slate-500" onclick={() => (addingRoleOpen = false)}>Cancel</button>
					</div>
				</div>
			{:else}
				<button
					class="cursor-pointer rounded border border-slate-300 px-3 py-1.5 text-sm hover:bg-slate-50"
					onclick={() => (addingRoleOpen = true)}
				>
					+ Add role
				</button>
			{/if}
		</div>

		<div class="fixed inset-x-0 bottom-0 border-t border-slate-200 bg-white p-4">
			<div class="mx-auto max-w-3xl">
				<button
					class="cursor-pointer rounded-md bg-slate-900 px-5 py-2.5 text-white disabled:cursor-not-allowed disabled:opacity-50"
					disabled={!savedInventoryStore.hasPendingEdits || savedInventoryStore.saving}
					onclick={() => savedInventoryStore.saveAll()}
				>
					{savedInventoryStore.saving ? 'Saving…' : 'Save'}
				</button>
			</div>
		</div>
	{/if}
</main>
