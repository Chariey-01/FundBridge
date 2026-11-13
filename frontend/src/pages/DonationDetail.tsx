import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { presentDonation } from "../api/client.ts";
import { Button, ErrorNotice, Loading, Money, Notice, StatusPill } from "../components/ui.tsx";
import { useResource } from "../lib/useResource.ts";
import { useSession } from "../session/SessionContext.tsx";

export function DonationDetail() {
  const { id = "" } = useParams();
  const { client } = useSession();
  const donation = useResource(() => client.getDonation(id), [client, id]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [checked, setChecked] = useState(false);

  async function askPayPal() {
    setBusy(true); setError(null);
    try {
      await client.reconcileDonation(id); // re-reads PayPal; never captures again
      setChecked(true);
      donation.reload();
    } catch (e) { setError(e); } finally { setBusy(false); }
  }

  if (donation.loading && !donation.data) return <div className="container section"><Loading label="Loading donation" /></div>;
  if (donation.error || !donation.data) return <div className="container section"><ErrorNotice error={donation.error} onRetry={donation.reload} /></div>;
  const d = donation.data;
  const p = presentDonation(d.status);
  return (
    <div className="container section" style={{ maxWidth: 720 }}>
      <div className="card stack" data-testid="donation-detail">
        <div className="card__title">
          <h1 style={{ margin: 0, fontSize: "1.6rem" }}>Donation</h1>
          <StatusPill presentation={p} testId="donation-status" />
        </div>
        <p className="amount-hero"><Money amount={d.amount} currency={d.currency} /></p>
        {d.status === "completed" ? (
          <Notice tone="success" title="Donation confirmed"><p>The payment was verified and is counted towards the campaign.</p></Notice>
        ) : p.final ? (
          <Notice tone={p.tone} title={p.label}><p>This donation is not counted towards the campaign.</p></Notice>
        ) : (
          <Notice tone="pending" title="Not confirmed yet">
            <p>This donation is not counted until PayPal's payment is verified. If you approved it at PayPal, ask FundBridge to check again. Checking never charges you twice.</p>
          </Notice>
        )}
        {checked && d.status !== "completed" && <p className="small muted" data-testid="reconcile-result">Checked with PayPal: still {p.label.toLowerCase()}.</p>}
        {error != null && <ErrorNotice error={error} />}
        <div className="row">
          {!p.final && <Button onClick={askPayPal} busy={busy} busyLabel="Checking with PayPal">Check with PayPal</Button>}
          <Link className="btn btn--ghost" to={`/campaigns/${d.campaign_id}`}>View campaign</Link>
          <Link className="btn btn--ghost" to="/account/donations">My donations</Link>
        </div>
        <p className="small muted" style={{ margin: 0 }}>Reference <span className="mono">{d.id}</span></p>
      </div>
    </div>
  );
}
