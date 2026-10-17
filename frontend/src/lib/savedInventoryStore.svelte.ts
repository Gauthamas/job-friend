import {
	addSavedUnit,
	commitInventory,
	deleteUnit as apiDeleteUnit,
	discardRole as apiDiscardRole,
	discardUnit as apiDiscardUnit,
	getInventory,
	mergeUnits as apiMergeUnits,
	patchUnit,
	restoreRole as apiRestoreRole,
	restoreUnit as apiRestoreUnit,
	splitUnit as apiSplitUnit
} from './api';
import type { InventoryDetail, SavedRole, SavedUnit, UnitSavePatch } from './types';

class SavedInventoryStore {
	inventory = $state<InventoryDetail | null>(null);
	loading = $state(false);
	error = $state<string | null>(null);
	showDiscarded = $state(false);
	addingRole = $state(false);
	addRoleError = $state<string | null>(null);

	private inventoryId: number | null = null;

	// Per-unit action state, keyed by unit id, so one unit's in-flight PATCH
	// doesn't disable controls on every other unit.
	pending = $state<Record<number, boolean>>({});

	// Text/enrichment edits are staged here as the user types — nothing
	// hits the server until saveAll(), same as the draft screen's one
	// Save-at-the-end. Split/merge/delete stay immediate (see saveAll doc).
	pendingEdits = $state<Record<number, { roleId: number; patch: UnitSavePatch }>>({});
	saving = $state(false);

	hasPendingEdits = $derived(Object.keys(this.pendingEdits).length > 0);

	private getRole(roleId: number): SavedRole {
		const role = this.inventory?.roles.find((r) => r.id === roleId);
		if (!role) throw new Error(`No role ${roleId} loaded`);
		return role;
	}

	private replaceUnit(roleId: number, unit: SavedUnit) {
		const role = this.getRole(roleId);
		const index = role.units.findIndex((u) => u.id === unit.id);
		if (index === -1) role.units.push(unit);
		else role.units[index] = unit;
		// Fresh server state just landed for this unit (e.g. a split/merge
		// changed its text) — any stale local edit based on the old text
		// would silently overwrite that if left staged.
		delete this.pendingEdits[unit.id];
	}

	private removeUnit(roleId: number, unitId: number) {
		const role = this.getRole(roleId);
		role.units = role.units.filter((u) => u.id !== unitId);
		delete this.pendingEdits[unitId]; // that unit no longer exists to save
	}

	async load(inventoryId: number) {
		this.inventoryId = inventoryId;
		this.loading = true;
		this.error = null;
		this.pendingEdits = {};
		try {
			this.inventory = await getInventory(inventoryId, this.showDiscarded);
		} catch (e) {
			this.error = e instanceof Error ? e.message : 'Failed to load inventory.';
		} finally {
			this.loading = false;
		}
	}

	async toggleShowDiscarded() {
		this.showDiscarded = !this.showDiscarded;
		if (this.inventoryId !== null) await this.load(this.inventoryId);
	}

	private async withPending(unitId: number, fn: () => Promise<void>) {
		this.pending[unitId] = true;
		try {
			await fn();
		} catch (e) {
			this.error = e instanceof Error ? e.message : 'Something went wrong.';
		} finally {
			this.pending[unitId] = false;
		}
	}

	// Stages an edit locally — no network call. UnitRow calls this on every
	// keystroke (text, context, contribution, outcome, skills together),
	// same as binding directly into draftStore. Nothing reaches the server
	// until saveAll().
	recordEdit(roleId: number, unitId: number, patch: UnitSavePatch) {
		this.pendingEdits[unitId] = { roleId, patch };
	}

	// Flushes every staged edit in one round, one PATCH per changed unit —
	// this is the editor's equivalent of the draft screen's single Save.
	async saveAll() {
		this.saving = true;
		this.error = null;
		const entries = Object.entries(this.pendingEdits);
		for (const [unitIdStr, { roleId, patch }] of entries) {
			const unitId = Number(unitIdStr);
			try {
				const updated = await patchUnit(unitId, patch);
				this.replaceUnit(roleId, updated);
				delete this.pendingEdits[unitId];
			} catch (e) {
				this.error = e instanceof Error ? e.message : `Failed to save unit ${unitId}.`;
				// Leave this one (and any not yet attempted) in pendingEdits so
				// the user can retry rather than silently losing the edit.
			}
		}
		this.saving = false;
	}

	async deleteUnit(roleId: number, unitId: number) {
		await this.withPending(unitId, async () => {
			await apiDeleteUnit(unitId);
			this.removeUnit(roleId, unitId);
		});
	}

	async splitUnit(roleId: number, unitId: number, splitAt: number) {
		await this.withPending(unitId, async () => {
			const result = await apiSplitUnit(unitId, splitAt);
			this.replaceUnit(roleId, result.original);
			this.replaceUnit(roleId, result.new_unit);
		});
	}

	// unitId is always the unit the user picked as the merge destination
	// (it survives); otherUnitId is absorbed into it and soft-deleted.
	async mergeUnits(roleId: number, unitId: number, otherUnitId: number) {
		await this.withPending(unitId, async () => {
			const result = await apiMergeUnits(unitId, otherUnitId);
			this.replaceUnit(roleId, result.survivor);
			this.removeUnit(roleId, result.merged_unit_id);
		});
	}

	async addUnit(roleId: number, text: string) {
		// Reuses the unit-id-keyed pending map with a negative key (no real
		// unit id is ever negative) rather than a second pending-state shape.
		await this.withPending(-roleId, async () => {
			const unit = await addSavedUnit(roleId, { text });
			this.replaceUnit(roleId, unit);
		});
	}

	// Reversible, unlike delete -- a full reload picks up whether the
	// affected role/unit should still be visible under the current
	// showDiscarded toggle (a role/unit can disappear from the list
	// entirely, which local patching can't express as cleanly).
	async discardUnit(roleId: number, unitId: number) {
		await this.withPending(unitId, async () => {
			await apiDiscardUnit(unitId);
			if (this.inventoryId !== null) await this.load(this.inventoryId);
		});
	}

	async restoreUnit(roleId: number, unitId: number) {
		await this.withPending(unitId, async () => {
			await apiRestoreUnit(unitId);
			if (this.inventoryId !== null) await this.load(this.inventoryId);
		});
	}

	async discardRole(roleId: number) {
		await this.withPending(-roleId, async () => {
			await apiDiscardRole(roleId);
			if (this.inventoryId !== null) await this.load(this.inventoryId);
		});
	}

	async restoreRole(roleId: number) {
		await this.withPending(-roleId, async () => {
			await apiRestoreRole(roleId);
			if (this.inventoryId !== null) await this.load(this.inventoryId);
		});
	}

	// Reuses the exact commit path resume import uses (POST .../commit),
	// with one role and no units -- units are added afterward through the
	// existing add-unit flow. No model call either way.
	async addRole(payload: { company: string; title: string; start_date: string; end_date: string }) {
		if (this.inventoryId === null) return;
		this.addingRole = true;
		this.addRoleError = null;
		try {
			const maxSortOrder = (this.inventory?.roles ?? []).reduce((m, r) => Math.max(m, r.sort_order), -1);
			await commitInventory(this.inventoryId, {
				roles: [{ ...payload, sort_order: maxSortOrder + 1, units: [] }]
			});
			await this.load(this.inventoryId);
		} catch (e) {
			this.addRoleError = e instanceof Error ? e.message : 'Failed to add role.';
		} finally {
			this.addingRole = false;
		}
	}
}

export const savedInventoryStore = new SavedInventoryStore();
