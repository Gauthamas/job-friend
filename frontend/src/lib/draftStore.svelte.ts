import { createInventoryFromFile, createInventoryFromText } from './api';
import type {
	CommitRequestPayload,
	DraftRole,
	DraftUnit,
	InventoryStreamEvent,
	StructuringStatus,
	UnitSavePatch
} from './types';

let nextClientId = 0;
function freshId(): string {
	nextClientId += 1;
	return `u${nextClientId}`;
}

function makeUnit(text: string, source: DraftUnit['source']): DraftUnit {
	return { clientId: freshId(), text, source, context: null, contribution: null, outcome: null, skillsJson: null };
}

const STORAGE_KEY = 'job-friend-draft-v1';

class DraftStore {
	inventoryId = $state<number | null>(null);
	status = $state<StructuringStatus>('idle');
	errorMessage = $state<string | null>(null);

	// All roles from the current structuring run, in server order, regardless
	// of section — role_index (server-assigned) is the stable key, not array
	// position, since roles/excludedRoles below are filtered views of this.
	allRoles = $state<DraftRole[]>([]);

	roles = $derived(this.allRoles.filter((r) => r.section === 'work'));
	excludedRoles = $derived(this.allRoles.filter((r) => r.section !== 'work'));

	constructor() {
		this._restore();
	}

	// A dev-mode page reload (e.g. Vite's HMR client hard-reloading after a
	// backgrounded tab's websocket drops — this is what actually causes "no
	// draft loaded" on switching tabs, not the switch itself) would otherwise
	// wipe this in-memory store entirely. Persisting to sessionStorage on
	// every change survives that; a reload mid-stream still loses the live
	// connection, so that case is surfaced as an error rather than a silent
	// reset (see _restore).
	private _persist() {
		if (typeof sessionStorage === 'undefined') return;
		try {
			sessionStorage.setItem(
				STORAGE_KEY,
				JSON.stringify({
					inventoryId: this.inventoryId,
					status: this.status,
					errorMessage: this.errorMessage,
					allRoles: this.allRoles
				})
			);
		} catch {
			// Storage can throw (private browsing, quota) — losing persistence
			// isn't worth failing the actual edit over.
		}
	}

	private _restore() {
		if (typeof sessionStorage === 'undefined') return;
		try {
			const raw = sessionStorage.getItem(STORAGE_KEY);
			if (!raw) return;
			const data = JSON.parse(raw);
			this.inventoryId = data.inventoryId ?? null;
			this.allRoles = data.allRoles ?? [];
			if (data.status === 'structuring') {
				// The fetch/SSE connection was tied to the old page load and is
				// gone — there's no way to resume it, so don't leave the UI
				// stuck showing "Generating..." forever.
				this.status = 'error';
				this.errorMessage =
					'Connection to the server was lost (the page reloaded while generating). ' +
					'What arrived before that is kept below.';
			} else {
				this.status = data.status ?? 'idle';
				this.errorMessage = data.errorMessage ?? null;
			}
		} catch {
			// Malformed/missing storage — start clean.
		}
	}

	private getRole(roleIndex: number): DraftRole {
		const role = this.allRoles.find((r) => r.roleIndex === roleIndex);
		if (!role) throw new Error(`No draft role with roleIndex ${roleIndex}`);
		return role;
	}

	private getUnit(roleIndex: number, unitKey: string): { units: DraftUnit[]; index: number; unit: DraftUnit } {
		const units = this.getRole(roleIndex).units;
		const index = units.findIndex((u) => u.clientId === unitKey);
		if (index === -1) throw new Error(`No draft unit with clientId ${unitKey}`);
		return { units, index, unit: units[index] };
	}

	async startStructuring(
		name: string,
		source: { mode: 'text'; text: string } | { mode: 'file'; file: File }
	) {
		this.reset();
		this.status = 'structuring';
		this._persist();
		const onEvent = (event: InventoryStreamEvent) => this.handleEvent(event);
		try {
			if (source.mode === 'text') {
				await createInventoryFromText(name, source.text, onEvent);
			} else {
				await createInventoryFromFile(name, source.file, onEvent);
			}
		} catch (e) {
			this.status = 'error';
			this.errorMessage = e instanceof Error ? e.message : 'Something went wrong.';
			this._persist();
		}
	}

	private handleEvent(event: InventoryStreamEvent) {
		switch (event.event) {
			case 'role_meta':
				this.allRoles.push({
					roleIndex: event.role_index,
					company: event.company,
					title: event.title,
					start: event.start,
					end: event.end,
					section: event.section,
					units: [],
					streaming: true
				});
				break;

			case 'bullet':
				this.getRole(event.role_index).units.push(makeUnit(event.text, 'parsed'));
				break;

			case 'role_done':
				this.getRole(event.role_index).streaming = false;
				break;

			case 'done':
				this.inventoryId = event.inventory_id;
				// Reconcile with the authoritative final draft. Live events above
				// are best-effort UI only; this is the source of truth, and
				// editing only unlocks once this has landed (status = 'ready').
				this.allRoles = event.draft.roles.map((role, roleIndex) => ({
					roleIndex,
					company: role.company,
					title: role.title,
					start: role.start,
					end: role.end,
					section: role.section,
					units: role.bullets.map((b) => makeUnit(b, 'parsed')),
					streaming: false
				}));
				this.status = 'ready';
				break;

			case 'error':
				this.status = 'error';
				this.errorMessage = event.message;
				break;
		}
		this._persist();
	}

	editRoleHeader(roleIndex: number, patch: { company: string; title: string; start: string; end: string }) {
		const role = this.getRole(roleIndex);
		role.company = patch.company;
		role.title = patch.title;
		role.start = patch.start;
		role.end = patch.end;
		this._persist();
	}

	// Misclassified role (e.g. an internship tagged "other"): move it into
	// the editable work list.
	promote(roleIndex: number) {
		this.getRole(roleIndex).section = 'work';
		this._persist();
	}

	// Covers text + enrichment in one call, matching UnitRow's single Save
	// button — mirrors savedInventoryStore.editUnit's shape even though this
	// one is a local mutation, not a network call.
	editUnit(roleIndex: number, unitKey: string, patch: UnitSavePatch) {
		const { unit } = this.getUnit(roleIndex, unitKey);
		if (unit.text !== patch.text) {
			unit.text = patch.text;
			unit.source = 'manual';
		}
		unit.context = patch.context;
		unit.contribution = patch.contribution;
		unit.outcome = patch.outcome;
		unit.skillsJson = patch.skills_json;
		this._persist();
	}

	deleteUnit(roleIndex: number, unitKey: string) {
		const { units, index } = this.getUnit(roleIndex, unitKey);
		units.splice(index, 1);
		this._persist();
	}

	addUnit(roleIndex: number, text: string = '') {
		this.getRole(roleIndex).units.push(makeUnit(text, 'manual'));
		this._persist();
	}

	// Splits one unit into two at `splitAt` (character offset into its text).
	// The split itself doesn't change wording, so both halves keep the
	// original unit's source — only a later edit would mark them 'manual'.
	splitUnit(roleIndex: number, unitKey: string, splitAt: number) {
		const { units, index, unit } = this.getUnit(roleIndex, unitKey);
		const first = unit.text.slice(0, splitAt).trim();
		const second = unit.text.slice(splitAt).trim();
		if (!first || !second) return;
		units.splice(
			index,
			1,
			{ ...unit, clientId: freshId(), text: first },
			{ ...unit, clientId: freshId(), text: second }
		);
		this._persist();
	}

	// Merges unitKey with otherKey (both must be in the same role). Merged
	// text is no longer verbatim model output, so the result is 'manual'.
	// unitKey survives (keeps its position); otherKey is removed.
	mergeUnits(roleIndex: number, unitKey: string, otherKey: string) {
		const { units, index, unit } = this.getUnit(roleIndex, unitKey);
		const otherIndex = units.findIndex((u) => u.clientId === otherKey);
		if (otherIndex === -1) return;
		const other = units[otherIndex];
		const merged: DraftUnit = { ...unit, text: `${unit.text} ${other.text}`.trim(), source: 'manual' };
		units.splice(otherIndex, 1);
		units[otherIndex < index ? index - 1 : index] = merged;
		this._persist();
	}

	toCommitPayload(): CommitRequestPayload {
		return {
			roles: this.roles.map((role, sortOrder) => ({
				company: role.company,
				title: role.title,
				start_date: role.start,
				end_date: role.end,
				sort_order: sortOrder,
				units: role.units.map((unit, unitIndex) => ({
					text: unit.text,
					source: unit.source,
					sort_order: unitIndex,
					context: unit.context,
					contribution: unit.contribution,
					outcome: unit.outcome,
					skills_json: unit.skillsJson
				}))
			}))
		};
	}

	reset() {
		this.inventoryId = null;
		this.status = 'idle';
		this.errorMessage = null;
		this.allRoles = [];
		this._persist();
	}
}

export const draftStore = new DraftStore();
