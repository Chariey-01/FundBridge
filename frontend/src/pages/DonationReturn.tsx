import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import type { Donation } from "../api/client.ts";
import { presentDonation } from "../api/client.ts";
import { Empty, ErrorNotice, Loading, Money, Notice, StatusPill } from "../components/ui.tsx";
import { confirmReturn, type ReturnResult } from "../lib/donationReturn.ts";
import { describeError } from "../lib/errors.ts";
import { clearPendingDonation, loadPendingDonation } from "../lib/pendingDonation.ts";
import { useSession } from "../session/SessionContext.tsx";

export function DonationReturn() {
  const [params] = useSearchParams();
  const cancelled = params.get("cancelled") === "1";
  const pending = loadPendingDonation();
  if (!pending)
    return (
      <div className="container section">
        <Empty title="We couldn't tell which donation this was">
          <p>Your donations and their confirmed status are listed in your account.</p>
          <Link className="btn btn--primary" to="/account/donations">My donations</Link>
        </Empty>
      </div>
    );
  return (
    <div className="container section" style={{ maxWidth: 720 }}>
      {cancelled ? <Cancelled donationId={pending.donationId} approvalUrl={pending.approvalUrl} /> : <Confirming donationId={pending.donationId} approvalUrl={pending.approvalUrl} campaignId={pending.campaignId} />}
    </div>
  );
}

function Cancelled({ donationId, approvalUrl }: { donationId: string; approvalUrl: string | null }) {
  const { client } = useSession();
  const [donation, setDonation] = useState<Donation | null>(null);
  const [error, setError] = useState<unknown>(null);
  useEffect(() => { client.getDonation(donationId).then(setDonation, setError); }, [client, donationId]);
  return (
    <div className="card stack" data-testid="donation-return">
      <h1>Payment not completed</h1>
      <Notice tone="pending" title="You left PayPal before approving the payment" testId="return-outcome">
        <p>Nothing has been confirmed and this donation is not counted. You can go back to PayPal to finish it.</p>
      </Notice>
      {donation && <p className="row">Status: <StatusPill presentation={presentDonation(donation.status)} testId="donation-status" /></p>}
      {error != null && <ErrorNotice error={error} />}
      <div className="row">
        {approvalUrl && <a className="btn btn--primary" href={approvalUrl}>Return to PayPal</a>}
        <Link className="btn btn--ghost" to={`/donations/${donationId}`}>View donation</Link>
      </div>
    </div>
  );
}

function Confirming({ donationId, approvalUrl, campaignId }: { donationId: string; approvalUrl: string | null; campaignId: string }) {
  const { client } = useSession();
  const [result, setResult] = useState<ReturnResult | null>(null);
  const [error, setError] = useState<unknown>(null);

  useEffect(() => {
    let alive = true;
    confirmReturn(client, donationId).then(
      (r) => { if (!alive) return; setResult(r); if (r.outcome === "confirmed" || r.outcome === "failed") clearPendingDonation(); },
      (e) => { if (alive) setError(e); },
    );
    return () => { alive = false; };
  }, [client, donationId]);

  if (error != null)
    return (
      <div className="card stack" data-testid="donation-return">
        <h1>We could not check this payment</h1>
        <ErrorNotice error={error} />
        <p className="muted">Nothing on this page means the payment succeeded. Check the donation again in a moment.</p>
        <Link className="btn btn--primary" to={`/donations/${donationId}`}>Check donation status</Link>
      </div>
    );

  if (!result)
    return (
      <div className="card stack" data-testid="donation-return">
        <h1>Confirming your payment</h1>
        <Loading label="Checking with PayPal. Please keep this page open" />
        <p className="muted small">Your donation is not confirmed until this check finishes.</p>
      </div>
    );

  const d = result.donation;
  const view = result.error ? describeError(result.error) : null;
  return (
    <div className="card stack" data-testid="donation-return">
      <div className="card__title">
        <h1 style={{ margin: 0 }}>{result.outcome === "confirmed" ? "Thank you" : "Donation not confirmed yet"}</h1>
        <StatusPill presentation={result.presentation} testId="donation-status" />
      </div>
      <p className="amount-hero"><Money amount={d.amount} currency={d.currency} /></p>
      {result.outcome === "confirmed" && (
        <Notice tone="success" title="Donation confirmed" testId="return-outcome">
          <p>PayPal's capture was verified by FundBridge and the amount is now counted towards the campaign.</p>
        </Notice>
      )}
      {result.outcome === "failed" && (
        <Notice tone="failure" title="Payment not completed" testId="return-outcome">
          <p>PayPal declined or cancelled this payment, so it is not counted. You can make a new donation from the campaign page.</p>
        </Notice>
      )}
      {result.outcome === "not_approved" && (
        <Notice tone="pending" title="Payment not completed at PayPal" testId="return-outcome">
          <p>PayPal reports that the payment was not approved. Your donation is not complete and nothing is counted.</p>
        </Notice>
      )}
      {result.outcome === "provider_unavailable" && (
        <Notice tone="pending" title="PayPal is not responding" testId="return-outcome">
          <p>We could not confirm the payment yet. It is not counted until it is verified. Check again in a few minutes.</p>
        </Notice>
      )}
      {result.outcome === "needs_review" && (
        <Notice tone="failure" title="We could not confirm this payment" testId="return-outcome">
          <p>It is not counted. Our support team can check it{view?.requestId ? <> using reference <span className="mono">{view.requestId}</span></> : null}.</p>
        </Notice>
      )}
      {result.outcome === "pending" && (
        <Notice tone="pending" title="Waiting for payment confirmation" testId="return-outcome">
          <p>PayPal has not confirmed the payment yet. It is not counted until it is verified.</p>
        </Notice>
      )}
      <div className="row">
        {result.outcome === "confirmed" || result.outcome === "failed" ? (
          <Link className="btn btn--primary" to={`/campaigns/${campaignId}`}>{result.outcome === "failed" ? "Donate again" : "Back to the campaign"}</Link>
        ) : (
          <>
            {result.outcome === "not_approved" && approvalUrl && <a className="btn btn--primary" href={approvalUrl}>Return to PayPal</a>}
            <Link className="btn btn--ghost" to={`/donations/${donationId}`}>Check status again</Link>
          </>
        )}
        <Link className="btn btn--ghost" to="/account/donations">My donations</Link>
      </div>
    </div>
  );
}
