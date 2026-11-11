/**
 * FundBridge API client for any web frontend (framework-agnostic, uses fetch).
 *
 * It encodes the rules a UI must follow:
 *  - Money is a decimal string; never parse it into a JS number for arithmetic.
 *  - A donation is successful only when GET /donations/{id} returns "completed". Neither a PayPal
 *    redirect nor the capture response is proof; completePayPalReturn() re-reads the server.
 *  - A payout has reached the beneficiary only when its status is "succeeded". Today no live payout
 *    provider exists, so a payout stops at "approved_for_submission" and must be shown as in progress.
 *  - Balances come from GET /campaigns/{id}/funds (ledger-backed), never from client-side sums.
 *  - Simulated channels (SMS/USSD simulator, payout simulator) must be labelled with channelModes().
 *  - AI is optional: every AI failure is an ApiError the caller can ignore while the non-AI form,
 *    search (GET /campaigns?q=) and donation flows keep working.
 *
 * Verified against the live API by backend/tests/e2e/test_frontend_client.py.
 */

import type {
  AIMeta,
  AssistantReply,
  AssistantRequest,
  CampaignDraft,
  CampaignDraftRequest,
  CampaignSearchRequest,
  CampaignSearchResult,
  DonationStatus,
  AIStatus,
  IntegrationStatus,
  MessagingStatus,
  Money,
  PayoutStatus,
  SimulatedSms,
  SimulatorMeta,
  SimulatorSmsReply,
  SimulatorUssdReply,
  StatusExplanation,
  StatusExplanationRequest,
  SupportRequest,
  Translation,
  TranslateRequest,
} from "./ai-messaging.types.ts";
import { PAYOUT_STATUS_LABEL_EN } from "./ai-messaging.types.ts";

// ------------------------------------------------------------------ resource types

export type Role = "donor" | "creator" | "beneficiary" | "agent" | "reviewer" | "admin";
export type CampaignStatus = "draft" | "submitted" | "published" | "closed";
export type VerificationStatus = "unverified" | "verified" | "reverification_required" | "rejected";

export interface Campaign {
  id: string; title: string; slug: string; description: string; category: string;
  goal: Money; status: CampaignStatus; review_status: string;
}
/** GET /campaigns/{id}: public fields plus ledger-backed raised; beneficiary_id only for the creator and staff */
export interface CampaignDetail extends Campaign { raised: Money; beneficiary_id?: string }
/** GET /beneficiaries/me/campaigns item (beneficiary only, every status of the caller's own campaigns) */
export interface BeneficiaryCampaign extends Campaign { beneficiary_id: string; raised: Money; created_at: string; updated_at: string }
/** GET /campaigns/review-queue item (reviewer, admin): submitted campaigns, oldest first */
export interface ReviewQueueItem extends Campaign { beneficiary_id: string; raised: Money; submitted_at: string }
export interface PageMeta { page: number; page_size: number; total: number }
export interface CampaignInput {
  beneficiary_id: string; title: string; slug: string; description: string; category: string;
  goal_amount: string; goal_currency: string;
}
export interface CampaignFunds {
  campaign_id: string; goal: Money; visibility: "public" | "full"; source: "ledger"; as_of: string;
  balance: { currency: string; raised: string; reserved_for_payouts?: string; paid_out?: string; available?: string };
}
export interface Donation {
  id: string; campaign_id: string; amount: string; currency: string; status: DonationStatus; provider: string;
}
export interface DonationOrder extends Donation { approval_url: string | null }
export interface Payout {
  id: string; campaign_id: string; beneficiary_id: string; amount: string; currency: string;
  status: PayoutStatus; provider: string;
}
export interface BeneficiaryProfile {
  id: string; user_id: string | null; display_name: string; phone_number: string; country_code: string;
  preferred_language: string; verification_status: VerificationStatus; has_payout_destination: boolean;
  /** Send back unchanged when verifying; a 409 PROFILE_CHANGED means the profile changed after review. */
  revision: string;
}
export interface Session { access_token: string; user: { id: string; role: Role } }
export interface AccountSummary { id: string; email: string | null; phone_number: string | null; role: Role; status: string }

// ------------------------------------------------------------------ errors

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly details: Record<string, unknown>;
  readonly requestId: string | null;
  constructor(status: number, code: string, message: string, details: Record<string, unknown>, requestId: string | null) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.details = details;
    this.requestId = requestId;
  }
  /** The stored session is unusable; send the person to sign in again. */
  get sessionInvalid(): boolean {
    return this.code === "TOKEN_EXPIRED" || this.code === "INVALID_TOKEN" || this.code === "ACCOUNT_INACTIVE";
  }
  get retryAfterSeconds(): number | null {
    const value = this.details["retry_after_seconds"];
    return typeof value === "number" ? value : null;
  }
}

// ------------------------------------------------------------------ presentation rules

export type Tone = "success" | "pending" | "failure" | "neutral";
export interface StatusPresentation { label: string; tone: Tone; final: boolean }

const DONATION: Record<DonationStatus, StatusPresentation> = {
  created: { label: "Waiting for payment", tone: "pending", final: false },
  pending: { label: "Waiting for payment confirmation", tone: "pending", final: false },
  completed: { label: "Donation confirmed", tone: "success", final: true },
  failed: { label: "Payment not completed", tone: "failure", final: true },
  cancelled: { label: "Cancelled", tone: "neutral", final: true },
  refunded: { label: "Refunded", tone: "neutral", final: true },
  partially_refunded: { label: "Partially refunded", tone: "neutral", final: true },
};

const PAYOUT_TONE: Record<PayoutStatus, Tone> = {
  requested: "pending", under_review: "pending", approved_for_submission: "pending", submitted: "pending",
  pending_confirmation: "pending", succeeded: "success", rejected: "failure", failed: "failure",
};

export function presentDonation(status: DonationStatus): StatusPresentation {
  return DONATION[status] ?? { label: "Status unknown, check again shortly", tone: "pending", final: false };
}

export function presentPayout(status: PayoutStatus): StatusPresentation {
  const tone = PAYOUT_TONE[status];
  if (!tone) return { label: "Status unknown, check again shortly", tone: "pending", final: false };
  return { label: PAYOUT_STATUS_LABEL_EN[status], tone, final: tone !== "pending" };
}

export type ChannelMode = "simulated" | "sandbox" | "live" | "fallback" | "unconfigured";
export interface ChannelLabel { mode: ChannelMode; label: string }

/** Labels for every channel the UI mentions. Anything not "live" must be shown as such. */
export function channelModes(status: IntegrationStatus, payoutProvider: string): Record<"sms" | "ussd" | "ai" | "payouts", ChannelLabel> {
  const sms: ChannelLabel =
    status.messaging.sms.mode === "africastalking_live" ? { mode: "live", label: "SMS (live)" }
    : status.messaging.sms.mode === "africastalking_sandbox" ? { mode: "sandbox", label: "SMS sandbox, messages do not reach phones" }
    : { mode: "simulated", label: "Simulated SMS, nothing is sent to phones" };
  const ussd: ChannelLabel = status.messaging.ussd.live_shortcode_verified
    ? { mode: "live", label: `USSD ${status.messaging.ussd.service_code}` }
    : status.messaging.ussd.callback_configured
      ? { mode: "sandbox", label: `USSD ${status.messaging.ussd.service_code} (not yet verified on a live network)` }
      : { mode: "unconfigured", label: "USSD not configured" };
  const ai: ChannelLabel = status.ai.mode !== "live"
    ? { mode: "fallback", label: "AI unavailable, using templates" }
    : status.ai.last_error && !status.ai.model_verified
      ? { mode: "fallback", label: "AI not responding, using templates" }
      : { mode: "live", label: "AI suggestions (review before saving)" };
  const payouts: ChannelLabel = payoutProvider === "simulator"
    ? { mode: "simulated", label: "Payouts are simulated, no money is sent" }
    : { mode: "unconfigured", label: "Payout provider not configured" };
  return { sms, ussd, ai, payouts };
}

/** Outcome of returning from PayPal. Only "confirmed" may be shown as a successful donation; "failed" means the
 * server recorded the payment as not completed (a new donation is needed). */
export type PayPalReturnOutcome = "confirmed" | "failed" | "not_approved" | "provider_unavailable" | "needs_review" | "pending";

// ------------------------------------------------------------------ client

export interface ClientOptions {
  baseUrl: string;
  token?: string | null;
  fetch?: typeof fetch;
  /** Called once when the server says the session is expired, invalid or inactive. */
  onSessionInvalid?: (error: ApiError) => void;
}

type Query = Record<string, string | undefined>;

export class FundBridgeClient {
  private readonly baseUrl: string;
  private readonly fetchImpl: typeof fetch;
  private readonly onSessionInvalid?: (error: ApiError) => void;
  token: string | null;

  constructor(options: ClientOptions) {
    this.baseUrl = options.baseUrl.replace(/\/$/, "");
    this.fetchImpl = options.fetch ?? fetch;
    this.token = options.token ?? null;
    this.onSessionInvalid = options.onSessionInvalid;
  }

  private async request<T>(method: string, path: string, opts: { body?: unknown; query?: Query; idempotencyKey?: string } = {}) {
    const url = new URL(this.baseUrl + path);
    for (const [k, v] of Object.entries(opts.query ?? {})) if (v !== undefined && v !== "") url.searchParams.set(k, v);
    const headers: Record<string, string> = { Accept: "application/json" };
    if (opts.body !== undefined) headers["Content-Type"] = "application/json";
    if (this.token) headers["Authorization"] = `Bearer ${this.token}`;
    if (opts.idempotencyKey) headers["Idempotency-Key"] = opts.idempotencyKey;
    const res = await this.fetchImpl(url, { method, headers, body: opts.body === undefined ? undefined : JSON.stringify(opts.body) });
    const requestId = res.headers.get("X-Request-ID");
    const text = await res.text();
    const json = text ? JSON.parse(text) : null;
    if (!res.ok) {
      const err = json?.error ?? {};
      const error = new ApiError(res.status, err.code ?? `HTTP_${res.status}`, err.message ?? res.statusText, err.details ?? {}, requestId);
      if (error.sessionInvalid && this.onSessionInvalid) this.onSessionInvalid(error);
      throw error;
    }
    return { data: (json?.data ?? null) as T, meta: (json?.meta ?? {}) as Record<string, unknown> };
  }

  private async data<T>(method: string, path: string, opts: { body?: unknown; query?: Query; idempotencyKey?: string } = {}): Promise<T> {
    return (await this.request<T>(method, path, opts)).data;
  }

  /** A fresh key per user intent. Reuse the same key when retrying that intent after a network error. */
  static newIdempotencyKey(): string {
    return globalThis.crypto.randomUUID();
  }

  // auth
  register(email: string, password: string) { return this.data<{ id: string; role: Role }>("POST", "/api/v1/auth/register", { body: { email, password } }); }
  async login(email: string, password: string): Promise<Session> {
    const session = await this.data<Session>("POST", "/api/v1/auth/login", { body: { email, password } });
    this.token = session.access_token;
    return session;
  }
  me() { return this.data<{ id: string; email: string | null; phone_number: string | null; role: Role }>("GET", "/api/v1/auth/me"); }

  // platform
  publicConfig() { return this.data<{ payments: { paypal: { mode: string } }; payouts: { provider: string; mode: string } }>("GET", "/api/v1/public/config"); }
  integrationStatus() { return this.data<IntegrationStatus>("GET", "/api/v1/integrations/status"); }

  // campaigns
  listCampaigns(filter: { q?: string; category?: string } = {}) { return this.data<Campaign[]>("GET", "/api/v1/campaigns", { query: filter }); }
  getCampaign(id: string) { return this.data<CampaignDetail>("GET", `/api/v1/campaigns/${encodeURIComponent(id)}`); }
  async beneficiaryCampaigns(page = 1, pageSize = 20) {
    const r = await this.request<BeneficiaryCampaign[]>("GET", "/api/v1/beneficiaries/me/campaigns", { query: { page: String(page), page_size: String(pageSize) } });
    return { items: r.data, page: r.meta as unknown as PageMeta };
  }
  async reviewQueue(page = 1, pageSize = 20) {
    const r = await this.request<ReviewQueueItem[]>("GET", "/api/v1/campaigns/review-queue", { query: { page: String(page), page_size: String(pageSize) } });
    return { items: r.data, page: r.meta as unknown as PageMeta };
  }
  campaignFunds(id: string) { return this.data<CampaignFunds>("GET", `/api/v1/campaigns/${encodeURIComponent(id)}/funds`); }
  myCampaigns() { return this.data<Campaign[]>("GET", "/api/v1/me/campaigns"); }
  createCampaign(input: CampaignInput) { return this.data<Campaign>("POST", "/api/v1/campaigns", { body: input }); }
  updateCampaign(id: string, changes: Partial<Pick<Campaign, "title" | "description" | "category">>) { return this.data<Campaign>("PATCH", `/api/v1/campaigns/${encodeURIComponent(id)}`, { body: changes }); }
  submitCampaign(id: string) { return this.data<Campaign>("POST", `/api/v1/campaigns/${encodeURIComponent(id)}/submit`); }
  reviewCampaign(id: string, decision: "approve" | "reject") { return this.data<Campaign>("POST", `/api/v1/campaigns/${encodeURIComponent(id)}/review`, { body: { decision } }); }

  // donations
  createDonationOrder(input: { campaign_id: string; amount: string; currency: string; return_url: string; cancel_url: string }, idempotencyKey: string) {
    return this.data<DonationOrder>("POST", "/api/v1/donations/orders", { body: input, idempotencyKey });
  }
  captureDonation(id: string) { return this.data<Donation>("POST", `/api/v1/donations/${encodeURIComponent(id)}/capture`); }
  getDonation(id: string) { return this.data<Donation>("GET", `/api/v1/donations/${encodeURIComponent(id)}`); }
  myDonations() { return this.data<Donation[]>("GET", "/api/v1/me/donations"); }

  /** Re-reads the order from PayPal after an ambiguous capture. Never captures again; never credits twice. */
  reconcileDonation(id: string) { return this.data<Donation>("POST", `/api/v1/donations/${encodeURIComponent(id)}/reconcile`); }

  /**
   * Call on the PayPal return page. Asks the server to capture; if the result is ambiguous (timeout, or
   * PayPal says the order was already captured) it asks the server to reconcile with PayPal. Then it
   * re-reads the donation: the result is "confirmed" only when the server reports "completed".
   * Query parameters PayPal adds to the return URL are never used as evidence.
   */
  async completePayPalReturn(donationId: string): Promise<{ outcome: PayPalReturnOutcome; donation: Donation; presentation: StatusPresentation; error?: ApiError }> {
    let outcome: PayPalReturnOutcome = "pending";
    let failure: ApiError | undefined;
    let ambiguous = false;
    try {
      await this.captureDonation(donationId);
    } catch (e) {
      if (!(e instanceof ApiError) || e.sessionInvalid || e.status === 403 || e.status === 404) throw e;
      failure = e;
      const issue = e.details["provider_issue"];
      if (e.code === "PROVIDER_REQUEST_REJECTED" && issue === "ORDER_NOT_APPROVED") outcome = "not_approved";
      else if (e.code === "PROVIDER_REQUEST_REJECTED" && issue === "ORDER_ALREADY_CAPTURED") ambiguous = true;
      else if (e.code === "PROVIDER_UNAVAILABLE") { outcome = "provider_unavailable"; ambiguous = true; }
      else if (e.code === "PROVIDER_REQUEST_REJECTED") outcome = "provider_unavailable";
      else if (e.code.startsWith("PAYMENT_")) outcome = "needs_review";
    }
    if (ambiguous) {
      try {
        await this.reconcileDonation(donationId);
      } catch (e) {
        if (!(e instanceof ApiError) || e.sessionInvalid) throw e; // otherwise keep the donation pending; re-check later
      }
    }
    const donation = await this.getDonation(donationId);
    if (donation.status === "completed") outcome = "confirmed";
    // The server decided: PayPal declined/denied the capture or the order was cancelled (reconciliation, 9d3f80c).
    else if (donation.status === "failed" || donation.status === "cancelled") outcome = "failed";
    else if (presentDonation(donation.status).final) outcome = "needs_review";
    return { outcome, donation, presentation: presentDonation(donation.status), error: failure };
  }

  // payouts
  requestPayout(input: { campaign_id: string; beneficiary_id: string; amount: string; currency: string }, idempotencyKey: string) {
    return this.data<Payout>("POST", "/api/v1/payouts", { body: input, idempotencyKey });
  }
  listPayouts() { return this.data<Payout[]>("GET", "/api/v1/payouts"); }
  getPayout(id: string) { return this.data<Payout>("GET", `/api/v1/payouts/${encodeURIComponent(id)}`); }
  reviewPayout(id: string, decision: "approve" | "reject") { return this.data<Payout>("POST", `/api/v1/payouts/${encodeURIComponent(id)}/review`, { body: { decision } }); }

  // beneficiaries and staff operations
  myBeneficiaryProfile() { return this.data<Omit<BeneficiaryProfile, "user_id" | "has_payout_destination" | "revision">>("GET", "/api/v1/beneficiaries/me"); }
  updateMyBeneficiaryProfile(changes: { display_name?: string; preferred_language?: string; phone_number?: string; payout_destination_reference?: string }) {
    return this.data<{ id: string; verification_status: VerificationStatus }>("PATCH", "/api/v1/beneficiaries/me", { body: changes });
  }
  onboardBeneficiary(input: { display_name: string; phone_number: string; country_code: string; user_id?: string; preferred_language?: string; payout_destination_reference?: string }) {
    return this.data<{ id: string; verification_status: VerificationStatus }>("POST", "/api/v1/beneficiaries", { body: input });
  }
  listBeneficiaries(verificationStatus?: VerificationStatus) { return this.data<BeneficiaryProfile[]>("GET", "/api/v1/beneficiaries", { query: { verification_status: verificationStatus } }); }
  getBeneficiary(id: string) { return this.data<BeneficiaryProfile>("GET", `/api/v1/beneficiaries/${encodeURIComponent(id)}`); }
  decideVerification(id: string, decision: "verify" | "reject", revision: string, reason?: string) {
    return this.data<BeneficiaryProfile>("POST", `/api/v1/beneficiaries/${encodeURIComponent(id)}/verification`, { body: { decision, revision, reason } });
  }
  findAccounts(filter: { email?: string; phone_number?: string }) { return this.data<AccountSummary[]>("GET", "/api/v1/admin/users", { query: filter }); }
  assignRole(userId: string, role: Role) { return this.data<AccountSummary>("PUT", `/api/v1/admin/users/${encodeURIComponent(userId)}/role`, { body: { role } }); }

  // feature phones (staff)
  messagingStatus() { return this.data<MessagingStatus>("GET", "/api/v1/messaging/status"); }
  supportRequests() { return this.data<SupportRequest[]>("GET", "/api/v1/messaging/support-requests"); }
  resetPhonePin(beneficiaryId: string) { return this.data<{ beneficiary_id: string; pin: "reset" }>("POST", `/api/v1/messaging/beneficiaries/${encodeURIComponent(beneficiaryId)}/pin-reset`); }

  // Phone simulator: only when the server enables it (404 otherwise). Every result is simulated; label it.
  async simulateUssd(phoneNumber: string, text: string, sessionId?: string) {
    const r = await this.request<SimulatorUssdReply>("POST", "/api/v1/messaging/simulator/ussd", { body: { phone_number: phoneNumber, text, session_id: sessionId } });
    return { reply: r.data, meta: r.meta as unknown as SimulatorMeta };
  }
  async simulateSms(phoneNumber: string, text: string) {
    const r = await this.request<SimulatorSmsReply>("POST", "/api/v1/messaging/simulator/sms", { body: { phone_number: phoneNumber, text } });
    return { reply: r.data, meta: r.meta as unknown as SimulatorMeta };
  }
  async simulatorOutbox(phoneNumber: string) {
    const r = await this.request<SimulatedSms[]>("GET", "/api/v1/messaging/simulator/outbox", { query: { phone_number: phoneNumber } });
    return { messages: r.data, meta: r.meta as unknown as SimulatorMeta };
  }

  // AI (optional; callers should catch ApiError and fall back to the plain form/search)
  aiStatus() { return this.data<AIStatus>("GET", "/api/v1/ai/status"); }
  async draftCampaign(input: CampaignDraftRequest) { const r = await this.request<CampaignDraft>("POST", "/api/v1/ai/campaign-draft", { body: input }); return { draft: r.data, meta: r.meta as unknown as AIMeta }; }
  async translate(input: TranslateRequest) { const r = await this.request<Translation>("POST", "/api/v1/ai/translate", { body: input }); return { translation: r.data, meta: r.meta as unknown as AIMeta }; }
  async askAssistant(input: AssistantRequest) { const r = await this.request<AssistantReply>("POST", "/api/v1/ai/beneficiary-assistant", { body: input }); return { reply: r.data, meta: r.meta as unknown as AIMeta }; }
  /** Read-only. Show data.status_label/confirmed as the status; the explanation is supporting text. */
  async explainStatus(input: StatusExplanationRequest) { const r = await this.request<StatusExplanation>("POST", "/api/v1/ai/status-explanation", { body: input }); return { explanation: r.data, meta: r.meta as unknown as AIMeta }; }
  async aiSearch(input: CampaignSearchRequest) { const r = await this.request<CampaignSearchResult>("POST", "/api/v1/ai/campaign-search", { body: input }); return { result: r.data, meta: r.meta as unknown as AIMeta }; }
}
