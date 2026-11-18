import { useState, type FormEvent } from "react";
import { Link, useLocation } from "react-router-dom";
import type { Campaign, DonationOrder } from "../api/client.ts";
import { forgetIntent, intentKey } from "../lib/intent.ts";
import { formatMoney, isValidAmount, normaliseAmount } from "../lib/money.ts";
import { paypalMode } from "../lib/modes.ts";
import { savePendingDonation } from "../lib/pendingDonation.ts";
import { safeHttpsUrl } from "../lib/urls.ts";
import { useEnvironment } from "../session/EnvironmentContext.tsx";
import { useSession } from "../session/SessionContext.tsx";
import { Button, ErrorNotice, Field, Notice, SimTag, StatusPill } from "./ui.tsx";
import { presentDonation } from "../api/client.ts";

const PRESETS = ["10", "25", "50", "100"];

export function DonatePanel({ campaign }: { campaign: Campaign }) {
  const { client, user } = useSession();
  const { config } = useEnvironment();
  const location = useLocation();
  const [amount, setAmount] = useState("25");
  const [touched, setTouched] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [order, setOrder] = useState<DonationOrder | null>(null);
  const currency = campaign.goal.currency;
  const paypal = paypalMode(config?.payments.paypal.mode);
  const amountOk = isValidAmount(amount);

  if (campaign.status !== "published") return null;

  if (paypal.mode === "unconfigured")
    return (
      <div className="card">
        <h2>Donate</h2>
        <Notice tone="neutral" title={paypal.label}><p>{paypal.detail}</p></Notice>
      </div>
    );

  if (!user)
    return (
      <div className="card stack">
        <h2>Donate</h2>
        <p className="muted">Sign in to donate. Donating without an account is not available yet.</p>
        <Link className="btn btn--primary btn--block" to={`/signin?next=${encodeURIComponent(location.pathname)}`}>Sign in to donate</Link>
        <Link className="btn btn--ghost btn--block" to="/register">Create an account</Link>
      </div>
    );

  async function submit(e: FormEvent) {
    e.preventDefault();
    setTouched(true);
    if (!amountOk) return;
    const value = normaliseAmount(amount);
    // Same campaign + amount = same intent, so a retry after a network error cannot create a second donation.
    const fingerprint = `${campaign.id}|${value}|${currency}`;
    setBusy(true);
    setError(null);
    try {
      const origin = window.location.origin;
      const created = await client.createDonationOrder(
        { campaign_id: campaign.id, amount: value, currency, return_url: `${origin}/donate/return`, cancel_url: `${origin}/donate/return?cancelled=1` },
        intentKey("donation", fingerprint),
      );
      savePendingDonation({ donationId: created.id, campaignId: campaign.id, amount: created.amount, currency: created.currency, approvalUrl: safeHttpsUrl(created.approval_url) });
      forgetIntent("donation", fingerprint);
      setOrder(created);
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  const checkoutUrl = safeHttpsUrl(order?.approval_url);

  if (order)
    return (
      <div className="card stack" data-testid="donation-order">
        <div className="card__title">
          <h2>Finish at PayPal</h2>
          <StatusPill presentation={presentDonation(order.status)} testId="order-status" />
        </div>
        <p>
          Your donation of <strong>{formatMoney(order.amount, order.currency)}</strong> has been set up but <strong>not paid yet</strong>.
          It is confirmed only after you approve it at PayPal and FundBridge verifies the payment.
        </p>
        {paypal.mode !== "live" && <p className="row small"><SimTag>Test mode</SimTag><span className="muted">{paypal.label}</span></p>}
        {checkoutUrl ? (
          <a className="btn btn--primary btn--block" href={checkoutUrl} data-testid="continue-to-paypal">Continue to PayPal</a>
        ) : (
          <Notice tone="failure" title="No usable PayPal checkout link"><p>The server did not return a secure PayPal link for this donation, so it cannot be paid from here. Nothing has been charged.</p></Notice>
        )}
        <Link className="small" to={`/donations/${order.id}`}>View this donation's status</Link>
      </div>
    );

  return (
    <form className="card stack" onSubmit={submit} noValidate data-testid="donate-form">
      <h2>Donate</h2>
      <div className="row" role="group" aria-label="Suggested amounts">
        {PRESETS.map((p) => (
          <button key={p} type="button" className={`btn btn--small ${amount === p ? "btn--secondary" : "btn--ghost"}`} aria-pressed={amount === p} onClick={() => setAmount(p)}>
            {formatMoney(p, currency).replace(".00", "")}
          </button>
        ))}
      </div>
      <Field label="Amount" htmlFor="donation-amount" error={touched && !amountOk ? "Enter an amount greater than zero, with at most two decimals." : null}>
        <div className="input-affix">
          <span>{currency}</span>
          <input id="donation-amount" className="input" inputMode="decimal" autoComplete="off" value={amount} aria-invalid={touched && !amountOk}
            onChange={(e) => setAmount(e.target.value)} onBlur={() => setTouched(true)} />
        </div>
      </Field>
      {error != null && <ErrorNotice error={error} />}
      <Button type="submit" block busy={busy} busyLabel="Setting up your donation">Continue to payment</Button>
      <p className="small muted" style={{ margin: 0 }}>
        {paypal.mode === "live" ? "You will approve the payment at PayPal." : <><SimTag>Test mode</SimTag> {paypal.label}.</>}
      </p>
    </form>
  );
}
