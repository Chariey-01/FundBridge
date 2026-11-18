/**
 * Links that leave FundBridge (PayPal checkout) come from the server. Only https URLs are used, so a
 * malformed or malicious value (for example `javascript:`) can never become a clickable link.
 */
export function safeHttpsUrl(value: string | null | undefined): string | null {
  if (!value) return null;
  try {
    const url = new URL(value);
    return url.protocol === "https:" && url.hostname ? url.href : null;
  } catch {
    return null;
  }
}
