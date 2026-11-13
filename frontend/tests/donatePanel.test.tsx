import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { DonatePanel } from "../src/components/DonatePanel.tsx";
import { fakeBackend, renderApp, signedIn } from "./helpers.tsx";

const campaign = { id: "c1", title: "Water", slug: "water", description: "x".repeat(30), category: "community", goal: { amount: "1000.00", currency: "USD" }, status: "published" as const, review_status: "approved" };

describe("donate panel", () => {
  it("asks visitors to sign in (guest donation is unavailable)", async () => {
    const { fetchImpl } = fakeBackend({});
    renderApp(<DonatePanel campaign={campaign} />, { fetchImpl });
    expect(await screen.findByRole("link", { name: "Sign in to donate" })).toBeInTheDocument();
  });

  it("shows a created order as not paid yet, never as a successful donation", async () => {
    signedIn("donor");
    const { fetchImpl, calls } = fakeBackend({
      "POST /api/v1/donations/orders": { status: 201, body: { data: { id: "d1", campaign_id: "c1", amount: "40.00", currency: "USD", status: "pending", provider: "paypal", approval_url: "https://www.sandbox.paypal.com/checkoutnow?token=O1" }, meta: {} } },
    });
    renderApp(<DonatePanel campaign={campaign} />, { fetchImpl });
    const amount = await screen.findByLabelText("Amount");
    await userEvent.clear(amount);
    await userEvent.type(amount, "40");
    await userEvent.click(screen.getByRole("button", { name: "Continue to payment" }));
    expect(await screen.findByText("not paid yet")).toBeInTheDocument();
    expect(screen.getByTestId("order-status")).toHaveAttribute("data-tone", "pending");
    expect(screen.queryByText(/Donation confirmed/)).not.toBeInTheDocument();
    expect(screen.getByTestId("continue-to-paypal")).toHaveAttribute("href", expect.stringContaining("token=O1"));
    const order = calls.find((c) => c.path === "/api/v1/donations/orders")!;
    expect(order.body).toMatchObject({ campaign_id: "c1", amount: "40.00", currency: "USD" });
    expect(order.headers["Idempotency-Key"]).toMatch(/^[0-9a-f-]{36}$/);
    expect(JSON.parse(window.sessionStorage.getItem("fundbridge.pendingDonation")!).donationId).toBe("d1");
  });

  it("retries the same intent with the same Idempotency-Key after a network failure", async () => {
    signedIn("donor");
    let attempt = 0;
    const { fetchImpl, calls } = fakeBackend({
      "POST /api/v1/donations/orders": () => {
        attempt += 1;
        if (attempt === 1) throw new TypeError("Failed to fetch");
        return { status: 201, body: { data: { id: "d1", campaign_id: "c1", amount: "25.00", currency: "USD", status: "pending", provider: "paypal", approval_url: "https://p/x" }, meta: {} } };
      },
    });
    renderApp(<DonatePanel campaign={campaign} />, { fetchImpl });
    await userEvent.click(await screen.findByRole("button", { name: "Continue to payment" }));
    expect(await screen.findByText("Connection problem")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Continue to payment" }));
    await screen.findByText("not paid yet");
    const keys = calls.filter((c) => c.path === "/api/v1/donations/orders").map((c) => c.headers["Idempotency-Key"]);
    expect(keys).toHaveLength(2);
    expect(keys[0]).toBe(keys[1]);
  });

  it("never turns a non-https checkout link from the server into a link", async () => {
    signedIn("donor");
    const { fetchImpl } = fakeBackend({
      "POST /api/v1/donations/orders": { status: 201, body: { data: { id: "d1", campaign_id: "c1", amount: "25.00", currency: "USD", status: "pending", provider: "paypal", approval_url: "javascript:alert(document.domain)" }, meta: {} } },
    });
    renderApp(<DonatePanel campaign={campaign} />, { fetchImpl });
    await userEvent.click(await screen.findByRole("button", { name: "Continue to payment" }));
    expect(await screen.findByText("No usable PayPal checkout link")).toBeInTheDocument();
    expect(screen.queryByTestId("continue-to-paypal")).not.toBeInTheDocument();
    expect(JSON.parse(window.sessionStorage.getItem("fundbridge.pendingDonation")!).approvalUrl).toBeNull();
  });

  it("refuses invalid amounts before sending anything", async () => {
    signedIn("donor");
    const { fetchImpl, calls } = fakeBackend({});
    renderApp(<DonatePanel campaign={campaign} />, { fetchImpl });
    const amount = await screen.findByLabelText("Amount");
    await userEvent.clear(amount);
    await userEvent.type(amount, "12.345");
    await userEvent.click(screen.getByRole("button", { name: "Continue to payment" }));
    expect(screen.getByText(/at most two decimals/)).toBeInTheDocument();
    expect(calls.some((c) => c.path === "/api/v1/donations/orders")).toBe(false);
  });
});
