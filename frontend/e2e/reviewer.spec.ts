import { expect, test } from "@playwright/test";
import { account, adminToken, createCampaign, expectNoHorizontalScroll, fund, getJson, onboard, publishedCampaign, requestPayout, signInUi, submit, uid, ADMIN_EMAIL } from "./support.ts";

test.describe("reviewer and administrator", () => {
  test("publishes a campaign, verifies a beneficiary and approves a payout without claiming money moved", async ({ page, request }) => {
    const reviewer = await account(request, "reviewer");
    const creator = await account(request, "creator");
    const name = `Grace ${uid()}`;
    const ben = await onboard(request, { name });
    const title = `Library books ${uid()}`;
    const c = await createCampaign(request, creator.token, ben.id, title);
    await submit(request, creator.token, c.id);

    await signInUi(page, reviewer.email);
    await expect(page).toHaveURL(/\/review$/);
    const item = page.getByTestId("queue-item").filter({ hasText: title });
    await expect(item.getByTestId("beneficiary-check")).toContainText("Waiting for verification");
    await expect(item.getByTestId("beneficiary-check")).toContainText("Approving will still publish the campaign");
    await expectNoHorizontalScroll(page);
    await item.getByRole("button", { name: "Approve and publish" }).click();
    await item.getByRole("button", { name: "Confirm" }).click();
    await expect(page.getByTestId("review-result")).toContainText(`“${title}” is now live.`);
    expect((await getJson<{ status: string }>(request, `/campaigns/${c.id}`)).status).toBe("published");

    await page.getByRole("tab", { name: "Beneficiaries" }).click();
    const profile = page.getByTestId("beneficiary-item").filter({ hasText: name });
    await profile.getByRole("button", { name: "Verify" }).click();
    await profile.getByRole("button", { name: "Confirm" }).click();
    await expect(profile.getByTestId("verification-status")).toHaveText("Verified");

    // a funded payout request from the (now verified) beneficiary's side, via an admin
    await fund(request, c.id, "60.00");
    const admin = await adminToken(request);
    const payout = await requestPayout(request, admin, c.id, ben.id, "25.00");
    await page.getByRole("tab", { name: "Payouts" }).click();
    const row = page.getByTestId("payout-row").filter({ hasText: title }).filter({ hasText: "USD 25.00" });
    await expect(row.getByTestId("payout-status")).toHaveText("Requested, waiting for review");
    await row.getByRole("button", { name: "Approve" }).click();
    await row.getByRole("button", { name: "Confirm" }).click();
    await expect(row.getByTestId("payout-decision")).toHaveText("Approved for submission. No money has been sent: payouts are simulated here.");
    await expect(row.getByTestId("payout-status")).toHaveText("Approved, being prepared");
    await expect(row.getByTestId("payout-status")).toHaveAttribute("data-tone", "pending");
    await expect(row.getByText("Simulated payout")).toBeVisible();
    expect((await getJson<{ status: string }>(request, `/payouts/${payout.id}`, admin)).status).toBe("approved_for_submission");
  });

  test("an administrator cannot approve their own payout request", async ({ page, request }) => {
    const title = `Fishing nets ${uid()}`;
    const { campaignId } = await publishedCampaign(request, title);
    await fund(request, campaignId, "30.00");
    const admin = await adminToken(request);
    const campaign = await getJson<{ beneficiary_id: string }>(request, `/campaigns/${campaignId}`, admin);
    await requestPayout(request, admin, campaignId, campaign.beneficiary_id, "10.00");

    await signInUi(page, ADMIN_EMAIL);
    await page.goto("/review?tab=payouts");
    const row = page.getByTestId("payout-row").filter({ hasText: title });
    await row.getByRole("button", { name: "Approve" }).click();
    await row.getByRole("button", { name: "Confirm" }).click();
    await expect(row.getByTestId("error")).toContainText("You cannot approve a payout you requested.");
    await expect(row.getByTestId("payout-status")).toHaveText("Requested, waiting for review");
  });
});
