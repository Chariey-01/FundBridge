import type { ApiError, Donation, FundBridgeClient, PayPalReturnOutcome, StatusPresentation } from "../api/client.ts";
import { presentDonation } from "../api/client.ts";

export interface ReturnResult { outcome: PayPalReturnOutcome; donation: Donation; presentation: StatusPresentation; error?: ApiError }

const inFlight = new Map<string, Promise<ReturnResult>>();

/** Re-check delays after the first answer; tests shorten them. */
export const returnPolling = { delaysMs: [1500, 3000] };

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

/**
 * Runs once per donation per page load (React may mount twice in development): asks the server to
 * capture, reconciles if ambiguous, re-reads the donation, then re-checks a few times. The outcome is
 * "confirmed" only when GET /donations/{id} says "completed".
 */
export function confirmReturn(client: FundBridgeClient, donationId: string, delaysMs: number[] = returnPolling.delaysMs): Promise<ReturnResult> {
  const existing = inFlight.get(donationId);
  if (existing) return existing;
  const run = (async () => {
    let result: ReturnResult = await client.completePayPalReturn(donationId);
    for (const delay of delaysMs) {
      if (result.outcome === "confirmed" || result.outcome === "failed" || result.outcome === "not_approved" || result.presentation.final) break;
      await sleep(delay);
      const donation = await client.getDonation(donationId);
      result = donation.status === "completed"
        ? { outcome: "confirmed", donation, presentation: presentDonation(donation.status) }
        : { ...result, donation, presentation: presentDonation(donation.status) };
    }
    return result;
  })();
  inFlight.set(donationId, run);
  run.finally(() => setTimeout(() => inFlight.delete(donationId), 0)).catch(() => undefined);
  return run;
}
