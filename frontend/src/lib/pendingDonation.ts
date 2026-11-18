import { readJson, remove, writeJson } from "./storage.ts";
import { safeHttpsUrl } from "./urls.ts";

/**
 * PayPal's return URL is fixed when the order is created, before the donation id exists, so the id
 * is kept here for the return page. PayPal's query parameters are never used as evidence.
 */
export interface PendingDonation { donationId: string; campaignId: string; amount: string; currency: string; approvalUrl: string | null }

const KEY = "fundbridge.pendingDonation";
export function loadPendingDonation(): PendingDonation | null {
  const p = readJson<PendingDonation>(KEY);
  return p && typeof p.donationId === "string" ? { ...p, approvalUrl: safeHttpsUrl(p.approvalUrl) } : null;
}
export const savePendingDonation = (p: PendingDonation) => writeJson(KEY, p);
export const clearPendingDonation = () => remove(KEY);
