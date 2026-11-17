import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { ReviewDesk } from "../src/pages/ReviewDesk.tsx";
import { fail, fakeBackend, ok, renderApp, signedIn } from "./helpers.tsx";

const profile = (status: string, revision = "rev-1", phone = "+254700000001") => ({
  id: "b1", user_id: null, display_name: "Grace W.", phone_number: phone, country_code: "KE", preferred_language: "sw",
  verification_status: status, has_payout_destination: true, revision,
});

describe("review desk: beneficiary verification", () => {
  it("keeps a verified profile in view with its new status", async () => {
    signedIn("reviewer");
    const { fetchImpl, calls } = fakeBackend({
      "GET /api/v1/beneficiaries": ok([profile("unverified")]),
      "POST /api/v1/beneficiaries/b1/verification": ok(profile("verified")),
    });
    renderApp(<ReviewDesk />, { route: "/review?tab=beneficiaries", fetchImpl });
    const item = await screen.findByTestId("beneficiary-item");
    await userEvent.click(within(item).getByRole("button", { name: "Verify" }));
    await userEvent.click(within(item).getByRole("button", { name: "Confirm" }));
    expect(await within(item).findByText("Verified.")).toBeInTheDocument();
    expect(within(item).getByTestId("verification-status")).toHaveTextContent("Verified");
    expect(calls.find((c) => c.path.endsWith("/verification"))!.body).toMatchObject({ decision: "verify", revision: "rev-1" });
  });

  it("refuses a stale decision and reloads the changed profile", async () => {
    signedIn("reviewer");
    const { fetchImpl } = fakeBackend({
      "GET /api/v1/beneficiaries": ok([profile("unverified")]),
      "POST /api/v1/beneficiaries/b1/verification": fail(409, "PROFILE_CHANGED"),
      "GET /api/v1/beneficiaries/b1": ok(profile("reverification_required", "rev-2", "+254799999999")),
    });
    renderApp(<ReviewDesk />, { route: "/review?tab=beneficiaries", fetchImpl });
    const item = await screen.findByTestId("beneficiary-item");
    await userEvent.click(within(item).getByRole("button", { name: "Verify" }));
    await userEvent.click(within(item).getByRole("button", { name: "Confirm" }));
    expect(await within(item).findByText(/changed after you opened it/)).toBeInTheDocument();
    expect(await within(item).findByText("+254799999999")).toBeInTheDocument();
    expect(within(item).getByTestId("verification-status")).toHaveTextContent("Re-verification needed");
  });
});

describe("review desk: payouts", () => {
  it("approval says no money moved and keeps the payout pending", async () => {
    signedIn("reviewer");
    const payout = { id: "p1", campaign_id: "c1", beneficiary_id: "b1", amount: "25.00", currency: "USD", provider: "simulator" };
    const { fetchImpl } = fakeBackend({
      "GET /api/v1/payouts": ok([{ ...payout, status: "requested" }]),
      "GET /api/v1/campaigns/c1": ok({ id: "c1", title: "Water tank", slug: "w", description: "", category: "community", goal: { amount: "1.00", currency: "USD" }, status: "published", review_status: "approved", raised: { amount: "0.00", currency: "USD" } }),
      "POST /api/v1/payouts/p1/review": ok({ ...payout, status: "approved_for_submission" }),
    });
    renderApp(<ReviewDesk />, { route: "/review?tab=payouts", fetchImpl });
    const row = await screen.findByTestId("payout-row");
    await userEvent.click(within(row).getByRole("button", { name: "Approve" }));
    await userEvent.click(within(row).getByRole("button", { name: "Confirm" }));
    expect(await within(row).findByTestId("payout-decision")).toHaveTextContent("No money has been sent: payouts are simulated here.");
    expect(within(row).getByTestId("payout-status")).toHaveAttribute("data-tone", "pending");
  });

  it("shows the server's refusal when approving one's own request", async () => {
    signedIn("admin");
    const payout = { id: "p1", campaign_id: "c1", beneficiary_id: "b1", amount: "10.00", currency: "USD", provider: "simulator", status: "requested" };
    const { fetchImpl } = fakeBackend({
      "GET /api/v1/payouts": ok([payout]),
      "GET /api/v1/campaigns/c1": fail(404, "NOT_FOUND"),
      "POST /api/v1/payouts/p1/review": fail(403, "SELF_APPROVAL_FORBIDDEN"),
    });
    renderApp(<ReviewDesk />, { route: "/review?tab=payouts", fetchImpl });
    const row = await screen.findByTestId("payout-row");
    await userEvent.click(within(row).getByRole("button", { name: "Approve" }));
    await userEvent.click(within(row).getByRole("button", { name: "Confirm" }));
    expect(await within(row).findByText("You cannot approve a payout you requested.")).toBeInTheDocument();
    expect(within(row).getByTestId("payout-status")).toHaveTextContent("Requested, waiting for review");
  });
});
