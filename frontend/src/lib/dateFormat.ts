const MONTH_NAMES = [
	'January', 'February', 'March', 'April', 'May', 'June',
	'July', 'August', 'September', 'October', 'November', 'December'
];

// Role start/end dates are stored as "YYYY-MM" (normalize_month on the
// backend). Formats that as "Month YYYY" for display; anything that isn't
// a plain "YYYY-MM" (empty, "Present", a raw value not yet normalized)
// passes through unchanged rather than showing something broken.
export function formatMonthYear(yearMonth: string | null | undefined): string {
	if (!yearMonth) return '';
	const match = /^(\d{4})-(\d{2})$/.exec(yearMonth);
	if (!match) return yearMonth;
	const monthIndex = Number(match[2]) - 1;
	if (monthIndex < 0 || monthIndex > 11) return yearMonth;
	return `${MONTH_NAMES[monthIndex]} ${match[1]}`;
}

// Reverse of formatMonthYear, for editable fields that display "Month
// YYYY" but must store "YYYY-MM" (what's already committed, and what the
// backend's own normalizer produces). Returns null if it doesn't parse as
// "<month name> <year>" — the caller falls back to storing the raw text
// rather than losing the edit.
export function parseMonthYear(display: string): string | null {
	const match = /^([A-Za-z]+)\s+(\d{4})$/.exec(display.trim());
	if (!match) return null;
	const monthIndex = MONTH_NAMES.findIndex((m) => m.toLowerCase() === match[1].toLowerCase());
	if (monthIndex === -1) return null;
	return `${match[2]}-${String(monthIndex + 1).padStart(2, '0')}`;
}
