import { expect, test } from "@playwright/test";
import { expectNoHorizontalScroll, fund, publishedCampaign, uid } from "./support.ts";

test.describe("visitor", () => {
  test("browses, searches and reads a campaign with honest environment labels", async ({ page, request }) => {
    const word = `Kisumu${uid()}`;
    const { campaignId } = await publishedCampaign(request, `Solar lamps ${word}`);
    await fund(request, campaignId, "40.00");

    await page.goto("/");
    await expect(page.getByRole("heading", { name: /Support people directly/ })).toBeVisible();
    await expect(page.getByTestId("mode-paypal")).toHaveText("PayPal test mode, no real money");
    await expect(page.getByTestId("mode-payouts")).toHaveText("Payouts simulated, no money is sent");
    await expect(page.getByTestId("mode-sms")).toHaveText("Simulated SMS, nothing is sent to phones");
    await expectNoHorizontalScroll(page);

    await page.goto("/campaigns");
    await page.getByRole("searchbox", { name: "Search campaigns" }).fill(word);
    await page.getByRole("button", { name: "Search" }).click();
    await expect(page.getByTestId("campaign-card")).toHaveCount(1);
    await expect(page.getByTestId("campaign-card").getByTestId("raised")).toHaveText("USD 40.00");
    await expectNoHorizontalScroll(page);
    await page.getByTestId("campaign-card").click();

    await expect(page.getByRole("heading", { level: 1 })).toHaveText(`Solar lamps ${word}`);
    await expect(page.getByTestId("raised-hero")).toHaveText("USD 40.00");
    await expect(page.getByText("Counts confirmed payments only, from the FundBridge ledger")).toBeVisible();
    await expect(page.getByTestId("full-funds")).toHaveCount(0); // visitors see raised only
    await expect(page.getByRole("link", { name: "Sign in to donate" })).toBeVisible();
    await expectNoHorizontalScroll(page);
  });

  test("the environment page explains what is simulated, without claiming PayPal's own Sandbox", async ({ page }) => {
    await page.goto("/system");
    await expect(page.getByTestId("system-paypal")).toContainText("does not yet report whether these reach PayPal's Sandbox or a local stand-in");
    await expect(page.getByTestId("system-payouts")).toContainText("Simulated");
    await expect(page.getByTestId("system-sms")).toContainText("not delivered to any phone");
    await expect(page.getByTestId("system-ussd")).toContainText("not yet verified on a live network");
    await expectNoHorizontalScroll(page);
  });

  test("an invalid stored session is cleared and the person is asked to sign in", async ({ page }) => {
    await page.goto("/");
    await page.evaluate(() => sessionStorage.setItem("fundbridge.session", JSON.stringify({
      token: "not.a.valid-token", user: { id: "x", role: "donor", email: "ghost@example.test", phone_number: null }, expiresAt: null,
    })));
    await page.goto("/account/donations");
    await expect(page).toHaveURL(/\/signin\?next=/);
    await expect(page.getByTestId("session-notice")).toContainText("Your session ended");
  });
});
