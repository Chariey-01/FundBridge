import { useState } from "react";
import { Button } from "./ui.tsx";

/** Two-step decision buttons: the first click asks for confirmation, so a slip never approves anything. */
export function Decision({ approveLabel, rejectLabel, onDecide, busy, disabled }: {
  approveLabel: string; rejectLabel: string; onDecide: (d: "approve" | "reject") => void; busy: "approve" | "reject" | null; disabled?: boolean;
}) {
  const [pending, setPending] = useState<"approve" | "reject" | null>(null);
  if (pending)
    return (
      <div className="row-item__actions" role="group" aria-label="Confirm decision">
        <span className="small">{pending === "approve" ? `${approveLabel}?` : `${rejectLabel}?`}</span>
        <Button small variant={pending === "approve" ? "primary" : "danger"} busy={busy === pending} busyLabel="Saving" onClick={() => { onDecide(pending); setPending(null); }}>
          Confirm
        </Button>
        <Button small variant="ghost" disabled={busy !== null} onClick={() => setPending(null)}>Cancel</Button>
      </div>
    );
  return (
    <div className="row-item__actions">
      <Button small busy={busy === "approve"} busyLabel="Saving" disabled={disabled || busy !== null} onClick={() => setPending("approve")}>{approveLabel}</Button>
      <Button small variant="danger" busy={busy === "reject"} busyLabel="Saving" disabled={disabled || busy !== null} onClick={() => setPending("reject")}>{rejectLabel}</Button>
    </div>
  );
}
