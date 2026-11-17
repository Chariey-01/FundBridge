import { readJson, writeJson } from "./storage.ts";

/**
 * One Idempotency-Key per user intent. Retrying the same intent (same campaign and amount) after a
 * network error reuses its key, so the server returns the original donation instead of a second one.
 * A changed amount is a new intent and gets a new key.
 */
export function newKey(): string {
  const c = globalThis.crypto;
  if (typeof c?.randomUUID === "function") return c.randomUUID();
  // randomUUID needs a secure context; getRandomValues does not (e.g. testing over a LAN IP).
  const b = c.getRandomValues(new Uint8Array(16));
  b[6] = (b[6] & 0x0f) | 0x40;
  b[8] = (b[8] & 0x3f) | 0x80;
  const h = Array.from(b, (x) => x.toString(16).padStart(2, "0")).join("");
  return `${h.slice(0, 8)}-${h.slice(8, 12)}-${h.slice(12, 16)}-${h.slice(16, 20)}-${h.slice(20)}`;
}

const STORE = "fundbridge.intents";

export function intentKey(scope: string, fingerprint: string): string {
  const all = readJson<Record<string, string>>(STORE) ?? {};
  const id = `${scope}|${fingerprint}`;
  if (!all[id]) {
    all[id] = newKey();
    writeJson(STORE, all);
  }
  return all[id];
}

export function forgetIntent(scope: string, fingerprint: string): void {
  const all = readJson<Record<string, string>>(STORE) ?? {};
  delete all[`${scope}|${fingerprint}`];
  writeJson(STORE, all);
}
