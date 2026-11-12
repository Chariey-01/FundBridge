import { expect, type APIRequestContext, type Page } from "@playwright/test";
import { API_PORT, PAYPAL_PORT } from "../playwright.config.ts";

/**
 * Setup through the public HTTP API only, the way other people would act on the platform.
 * PayPal approval goes through the local PayPal TEST DOUBLE's test-only endpoint; it stands in for
 * the donor clicking "Pay" on PayPal's checkout page. No real PayPal system is involved.
 */
export const API = `http://127.0.0.1:${API_PORT}/api/v1`;
export const PAYPAL_DOUBLE = `http://127.0.0.1:${PAYPAL_PORT}`;
export const ADMIN_EMAIL = process.env.E2E_ADMIN_EMAIL ?? "ops-admin@example.test";
export const PASSWORD = process.env.E2E_PASSWORD ?? "e2e-long-enough-password";

export const uid = () => Math.random().toString(36).slice(2, 10);

export interface Account { id: string; email: string; token: string }

async function call<T>(req: APIRequestContext, method: string, path: string, token?: string, data?: unknown, headers: Record<string, string> = {}): Promise<T> {
  const res = await req.fetch(API + path, { method, data, headers: { ...(token ? { Authorization: `Bearer ${token}` } : {}), ...headers } });
  const body = await res.text();
  expect(res.ok(), `${method} ${path} → ${res.status()} ${body}`).toBeTruthy();
  return (body ? JSON.parse(body).data : null) as T;
}

export async function login(req: APIRequestContext, email: string, password = PASSWORD): Promise<string> {
  return (await call<{ access_token: string }>(req, "POST", "/auth/login", undefined, { email, password })).access_token;
}

export async function adminToken(req: APIRequestContext) { return login(req, ADMIN_EMAIL); }

/** Public registration (always a donor), then the admin assigns the role through the API. */
export async function account(req: APIRequestContext, role: string, label = role): Promise<Account> {
  const email = `${label}-${uid()}@example.test`;
  const reg = await call<{ id: string }>(req, "POST", "/auth/register", undefined, { email, password: PASSWORD });
  if (role !== "donor") await call(req, "PUT", `/admin/users/${reg.id}/role`, await adminToken(req), { role });
  return { id: reg.id, email, token: await login(req, email) };
}

export async function onboard(req: APIRequestContext, opts: { name: string; userId?: string; destination?: string | null }) {
  const admin = await adminToken(req);
  return call<{ id: string }>(req, "POST", "/beneficiaries", admin, {
    display_name: opts.name, phone_number: `+2547${Math.floor(10000000 + Math.random() * 89999999)}`, country_code: "KE",
    ...(opts.userId ? { user_id: opts.userId } : {}),
    ...(opts.destination === null ? {} : { payout_destination_reference: opts.destination ?? `wallet-${uid()}` }),
  });
}

export async function verifyBeneficiary(req: APIRequestContext, reviewerToken: string, id: string) {
  const profile = await call<{ revision: string }>(req, "GET", `/beneficiaries/${id}`, reviewerToken);
  return call(req, "POST", `/beneficiaries/${id}/verification`, reviewerToken, { decision: "verify", revision: profile.revision });
}

export async function createCampaign(req: APIRequestContext, creatorToken: string, beneficiaryId: string, title: string, goal = "500.00") {
  const slug = `${title.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "")}-${uid()}`;
  return call<{ id: string }>(req, "POST", "/campaigns", creatorToken, {
    beneficiary_id: beneficiaryId, title, slug, category: "community", goal_amount: goal, goal_currency: "USD",
    description: `${title}: a community project that needs support to finish this season.`,
  });
}

export async function submit(req: APIRequestContext, creatorToken: string, campaignId: string) { return call(req, "POST", `/campaigns/${campaignId}/submit`, creatorToken); }
export async function review(req: APIRequestContext, reviewerToken: string, campaignId: string, decision: "approve" | "reject") {
  return call(req, "POST", `/campaigns/${campaignId}/review`, reviewerToken, { decision });
}

/** A published campaign with a verified, linked, payout-ready beneficiary. */
export async function publishedCampaign(req: APIRequestContext, title: string, opts: { beneficiaryUserId?: string; verify?: boolean } = {}) {
  const creator = await account(req, "creator");
  const reviewer = await account(req, "reviewer");
  const ben = await onboard(req, { name: `Amina ${uid()}`, userId: opts.beneficiaryUserId });
  if (opts.verify !== false) await verifyBeneficiary(req, reviewer.token, ben.id);
  const c = await createCampaign(req, creator.token, ben.id, title);
  await submit(req, creator.token, c.id);
  await review(req, reviewer.token, c.id, "approve");
  return { campaignId: c.id, beneficiaryId: ben.id, creator, reviewer };
}

export const orderIdFrom = (approvalUrl: string) => new URL(approvalUrl).searchParams.get("token")!;

export async function approveAtPayPalDouble(req: APIRequestContext, orderId: string) {
  const res = await req.post(`${PAYPAL_DOUBLE}/test/orders/${orderId}/approve`);
  expect(res.ok()).toBeTruthy();
}

export async function captureOutOfBand(req: APIRequestContext, orderId: string) {
  const res = await req.post(`${PAYPAL_DOUBLE}/test/orders/${orderId}/capture-out-of-band`);
  expect(res.ok()).toBeTruthy();
}

/** A completed donation made entirely through the API (create order, approve at the double, server capture). */
export async function fund(req: APIRequestContext, campaignId: string, amount: string) {
  const donor = await account(req, "donor");
  const order = await call<{ id: string; approval_url: string }>(req, "POST", "/donations/orders", donor.token,
    { campaign_id: campaignId, amount, currency: "USD", return_url: "http://127.0.0.1/r", cancel_url: "http://127.0.0.1/c" }, { "Idempotency-Key": crypto.randomUUID() });
  await approveAtPayPalDouble(req, orderIdFrom(order.approval_url));
  const done = await call<{ status: string }>(req, "POST", `/donations/${order.id}/capture`, donor.token);
  expect(done.status).toBe("completed");
}

export async function requestPayout(req: APIRequestContext, token: string, campaignId: string, beneficiaryId: string, amount: string) {
  return call<{ id: string; status: string }>(req, "POST", "/payouts", token, { campaign_id: campaignId, beneficiary_id: beneficiaryId, amount, currency: "USD" }, { "Idempotency-Key": crypto.randomUUID() });
}

export async function reviewPayout(req: APIRequestContext, token: string, payoutId: string, decision: "approve" | "reject") {
  return call(req, "POST", `/payouts/${payoutId}/review`, token, { decision });
}

export async function getJson<T>(req: APIRequestContext, path: string, token?: string) { return call<T>(req, "GET", path, token); }

/** Signs in through the real form. */
export async function signInUi(page: Page, email: string, password = PASSWORD) {
  await page.goto("/signin");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill(password);
  await page.getByRole("button", { name: "Sign in" }).click();
  // The role tag sits in the header menu, which is collapsed on phones; it exists once signed in.
  await expect(page.getByTestId("role-tag")).toBeAttached();
  await expect(page).not.toHaveURL(/\/signin/);
}

/** Opens the navigation menu on narrow screens, where it is collapsed. */
export async function openNav(page: Page) {
  const toggle = page.locator(".menu-toggle");
  if (await toggle.isVisible()) await toggle.click();
}

export async function expectNoHorizontalScroll(page: Page) {
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  expect(overflow, "page must not scroll horizontally").toBeLessThanOrEqual(0);
}

/**
 * Stands in for PayPal's checkout page: when the browser is sent to PayPal, optionally approve the
 * order at the local double, then send the browser back to the app's return (or cancel) URL.
 */
export async function routePayPalCheckout(page: Page, req: APIRequestContext, behaviour: "approve" | "leave" | "cancel" | "approve-and-capture-out-of-band") {
  await page.route("https://www.sandbox.paypal.com/**", async (route) => {
    const orderId = new URL(route.request().url()).searchParams.get("token")!;
    if (behaviour === "approve" || behaviour === "approve-and-capture-out-of-band") await approveAtPayPalDouble(req, orderId);
    if (behaviour === "approve-and-capture-out-of-band") await captureOutOfBand(req, orderId);
    const base = new URL(page.url()).origin;
    const target = behaviour === "cancel" ? `${base}/donate/return?cancelled=1` : `${base}/donate/return?token=${orderId}&PayerID=TESTBUYER`;
    await route.fulfill({ status: 302, headers: { Location: target } });
  });
}
