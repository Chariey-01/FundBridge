/**
 * Money arrives as decimal strings ("1250.00"). It is never converted to a JS number: amounts are
 * compared and divided as integer cents with BigInt, and formatted by string manipulation.
 */

const AMOUNT = /^(\d{1,15})(?:\.(\d{1,2}))?$/;

/** True for a positive amount with at most two decimals, e.g. "25" or "25.50". */
export function isValidAmount(value: string): boolean {
  const m = AMOUNT.exec(value.trim());
  return m !== null && toCents(value) > 0n;
}

/** Normalises "25" or "25.5" to "25.00". Call only after isValidAmount. */
export function normaliseAmount(value: string): string {
  const m = AMOUNT.exec(value.trim());
  if (!m) throw new Error(`Not a valid amount: ${value}`);
  const whole = m[1].replace(/^0+(?=\d)/, "");
  const frac = (m[2] ?? "").padEnd(2, "0");
  return `${whole}.${frac}`;
}

export function toCents(value: string): bigint {
  const m = /^(-)?(\d+)(?:\.(\d{1,2}))?$/.exec(value.trim());
  if (!m) return 0n;
  const cents = BigInt(m[2]) * 100n + BigInt((m[3] ?? "").padEnd(2, "0") || "0");
  return m[1] ? -cents : cents;
}

/** Whole-number percentage of goal reached, clamped to 0..100 for the progress bar. */
export function percentOf(part: string, whole: string): number {
  const w = toCents(whole);
  if (w <= 0n) return 0;
  const pct = (toCents(part) * 100n) / w;
  return Number(pct > 100n ? 100n : pct < 0n ? 0n : pct);
}

function group(digits: string): string {
  return digits.replace(/\B(?=(\d{3})+(?!\d))/g, ",");
}

/** "1234567.5" + "USD" → "USD 1,234,567.50". */
export function formatMoney(amount: string, currency: string): string {
  const m = /^(-)?(\d+)(?:\.(\d+))?$/.exec(amount.trim());
  if (!m) return `${currency} ${amount}`;
  const frac = (m[3] ?? "").padEnd(2, "0").slice(0, 2);
  return `${m[1] ? "−" : ""}${currency} ${group(m[2].replace(/^0+(?=\d)/, ""))}.${frac}`;
}

export const DONATION_CURRENCIES = ["USD", "EUR", "GBP", "CAD", "AUD"] as const;
