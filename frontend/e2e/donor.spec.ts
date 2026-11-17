import { expect, test, type Page } from "@playwright/test";
import { account, expectNoHorizontalScroll, getJson, openNav, publishedCampaign, routePayPalCheckout, signInUi, uid } from "./support.ts";

async function startDonation(page: Page, campaignId: string, amount: string) {
  await page.goto(`/campaigns/${campaignId}`);
  await page.getByRole("textbox", { name: "Amount", exact: true }).fill(amount);
  await page.getByRole("button", { name: "Continue to payment" }).click();
  const order = page.getByTestId("donation-order");
  await expect(order).toContainText("not paid yet");
  await expect(order.getByTestId("order-status")).toHaveText("Waiting for payment confirmation");
  await expect(page.getByTestId("raised-hero")).toHaveText("USD 0.00"); // nothing counted yet
  await expectNoHorizontalScroll(page);
}

test.describe("donor", () => {
  test("registers, donates, and sees it confirmed only after the server verifies the capture", async ({ page, request }) => {
    const { campaignId } = await publishedCampaign(request, `School desks ${uid()}`);
    const email = `new-donor-${uid()}@example.test`;
    await page.goto("/register");
    await page.getByLabel("Email").fill(email);
    await page.getByLabel("Password", { exact: true }).fill("a-very-long-password-1");
    await page.getByLabel("Confirm password").fill("a-very-long-password-1");
    await page.getByRole("button", { name: "Create account" }).click();
    await expect(page).toHaveURL(/\/campaigns$/);
    await expect(page.getByTestId("role-tag")).toHaveText("Donor");

    await startDonation(page, campaignId, "12.50");
    await routePayPalCheckout(page, request, "approve");
    await page.getByTestId("continue-to-paypal").click();

    await expect(page.getByTestId("return-outcome")).toContainText("Donation confirmed");
    await expect(page.getByTestId("donation-status")).toHaveText("Donation confirmed");
    await page.getByRole("link", { name: "Back to the campaign" }).click();
    await expect(page.getByTestId("raised-hero")).toHaveText("USD 12.50");

    await openNav(page);
    await page.getByRole("link", { name: "My donations" }).click();
    await expect(page.getByTestId("donation-row")).toHaveCount(1);
    await expect(page.getByTestId("donation-row")).toContainText("Donation confirmed");
    await expect(page.getByTestId("donation-row")).toContainText("USD 12.50");
  });

  test("returning without approving at PayPal is not a donation", async ({ page, request }) => {
    const { campaignId } = await publishedCampaign(request, `Clinic roof ${uid()}`);
    const donor = await account(request, "donor");
    await signInUi(page, donor.email);
    await startDonation(page, campaignId, "30");
    await routePayPalCheckout(page, request, "leave");
    await page.getByTestId("continue-to-paypal").click();

    await expect(page.getByTestId("return-outcome")).toContainText("Payment not completed at PayPal");
    await expect(page.getByTestId("donation-status")).toHaveText("Waiting for payment confirmation");
    await expect(page.getByText("Donation confirmed")).toHaveCount(0);
    await expect(page.getByRole("link", { name: "Return to PayPal" })).toBeVisible();
    const funds = await getJson<{ balance: { raised: string } }>(request, `/campaigns/${campaignId}/funds`);
    expect(funds.balance.raised).toBe("0.00");

    await page.getByRole("link", { name: "Check status again" }).click();
    await page.getByRole("button", { name: "Check with PayPal" }).click();
    await expect(page.getByTestId("reconcile-result")).toContainText("still waiting for payment confirmation");
    await expect(page.getByTestId("donation-status")).toHaveAttribute("data-tone", "pending");
  });

  test("cancelling at PayPal is explained and nothing is captured", async ({ page, request }) => {
    const { campaignId } = await publishedCampaign(request, `Seed bank ${uid()}`);
    const donor = await account(request, "donor");
    await signInUi(page, donor.email);
    await startDonation(page, campaignId, "8");
    await routePayPalCheckout(page, request, "cancel");
    await page.getByTestId("continue-to-paypal").click();
    await expect(page.getByTestId("return-outcome")).toContainText("You left PayPal before approving the payment");
    await expect(page.getByTestId("donation-status")).toHaveText("Waiting for payment confirmation");
  });

  test("an ambiguous capture is reconciled with PayPal, never captured twice", async ({ page, request }) => {
    const { campaignId } = await publishedCampaign(request, `Water tank ${uid()}`);
    const donor = await account(request, "donor");
    await signInUi(page, donor.email);
    await startDonation(page, campaignId, "20");
    // PayPal captured the order but FundBridge never saw the response (e.g. a timeout).
    await routePayPalCheckout(page, request, "approve-and-capture-out-of-band");
    await page.getByTestId("continue-to-paypal").click();
    await expect(page.getByTestId("return-outcome")).toContainText("Donation confirmed");
    const funds = await getJson<{ balance: { raised: string } }>(request, `/campaigns/${campaignId}/funds`);
    expect(funds.balance.raised).toBe("20.00"); // credited exactly once
  });
});
