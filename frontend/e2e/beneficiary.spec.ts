import { expect, test } from "@playwright/test";
import { account, expectNoHorizontalScroll, fund, getJson, publishedCampaign, reviewPayout, signInUi, uid } from "./support.ts";

test.describe("beneficiary", () => {
  test("sees confirmed funds, requests a payout and never sees it called paid", async ({ page, request }) => {
    const me = await account(request, "beneficiary");
    const title = `Tailoring shop ${uid()}`;
    const { campaignId, reviewer } = await publishedCampaign(request, title, { beneficiaryUserId: me.id });
    await fund(request, campaignId, "80.00");

    await signInUi(page, me.email);
    await expect(page).toHaveURL(/\/beneficiary$/);
    await expect(page.getByTestId("verification-status")).toHaveText("Verified");
    await expect(page.getByText("No money is sent in this environment")).toBeVisible();
    const card = page.getByTestId("beneficiary-campaign").filter({ hasText: title });
    await expect(card.getByTestId("available")).toHaveText("USD 80.00");
    await expectNoHorizontalScroll(page);

    // more than available is refused before anything is sent
    await card.getByLabel("Request a payout").fill("80.01");
    await card.getByRole("button", { name: "Request payout" }).click();
    await expect(card.getByText("The most you can request is USD 80.00.")).toBeVisible();

    await card.getByLabel("Request a payout").fill("30");
    await card.getByRole("button", { name: "Request payout" }).click();
    await expect(card.getByTestId("payout-requested")).toContainText("USD 30.00 is reserved and waiting for a reviewer. Nothing has been sent yet.");
    await expect(card.getByTestId("available")).toHaveText("USD 50.00");
    await expect(card.getByTestId("reserved")).toHaveText("USD 30.00");
    const row = page.getByTestId("payout-row").filter({ hasText: "USD 30.00" });
    await expect(row.getByTestId("payout-status")).toHaveText("Requested, waiting for review");

    const payouts = await getJson<{ id: string }[]>(request, "/payouts", me.token);
    await reviewPayout(request, reviewer.token, payouts[0].id, "approve");
    await page.reload();
    const approved = page.getByTestId("payout-row").filter({ hasText: "USD 30.00" });
    await expect(approved.getByTestId("payout-status")).toHaveText("Approved, being prepared");
    await expect(approved.getByTestId("payout-status")).toHaveAttribute("data-tone", "pending");
    await expect(approved).toContainText("No money has been sent. Payouts are simulated in this environment.");
    await expect(page.getByText("Paid to your mobile money account")).toHaveCount(0);
  });

  test("changing the phone number pauses payouts until re-verification", async ({ page, request }) => {
    const me = await account(request, "beneficiary");
    const { campaignId } = await publishedCampaign(request, `Bakery oven ${uid()}`, { beneficiaryUserId: me.id });
    await fund(request, campaignId, "15.00");
    await signInUi(page, me.email);
    await expect(page.getByTestId("payout-form")).toBeVisible();

    await page.getByTestId("profile-card").getByRole("button", { name: "Edit" }).click();
    await page.getByLabel("Phone number").fill("+254711000111");
    await expect(page.getByText("This pauses payouts")).toBeVisible();
    await page.getByRole("button", { name: "Save", exact: true }).click();
    await expect(page.getByTestId("profile-result")).toHaveText("Saved. A reviewer must verify you again before payouts resume.");
    await expect(page.getByTestId("verification-status")).toHaveText("Re-verification needed");
    await expect(page.getByTestId("unverified-notice")).toBeVisible();
    await expect(page.getByTestId("payout-form")).toHaveCount(0);
  });

  test("an account without a linked profile is told how to get linked", async ({ page, request }) => {
    const me = await account(request, "beneficiary");
    await signInUi(page, me.email);
    await expect(page.getByText("Your account is not linked to a beneficiary profile yet")).toBeVisible();
  });
});
