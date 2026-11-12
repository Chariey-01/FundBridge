import type { ReactNode } from "react";
import type { Payout } from "../api/client.ts";
import { presentPayout } from "../api/client.ts";
import { Money, SimTag, StatusPill } from "./ui.tsx";

/** "Approved" is never "paid": only "succeeded" is a completed transfer. Simulated payouts are tagged. */
export function PayoutNote({ payout }: { payout: Payout }) {
  if (payout.status === "succeeded") return <span>The provider confirmed the transfer.</span>;
  if (payout.status === "rejected" || payout.status === "failed") return <span>The reserved amount is available again.</span>;
  if (payout.provider === "simulator") return <span>No money has been sent. Payouts are simulated in this environment.</span>;
  return <span>No money has been sent yet.</span>;
}

export function PayoutRow({ payout, title, children }: { payout: Payout; title?: string; children?: ReactNode }) {
  return (
    <div className="row-item" data-testid="payout-row" data-status={payout.status}>
      <div className="row-item__head">
        <span className="row-item__title"><Money amount={payout.amount} currency={payout.currency} />{title ? <span className="muted"> · {title}</span> : null}</span>
        <span className="row">
          {payout.provider === "simulator" && <SimTag>Simulated payout</SimTag>}
          <StatusPill presentation={presentPayout(payout.status)} testId="payout-status" />
        </span>
      </div>
      <div className="row-item__meta"><PayoutNote payout={payout} /></div>
      {children}
    </div>
  );
}
