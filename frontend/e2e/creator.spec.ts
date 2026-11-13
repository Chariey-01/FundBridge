import { expect, test } from "@playwright/test";
import { account, expectNoHorizontalScroll, onboard, review, signInUi, uid } from "./support.ts";

test.describe("campaign creator", () => {
  test("creates, edits and submits a draft; handles a send-back; goes live after approval", async ({ page, request }) => {
    const creator = await account(request, "creator");
    const reviewer = await account(request, "reviewer");
    const ben = await onboard(request, { name: `Joseph ${uid()}` });
    const title = `Maize mill ${uid()}`;

    await signInUi(page, creator.email);
    await expect(page).toHaveURL(/\/creator$/);
    await page.getByRole("link", { name: /New campaign|Start a campaign/ }).first().click();

    // client-side checks mirror the server's create rules: nothing is sent while invalid
    await page.getByLabel("Title").fill(title);
    await page.getByLabel("Story").fill("Too short");
    await page.getByRole("button", { name: "Save draft" }).click();
    await expect(page.getByText(/Write at least 20 characters/)).toBeVisible();

    await page.getByLabel("Category").selectOption("agriculture");
    await page.getByLabel("Goal").fill("750");
    await page.getByLabel("Story").fill("A shared maize mill so 40 farming families can process their harvest locally.");
    await page.getByLabel("Beneficiary reference").fill(ben.id);
    await expectNoHorizontalScroll(page);
    await page.getByRole("button", { name: "Save draft" }).click();

    await expect(page.getByTestId("editor-message")).toContainText("Draft saved. Donors cannot see it");
    await expect(page.getByTestId("campaign-status")).toHaveText("Draft, not visible to donors");
    const campaignId = page.url().split("/").pop()!;

    await page.getByLabel("Story").fill("A shared maize mill so 40 farming families can process their harvest locally and sell flour.");
    await expect(page.getByRole("button", { name: "Submit for review" })).toBeDisabled(); // unsaved changes
    await page.getByRole("button", { name: "Save changes" }).click();
    await expect(page.getByTestId("editor-message")).toHaveText("Changes saved.");
    await page.getByRole("button", { name: "Submit for review" }).click();
    await expect(page.getByTestId("campaign-status")).toHaveText("In review");
    await expect(page.getByTestId("in-review-notice")).toBeVisible();
    await expect(page.getByRole("button", { name: "Save changes" })).toHaveCount(0);

    // a reviewer sends it back
    await review(request, reviewer.token, campaignId, "reject");
    await page.reload();
    await expect(page.getByTestId("campaign-status")).toHaveText("Sent back by reviewer");
    await expect(page.getByTestId("rejected-notice")).toBeVisible();
    await page.getByLabel("Title").fill(`${title} (revised)`);
    await page.getByRole("button", { name: "Save changes" }).click();
    await expect(page.getByTestId("editor-message")).toHaveText("Changes saved.");
    await page.getByRole("button", { name: "Submit for review" }).click();
    await expect(page.getByTestId("campaign-status")).toHaveText("In review");

    // approved: live
    await review(request, reviewer.token, campaignId, "approve");
    await page.goto("/creator");
    const row = page.getByTestId("creator-campaign").filter({ hasText: `${title} (revised)` });
    await expect(row.getByTestId("campaign-status")).toHaveText("Live, accepting donations");
    await row.getByRole("link", { name: "Public page" }).click();
    await expect(page.getByRole("heading", { level: 1 })).toHaveText(`${title} (revised)`);
    await expect(page.getByTestId("full-funds")).toBeVisible(); // the creator sees the full ledger view
  });

  test("an unknown beneficiary reference is reported by the server", async ({ page, request }) => {
    const creator = await account(request, "creator");
    await signInUi(page, creator.email);
    await page.goto("/creator/new");
    await page.getByLabel("Title").fill(`Bridge repair ${uid()}`);
    await page.getByLabel("Category").selectOption("community");
    await page.getByLabel("Goal").fill("100");
    await page.getByLabel("Story").fill("Repairing the footbridge the school children use every day.");
    await page.getByLabel("Beneficiary reference").fill("00000000-0000-0000-0000-000000000000");
    await page.getByRole("button", { name: "Save draft" }).click();
    await expect(page.getByTestId("error")).toContainText("No beneficiary profile matches this reference.");
  });
});
