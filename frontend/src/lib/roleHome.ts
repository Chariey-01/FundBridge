import type { Role } from "../api/client.ts";

export function roleHome(role: Role): string {
  switch (role) {
    case "creator": return "/creator";
    case "beneficiary": return "/beneficiary";
    case "reviewer":
    case "admin": return "/review";
    case "agent": return "/agent/onboard";
    default: return "/campaigns";
  }
}

/**
 * Only same-site paths are accepted as a post-sign-in destination. Backslashes and control characters
 * are refused because browsers normalise "/\\evil.example" to the off-site "//evil.example".
 */
export function safeNext(next: string | null): string | null {
  if (!next || !next.startsWith("/") || next.startsWith("//")) return null;
  // eslint-disable-next-line no-control-regex -- control characters are exactly what is being refused
  return /[\\\u0000-\u001f\u007f]/.test(next) ? null : next;
}
