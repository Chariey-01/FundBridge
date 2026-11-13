import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { Payout } from "../src/api/client.ts";
import { PayoutRow } from "../src/components/PayoutList.tsx";

const payout = (status: Payout["status"], provider = "simulator"): Payout => ({ id: "p1", campaign_id: "c1", beneficiary_id: "b1", amount: "120.00", currency: "USD", status, provider });

describe("payout status is never overstated", () => {
  it("approved is shown as pending and simulated, not paid", () => {
    render(<PayoutRow payout={payout("approved_for_submission")} />);
    expect(screen.getByTestId("payout-status")).toHaveTextContent("Approved, being prepared");
    expect(screen.getByTestId("payout-status")).toHaveAttribute("data-tone", "pending");
    expect(screen.getByText("Simulated payout")).toBeInTheDocument();
    expect(screen.getByText(/No money has been sent/)).toBeInTheDocument();
    expect(screen.queryByText(/Paid to your/)).not.toBeInTheDocument();
  });

  it("every in-flight status is pending", () => {
    for (const s of ["requested", "under_review", "submitted", "pending_confirmation"] as const) {
      const { unmount } = render(<PayoutRow payout={payout(s, "mpesa")} />);
      expect(screen.getByTestId("payout-status")).toHaveAttribute("data-tone", "pending");
      unmount();
    }
  });

  it("only succeeded is success", () => {
    render(<PayoutRow payout={payout("succeeded", "mpesa")} />);
    expect(screen.getByTestId("payout-status")).toHaveTextContent("Paid to your mobile money account");
    expect(screen.getByTestId("payout-status")).toHaveAttribute("data-tone", "success");
  });

  it("rejected releases the reservation", () => {
    render(<PayoutRow payout={payout("rejected")} />);
    expect(screen.getByTestId("payout-status")).toHaveAttribute("data-tone", "failure");
    expect(screen.getByText(/available again/)).toBeInTheDocument();
  });
});
