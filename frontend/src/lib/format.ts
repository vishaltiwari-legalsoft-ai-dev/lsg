/*
 * Presentation-only formatting. Month names are spelled here rather than
 * through Intl so every browser renders "9 Sep 2026" (en-GB ICU now says
 * "Sept") and server and client never disagree.
 */

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const DAY_MS = 86_400_000;

function toDate(iso: string): Date {
  // A bare date ("2026-08-12") is a calendar day, not midnight UTC.
  return /^\d{4}-\d{2}-\d{2}$/.test(iso) ? new Date(`${iso}T12:00:00`) : new Date(iso);
}

/** "9 Sep 2026" */
export function formatDate(iso: string): string {
  const d = toDate(iso);
  return `${d.getDate()} ${MONTHS[d.getMonth()]} ${d.getFullYear()}`;
}

/** "9 Sep" */
export function formatDayMonth(iso: string): string {
  const d = toDate(iso);
  return `${d.getDate()} ${MONTHS[d.getMonth()]}`;
}

/** "9 Sep, 14:22" */
export function formatDateTime(iso: string): string {
  const d = toDate(iso);
  const hh = String(d.getHours()).padStart(2, "0");
  const mm = String(d.getMinutes()).padStart(2, "0");
  return `${d.getDate()} ${MONTHS[d.getMonth()]}, ${hh}:${mm}`;
}

/** Whole calendar days between a moment and now (never negative). */
export function daysSince(iso: string, now: Date = new Date()): number {
  const then = toDate(iso);
  const a = Date.UTC(then.getFullYear(), then.getMonth(), then.getDate());
  const b = Date.UTC(now.getFullYear(), now.getMonth(), now.getDate());
  return Math.max(0, Math.round((b - a) / DAY_MS));
}

/** "today", "yesterday", "12 days ago" */
export function relativeDays(iso: string, now: Date = new Date()): string {
  const days = daysSince(iso, now);
  if (days === 0) return "today";
  if (days === 1) return "yesterday";
  return `${days} days ago`;
}

const integer = new Intl.NumberFormat("en-US", { maximumFractionDigits: 0 });

/** "1,204" */
export function formatCount(n: number): string {
  return integer.format(n);
}

/** Confidence and weights as the engine writes them: "0.95". */
export function formatDecimal(n: number): string {
  return n.toFixed(2);
}

/** "92%" */
export function formatPercent(part: number, whole: number): string {
  if (whole === 0) return "0%";
  return `${Math.round((part / whole) * 100)}%`;
}

/** "Atlanta, GA" — or null when neither is known. */
export function formatPlace(city: string | null, state: string | null): string | null {
  if (city && state) return `${city}, ${state}`;
  return city ?? state ?? null;
}

/** Local YYYY-MM-DD for <input type="date">. */
export function toDateInputValue(d: Date): string {
  const mm = String(d.getMonth() + 1).padStart(2, "0");
  const dd = String(d.getDate()).padStart(2, "0");
  return `${d.getFullYear()}-${mm}-${dd}`;
}

/** Path and query of a URL, for compact citations: "/careers". */
export function urlPath(url: string): string {
  try {
    const u = new URL(url);
    return `${u.pathname}${u.search}` || "/";
  } catch {
    return url;
  }
}
