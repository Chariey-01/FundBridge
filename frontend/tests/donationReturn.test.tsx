import { screen } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";
import { returnPolling } from "../src/lib/donationReturn.ts";
import { savePendingDonation } from "../src/lib/pendingDonation.ts";
import { DonationReturn } from "../src/pages/DonationReturn.tsx";
import { fail, fakeBackend, ok, renderApp, signedIn } from "./helpers.tsx";

const donation = (status: string) => ok({ id: "d1", campaign_id: "c1", amount: "25.00", currency: "USD", status, provider: "paypal" });

describe("PayPal return page: success only when the server says completed", () => {
  beforeEach(() => {
    returnPolling.delaysMs = [5];
    signedIn("donor");
    savePendingDonation({ donationId: "d1", campaignId: "c1", amount: "25.00", currency: "USD", approvalUrl: "https://www.sandbox.paypal.com/checkoutnow?token=O1" });
  });

  it("confirms after a verified capture", async () => {
    const { fetchImpl, calls } = fakeBackend({
      "POST /api/v1/donations/d1/capture": donation("completed"),
      "GET /api/v1/donations/d1": donation("completed"),
    });
    renderApp(<DonationReturn />, { route: "/donate/return?token=O1&PayerID=X", fetchImpl });
    expect(await screen.findByText("Donation confirmed", { selector: "strong" })).toBeInTheDocument();
    expect(calls.filter((c) => c.path.startsWith("/api/v1/donations/d1/capture"))).toHaveLength(1);
    expect(window.sessionStorage.getItem("fundbridge.pendingDonation")).toBeNull();
  });

  it("stays pending when PayPal times out and reconcile cannot confirm", async () => {
    const { fetchImpl, calls } = fakeBackend({
      "POST /api/v1/donations/d1/capture": fail(503, "PROVIDER_UNAVAILABLE"),
      "POST /api/v1/donations/d1/reconcile": donation("pending"),
      "GET /api/v1/donations/d1": donation("pending"),
    });
    renderApp(<DonationReturn />, { route: "/donate/return", fetchImpl });
    expect(await screen.findByText("PayPal is not responding")).toBeInTheDocument();
    expect(screen.queryByText(/Donation confirmed/)).not.toBeInTheDocument();
    expect(screen.queryByText("Thank you")).not.toBeInTheDocument();
    expect(screen.getByTestId("donation-status")).toHaveAttribute("data-tone", "pending");
    expect(calls.some((c) => c.path === "/api/v1/donations/d1/reconcile")).toBe(true);
    expect(calls.filter((c) => c.path.endsWith("/capture"))).toHaveLength(1); // never captures twice
  });

  it("explains an unapproved order and offers to return to PayPal", async () => {
    const { fetchImpl } = fakeBackend({
      "POST /api/v1/donations/d1/capture": fail(502, "PROVIDER_REQUEST_REJECTED", { provider_issue: "ORDER_NOT_APPROVED" }),
      "GET /api/v1/donations/d1": donation("pending"),
    });
    renderApp(<DonationReturn />, { route: "/donate/return", fetchImpl });
    expect(await screen.findByText("Payment not completed at PayPal")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Return to PayPal" })).toHaveAttribute("href", expect.stringContaining("checkoutnow"));
  });

  it("reports a declined payment as not completed", async () => {
    const { fetchImpl } = fakeBackend({
      "POST /api/v1/donations/d1/capture": fail(503, "PROVIDER_UNAVAILABLE"),
      "POST /api/v1/donations/d1/reconcile": donation("failed"),
      "GET /api/v1/donations/d1": donation("failed"),
    });
    renderApp(<DonationReturn />, { route: "/donate/return", fetchImpl });
    expect(await screen.findByText("Payment not completed", { selector: "strong" })).toBeInTheDocument();
    expect(screen.getByTestId("donation-status")).toHaveAttribute("data-tone", "failure");
  });

  it("does not capture when the donor cancelled at PayPal", async () => {
    const { fetchImpl, calls } = fakeBackend({ "GET /api/v1/donations/d1": donation("pending") });
    renderApp(<DonationReturn />, { route: "/donate/return?cancelled=1", fetchImpl });
    expect(await screen.findByText("You left PayPal before approving the payment")).toBeInTheDocument();
    expect(calls.some((c) => c.path.endsWith("/capture"))).toBe(false);
  });
});
