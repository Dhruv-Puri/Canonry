// Small wording helpers shared by the screens: plurals and dates said the same way everywhere.

/** "1 issue", "3 issues"; pass the plural when it isn't just "+s". */
export function plural(n: number, one: string, many = `${one}s`): string {
  return `${n} ${n === 1 ? one : many}`;
}

/** A calendar date ("2026-09-30" or a full timestamp) as "30 Sep 2026". */
export function formatDay(iso: string | null | undefined): string {
  if (!iso) return "";
  // date-only strings are calendar days: read them in UTC so no timezone moves them
  const d = new Date(/^\d{4}-\d{2}-\d{2}$/.test(iso) ? `${iso}T00:00:00Z` : iso);
  if (Number.isNaN(d.getTime())) return iso;
  // spelled out by hand: some browsers write "Sept" for en-GB
  return `${d.getUTCDate()} ${MONTHS[d.getUTCMonth()]} ${d.getUTCFullYear()}`;
}

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/** Today as "YYYY-MM-DD" (UTC), to compare with fact validity dates. */
export function todayIso(): string {
  return new Date().toISOString().slice(0, 10);
}

/** Days from today to a "YYYY-MM-DD" date (negative when it is in the past). */
export function daysUntil(iso: string): number {
  return Math.round((Date.parse(`${iso}T00:00:00Z`) - Date.parse(`${todayIso()}T00:00:00Z`)) / 86_400_000);
}
