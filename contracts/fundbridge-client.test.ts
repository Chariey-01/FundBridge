// Offline tests for the client's presentation rules. Run: node --test contracts/fundbridge-client.test.ts
import assert from "node:assert/strict";
import { test } from "node:test";

import type { DonationStatus, PayoutStatus } from "./ai-messaging.types.ts";
import { ApiError, FundBridgeClient, channelModes, presentDonation, presentPayout } from "./fundbridge-client.ts";

type Reply = { status: number; body: unknown };

function fakeFetch(routes: Record<string, Reply>, seen: string[] = []): typeof fetch {
  return (async (input: URL | RequestInfo, init?: RequestInit) => {
    const url = new URL(String(input));
    const key = `${init?.method ?? "GET"} ${url.pathname}`;
    seen.push(key);
    const reply = routes[key];
    if (!reply) throw new Error(`unexpected request ${key}`);
    return new Response(JSON.stringify(reply.body), { status: reply.status, headers: { "X-Request-ID": "req-1" } });
  }) as typeof fetch;
}

const DONATION_STATUSES: DonationStatus[] = ["created", "pending", "completed", "failed", "cancelled", "refunded", "partially_refunded"];
const PAYOUT_STATUSES: PayoutStatus[] = ["requested", "under_review", "rejected", "approved_for_submission", "submitted", "pending_confirmation", "failed", "succeeded"];

test("only a completed donation is presented as success", () => {
  for (const s of DONATION_STATUSES) assert.equal(presentDonation(s).tone === "success", s === "completed", s);
});

test("only a succeeded payout is presented as success; approved payouts stay pending", () => {
  for (const s of PAYOUT_STATUSES) assert.equal(presentPayout(s).tone === "success", s === "succeeded", s);
  assert.deepEqual(presentPayout("approved_for_submission"), { label: "Approved, being prepared", tone: "pending", final: false });
  assert.equal(presentPayout("rejected").tone, "failure");
});

test("unknown future statuses are never shown as success", () => {
  assert.equal(presentDonation("weird" as DonationStatus).tone, "pending");
  assert.equal(presentPayout("weird" as PayoutStatus).tone, "pending");
});

const donation = (status: DonationStatus) => ({ status: 200, body: { data: { id: "d1", campaign_id: "c1", amount: "10.00", currency: "USD", status, provider: "paypal" } } });

test("PayPal return is confirmed only when the server re-read says completed", async () => {
  const seen: string[] = [];
  const client = new FundBridgeClient({ baseUrl: "http://api", fetch: fakeFetch({
    "POST /api/v1/donations/d1/capture": donation("completed"),
    "GET /api/v1/donations/d1": donation("pending"), // the authoritative read disagrees
  }, seen) });
  const result = await client.completePayPalReturn("d1");
  assert.equal(result.outcome, "pending");
  assert.equal(result.presentation.tone, "pending");
  assert.deepEqual(seen, ["POST /api/v1/donations/d1/capture", "GET /api/v1/donations/d1"]);
});

test("client passes a string URL to injected fetch implementations", async () => {
  const fetchImpl = (async (input: RequestInfo | URL) => {
    assert.equal(typeof input, "string");
    return new Response(JSON.stringify({ data: [] }), { status: 200 });
  }) as typeof fetch;
  const client = new FundBridgeClient({ baseUrl: "http://api", fetch: fetchImpl, token: "test" });
  assert.deepEqual(await client.findCampaignBeneficiaries("Amina"), []);
});

test("PayPal return before approval reports not_approved and stays pending", async () => {
  const client = new FundBridgeClient({ baseUrl: "http://api", fetch: fakeFetch({
    "POST /api/v1/donations/d1/capture": { status: 502, body: { error: { code: "PROVIDER_REQUEST_REJECTED", message: "x", details: { provider_status: 422, provider_issue: "ORDER_NOT_APPROVED" } } } },
    "GET /api/v1/donations/d1": donation("pending"),
  }) });
  const result = await client.completePayPalReturn("d1");
  assert.equal(result.outcome, "not_approved");
  assert.equal(result.error?.requestId, "req-1");
});

test("a capture mismatch needs review and is not success", async () => {
  const client = new FundBridgeClient({ baseUrl: "http://api", fetch: fakeFetch({
    "POST /api/v1/donations/d1/capture": { status: 400, body: { error: { code: "PAYMENT_AMOUNT_MISMATCH", message: "x", details: {} } } },
    "GET /api/v1/donations/d1": donation("pending"),
  }) });
  assert.equal((await client.completePayPalReturn("d1")).outcome, "needs_review");
});

test("an already-captured order is reconciled and confirmed only by the re-read", async () => {
  const seen: string[] = [];
  const client = new FundBridgeClient({ baseUrl: "http://api", fetch: fakeFetch({
    "POST /api/v1/donations/d1/capture": { status: 502, body: { error: { code: "PROVIDER_REQUEST_REJECTED", message: "x", details: { provider_status: 422, provider_issue: "ORDER_ALREADY_CAPTURED" } } } },
    "POST /api/v1/donations/d1/reconcile": donation("completed"),
    "GET /api/v1/donations/d1": donation("completed"),
  }, seen) });
  const result = await client.completePayPalReturn("d1");
  assert.equal(result.outcome, "confirmed");
  assert.deepEqual(seen, ["POST /api/v1/donations/d1/capture", "POST /api/v1/donations/d1/reconcile", "GET /api/v1/donations/d1"]);
});

test("a timeout is reconciled; a failed reconcile leaves the donation pending, not failed", async () => {
  const client = new FundBridgeClient({ baseUrl: "http://api", fetch: fakeFetch({
    "POST /api/v1/donations/d1/capture": { status: 503, body: { error: { code: "PROVIDER_UNAVAILABLE", message: "x", details: {} } } },
    "POST /api/v1/donations/d1/reconcile": { status: 400, body: { error: { code: "PAYMENT_NOT_CONFIRMED", message: "x", details: {} } } },
    "GET /api/v1/donations/d1": donation("pending"),
  }) });
  const result = await client.completePayPalReturn("d1");
  assert.equal(result.outcome, "provider_unavailable");
  assert.equal(result.presentation.tone, "pending");
});

test("an expired session triggers onSessionInvalid once and throws", async () => {
  const calls: string[] = [];
  const client = new FundBridgeClient({ baseUrl: "http://api", token: "old",
    onSessionInvalid: (e) => calls.push(e.code),
    fetch: fakeFetch({ "GET /api/v1/auth/me": { status: 401, body: { error: { code: "TOKEN_EXPIRED", message: "x", details: {} } } } }) });
  await assert.rejects(client.me(), (e: unknown) => e instanceof ApiError && e.code === "TOKEN_EXPIRED" && e.sessionInvalid);
  assert.deepEqual(calls, ["TOKEN_EXPIRED"]);
});

test("simulated and unverified channels are labelled", () => {
  const modes = channelModes({
    ai: { provider: "fallback", model: null, mode: "fallback_only", features: { campaign_draft: "template_fallback", translate: "unavailable", beneficiary_assistant: "rule_based_fallback", campaign_search: "keyword_fallback" }, supported_languages: {} as never, model_verified: false, last_success_at: null, last_error: null },
    messaging: { sms: { provider: "simulator", mode: "simulated", delivery_confirmed: false }, ussd: { service_code: "*384*123#", callback_configured: true, live_shortcode_verified: false }, simulator_enabled: true, notifications_enabled: true, sms_assistant: "rule_based" },
  }, "simulator");
  assert.equal(modes.sms.mode, "simulated");
  assert.match(modes.ussd.label, /not yet verified/);
  assert.equal(modes.ai.mode, "fallback");
  assert.match(modes.payouts.label, /simulated, no money is sent/);
});
