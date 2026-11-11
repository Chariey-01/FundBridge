// Live test of the frontend client against a running API. Started by
// backend/tests/e2e/test_frontend_client.py, which provides these variables:
//   FB_API, FB_PAYPAL_DOUBLE, FB_CAMPAIGN_ID, FB_DONOR_EMAIL, FB_BENEFICIARY_EMAIL, FB_PASSWORD, FB_PAYOUT_ID
import assert from "node:assert/strict";
import { test } from "node:test";

import { ApiError, FundBridgeClient, channelModes, presentDonation, presentPayout } from "./fundbridge-client.ts";

const env = (k: string): string => {
  const v = process.env[k];
  if (!v) throw new Error(`${k} is required`);
  return v;
};
const cents = (s: string): bigint => BigInt(s.replace(".", ""));

test("donor journey through the client: browse, donate via PayPal, confirm from the server", async () => {
  const sessionErrors: string[] = [];
  const client = new FundBridgeClient({ baseUrl: env("FB_API"), onSessionInvalid: (e) => sessionErrors.push(e.code) });
  await client.login(env("FB_DONOR_EMAIL"), env("FB_PASSWORD"));

  const campaign = await client.getCampaign(env("FB_CAMPAIGN_ID"));
  const found = await client.listCampaigns({ q: campaign.title.split(" ")[0] });
  assert.ok(found.some((c) => c.id === campaign.id));
  const before = (await client.campaignFunds(campaign.id)).balance.raised;

  const key = FundBridgeClient.newIdempotencyKey();
  const order = await client.createDonationOrder({ campaign_id: campaign.id, amount: "7.50", currency: "USD",
    return_url: "http://localhost:3000/donate/return", cancel_url: "http://localhost:3000/donate/cancel" }, key);
  assert.equal(presentDonation(order.status).tone, "pending");
  assert.ok(order.approval_url);
  // Retrying the same intent with the same key returns the same donation.
  assert.equal((await client.createDonationOrder({ campaign_id: campaign.id, amount: "7.50", currency: "USD",
    return_url: "http://localhost:3000/donate/return", cancel_url: "http://localhost:3000/donate/cancel" }, key)).id, order.id);

  // The donor comes back without having approved: nothing is confirmed.
  const early = await client.completePayPalReturn(order.id);
  assert.equal(early.outcome, "not_approved");
  assert.notEqual(early.presentation.tone, "success");

  const orderId = new URL(order.approval_url!).searchParams.get("token")!;
  const approved = await fetch(`${env("FB_PAYPAL_DOUBLE")}/test/orders/${orderId}/approve`, { method: "POST" });
  assert.equal(approved.status, 200);

  const done = await client.completePayPalReturn(order.id);
  assert.equal(done.outcome, "confirmed");
  assert.equal(done.presentation.tone, "success");
  const after = (await client.campaignFunds(campaign.id)).balance.raised;
  assert.equal(cents(after) - cents(before), 750n);
  assert.ok((await client.myDonations()).some((d) => d.id === order.id && d.status === "completed"));

  // AI explanation of the same donation, from the server's record (works with or without a model).
  const { explanation, meta } = await client.explainStatus({ kind: "donation", id: order.id, language: "sw" });
  assert.equal(explanation.status, "completed");
  assert.equal(explanation.confirmed, true);
  assert.deepEqual(explanation.amount, { amount: "7.50", currency: "USD" });
  assert.equal(explanation.verified_text_language, "sw");
  assert.equal(typeof meta.ai_generated, "boolean");
  const detail = await client.getCampaign(campaign.id);
  assert.equal(detail.raised.amount, after);
  assert.equal(detail.beneficiary_id, undefined); // donors never see the beneficiary id
  assert.deepEqual(sessionErrors, []);
});

test("a capture whose response was lost is reconciled and confirmed by the server", async () => {
  const client = new FundBridgeClient({ baseUrl: env("FB_API") });
  await client.login(env("FB_DONOR_EMAIL"), env("FB_PASSWORD"));
  const campaignId = env("FB_CAMPAIGN_ID");
  const before = (await client.campaignFunds(campaignId)).balance.raised;
  const order = await client.createDonationOrder({ campaign_id: campaignId, amount: "3.25", currency: "USD",
    return_url: "http://localhost:3000/donate/return", cancel_url: "http://localhost:3000/donate/cancel" },
    FundBridgeClient.newIdempotencyKey());
  const orderId = new URL(order.approval_url!).searchParams.get("token")!;
  for (const step of ["approve", "capture-out-of-band"]) {
    assert.equal((await fetch(`${env("FB_PAYPAL_DOUBLE")}/test/orders/${orderId}/${step}`, { method: "POST" })).status, 200);
  }
  const done = await client.completePayPalReturn(order.id);
  assert.equal(done.outcome, "confirmed");
  assert.equal(done.error?.details["provider_issue"], "ORDER_ALREADY_CAPTURED");
  const after = (await client.campaignFunds(campaignId)).balance.raised;
  assert.equal(cents(after) - cents(before), 325n);
});

test("beneficiary sees server payout status and labelled simulated channels", async () => {
  const client = new FundBridgeClient({ baseUrl: env("FB_API") });
  await client.login(env("FB_BENEFICIARY_EMAIL"), env("FB_PASSWORD"));
  const payout = await client.getPayout(env("FB_PAYOUT_ID"));
  assert.equal(payout.status, "approved_for_submission");
  assert.equal(presentPayout(payout.status).tone, "pending"); // approved is not paid
  const mine = await client.beneficiaryCampaigns();
  assert.ok(mine.items.some((c) => c.id === payout.campaign_id) && mine.page.total >= 1);
  const { explanation } = await client.explainStatus({ kind: "payout", id: payout.id });
  assert.equal(explanation.status, "approved_for_submission");
  assert.equal(explanation.confirmed, false);
  assert.match(explanation.verified_text, /has not been sent/);
  const funds = await client.campaignFunds(payout.campaign_id);
  assert.equal(funds.visibility, "full");
  assert.ok(funds.balance.available !== undefined && funds.balance.reserved_for_payouts !== undefined);

  const config = await client.publicConfig();
  const modes = channelModes(await client.integrationStatus(), config.payouts.provider);
  assert.equal(modes.sms.mode, "simulated");
  assert.equal(modes.payouts.mode, "simulated");

  const sim = await client.simulateUssd("+254700000000", "");
  assert.equal(sim.meta.simulated, true);
  assert.match(sim.reply.response, /^CON FundBridge/);
});

test("an invalid session is reported through onSessionInvalid", async () => {
  const seen: string[] = [];
  const client = new FundBridgeClient({ baseUrl: env("FB_API"), token: "not-a-token", onSessionInvalid: (e) => seen.push(e.code) });
  await assert.rejects(client.me(), (e: unknown) => e instanceof ApiError && e.code === "INVALID_TOKEN" && e.requestId !== null);
  assert.deepEqual(seen, ["INVALID_TOKEN"]);
});
