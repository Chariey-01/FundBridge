import { expect, test } from "@playwright/test";
import { account, expectNoHorizontalScroll, openNav, signInUi, uid, ADMIN_EMAIL } from "./support.ts";

test.describe("administrator tools", () => {
  test("assigns a role, cannot change their own, and onboards a beneficiary", async ({ page, request }) => {
    const person = await account(request, "donor");
    await signInUi(page, ADMIN_EMAIL);
    await openNav(page);
    await page.getByRole("link", { name: "People" }).click();
    await page.getByLabel("Email or phone number").fill(person.email);
    await page.getByRole("button", { name: "Find account" }).click();
    const row = page.getByTestId("account-row");
    await expect(row.getByTestId("account-role")).toHaveText("donor");
    await row.getByLabel("Role").selectOption("creator");
    await row.getByRole("button", { name: "Change role" }).click();
    await expect(row.getByTestId("role-saved")).toContainText("Role changed to creator");
    await expectNoHorizontalScroll(page);

    await page.getByLabel("Email or phone number").fill(ADMIN_EMAIL);
    await page.getByRole("button", { name: "Find account" }).click();
    await expect(page.getByTestId("account-row").getByText("This is you")).toBeVisible();
    await expect(page.getByTestId("account-row").getByLabel("Role")).toBeDisabled();

    const name = `Halima ${uid()}`;
    await page.goto("/agent/onboard");
    await page.getByLabel("Full name").fill(name);
    await page.getByLabel("Phone number").fill("+254 722 000 333");
    await page.getByLabel("Payout destination (optional)").fill(`wallet-${uid()}`);
    await page.getByRole("button", { name: "Create profile" }).click();
    await expect(page.getByTestId("onboard-result")).toContainText("waiting for verification");
    await expect(page.getByText(name)).toBeVisible();
    await expectNoHorizontalScroll(page);
  });
});
