/**
 * Integration examples for the web frontend: framework-agnostic and type-checked against the client.
 * They show how each screen moves through loading, pending, failure and success, and where the
 * server is the only authority. Adapt the view models to the UI framework; keep the rules.
 */

import type { CampaignDraft } from "./ai-messaging.types.ts";
import {
  ApiError,
  type Campaign,
  type Donation,
  FundBridgeClient,
  type Payout,
  type PayPalReturnOutcome,
  type StatusPresentation,
  channelModes,
  presentPayout,
} from "./fundbridge-client.ts";

// ------------------------------------------------------------------ async state for every screen

export type AsyncState<T> =
  | { state: "idle" }
  | { state: "loading" }
  | { state: "success"; data: T }
  | { state: "error"; error: ApiError; retryable: boolean };

export async function load<T>(fn: () => Promise<T>): Promise<AsyncState<T>> {
  try {
    return { state: "success", data: await fn() };
  } catch (e) {
    if (!(e instanceof ApiError)) throw e;
    const retryable = e.status === 429 || e.status === 502 || e.status === 503;
    return { state: "error", error: e, retryable };
  }
}

/** A user-facing message for an error. Always include the request ID for support on 5xx. */
export function errorMessage(error: ApiError): string {
  if (error.code === "RATE_LIMITED") return `Too many attempts. Try again in ${error.retryAfterSeconds ?? 60} seconds.`;
  if (error.sessionInvalid) return "Your session ended. Please sign in again.";
  if (error.status >= 500) return `Something went wrong (reference ${error.requestId ?? "unknown"}).`;
  return error.message;
}

// ------------------------------------------------------------------ donation: PayPal return page

export interface DonationReturnView {
  outcome: PayPalReturnOutcome;
  presentation: StatusPresentation;
  donation: Donation;
  /** What the page offers next; "Try again" never creates a second donation (same donation id). */
  actions: Array<"view_campaign" | "check_again" | "contact_support" | "return_to_paypal" | "donate_again">;
}

const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

/**
 * The return page. Success is shown only for outcome "confirmed". While the server still says pending,
 * re-check a few times (the webhook or reconciliation may complete it), then show "pending" honestly.
 */
export async function donationReturnPage(client: FundBridgeClient, donationId: string, approvalUrl?: string,
  pollDelaysMs: number[] = [2000, 4000, 8000]): Promise<DonationReturnView> {
  let result = await client.completePayPalReturn(donationId);
  for (const delay of pollDelaysMs) {
    if (result.outcome === "confirmed" || result.outcome === "failed" || result.outcome === "not_approved"
        || result.presentation.final) break;
    await sleep(delay);
    const donation = await client.getDonation(donationId);
    if (donation.status === "completed") result = { ...result, outcome: "confirmed", donation, presentation: { label: "Donation confirmed", tone: "success", final: true } };
  }
  const actions: DonationReturnView["actions"] =
    result.outcome === "confirmed" ? ["view_campaign"]
    : result.outcome === "failed" ? ["donate_again", "view_campaign"]  // a new donation (new idempotency key)
    : result.outcome === "not_approved" && approvalUrl ? ["return_to_paypal", "check_again"]
    : result.outcome === "needs_review" ? ["contact_support"]
    : ["check_again"];
  return { outcome: result.outcome, presentation: result.presentation, donation: result.donation, actions };
}

// ------------------------------------------------------------------ payouts: never "paid" because "approved"

export function payoutRow(payout: Payout): { amount: string; label: string; tone: StatusPresentation["tone"] } {
  const p = presentPayout(payout.status);
  return { amount: `${payout.currency} ${payout.amount}`, label: p.label, tone: p.tone };
}

// ------------------------------------------------------------------ AI: optional, reviewable, never blocking

export interface DraftSuggestion { draft: CampaignDraft; label: string; warnings: string[] }

/** Returns a suggestion to load into the editable form, or null: the manual form keeps working either way. */
export async function suggestDraft(client: FundBridgeClient, storyNotes: string): Promise<DraftSuggestion | null> {
  try {
    const { draft, meta } = await client.draftCampaign({ story_notes: storyNotes, language: "en" });
    const label = meta.ai_generated ? "AI suggestion: check every detail before saving"
      : "Template suggestion (AI unavailable): check every detail before saving";
    return { draft, label, warnings: draft.warnings };
  } catch {
    return null; // 401, 429, 503 or a network error: hide the suggestion, never the form
  }
}

/** Plain keyword search is the baseline; AI search is used only when the server says it works. */
export async function searchCampaigns(client: FundBridgeClient, query: string): Promise<{ campaigns: Array<Pick<Campaign, "id" | "title">>; via: "ai" | "keyword" }> {
  try {
    const status = await client.aiStatus();
    if (status.mode === "live" && (status.model_verified || !status.last_error)) {
      const { result, meta } = await client.aiSearch({ query });
      return { campaigns: result.results.map((c) => ({ id: c.id, title: c.title })), via: meta.ai_generated ? "ai" : "keyword" };
    }
  } catch {
    // fall through to the plain search
  }
  return { campaigns: await client.listCampaigns({ q: query }), via: "keyword" };
}

// ------------------------------------------------------------------ feature phones

/** Banner text for any page that mentions SMS, USSD or payouts. Shown whenever a channel is not live. */
export async function channelBanner(client: FundBridgeClient): Promise<string[]> {
  const [status, config] = await Promise.all([client.integrationStatus(), client.publicConfig()]);
  const modes = channelModes(status, config.payouts.provider);
  return Object.values(modes).filter((m) => m.mode !== "live").map((m) => m.label);
}

/** One step of the demo phone simulator. The transcript always carries the server's simulation notice. */
export async function simulatorStep(client: FundBridgeClient, phone: string, typedSoFar: string) {
  const { reply, meta } = await client.simulateUssd(phone, typedSoFar);
  return { screen: reply.text, sessionEnded: reply.session_ended, badge: "SIMULATED", notice: meta.notice };
}

// ------------------------------------------------------------------ reviewer: stale-review protection

export async function verifyBeneficiary(client: FundBridgeClient, profileId: string, revision: string) {
  try {
    return { ok: true as const, profile: await client.decideVerification(profileId, "verify", revision) };
  } catch (e) {
    if (e instanceof ApiError && e.code === "PROFILE_CHANGED") {
      return { ok: false as const, reload: true, message: "This profile changed after you opened it. Review it again." };
    }
    throw e;
  }
}
