import { useState, type FormEvent } from "react";
import type { CampaignFunds } from "../api/client.ts";
import { ApiError } from "../api/client.ts";
import { PayoutRow } from "../components/PayoutList.tsx";
import { Button, Empty, ErrorNotice, Field, FundsMeter, Loading, Money, Notice, PageHead, SimTag, StatusPill } from "../components/ui.tsx";
import { forgetIntent, intentKey } from "../lib/intent.ts";
import { formatMoney, isValidAmount, normaliseAmount, toCents } from "../lib/money.ts";
import { presentCampaign, presentVerification } from "../lib/status.ts";
import { useCampaignTitles } from "../lib/useCampaignTitles.ts";
import { useResource } from "../lib/useResource.ts";
import { useEnvironment } from "../session/EnvironmentContext.tsx";
import { useSession } from "../session/SessionContext.tsx";

type Profile = Awaited<ReturnType<ReturnType<typeof useSession>["client"]["myBeneficiaryProfile"]>>;

export function BeneficiaryDashboard() {
  const { client } = useSession();
  const { config } = useEnvironment();
  const profile = useResource(() => client.myBeneficiaryProfile(), [client]);
  const campaigns = useResource(() => client.beneficiaryCampaigns(1, 50), [client]);
  const payouts = useResource(() => client.listPayouts(), [client]);
  const titles = useCampaignTitles(client, (payouts.data ?? []).map((p) => p.campaign_id));

  if (profile.loading && !profile.data) return <div className="container section"><Loading label="Loading your profile" /></div>;
  if (profile.error instanceof ApiError && profile.error.code === "BENEFICIARY_NOT_FOUND")
    return (
      <div className="container section">
        <Empty title="Your account is not linked to a beneficiary profile yet">
          <p>A FundBridge agent links your account when they onboard you. Contact your agent.</p>
        </Empty>
      </div>
    );
  if (profile.error || !profile.data) return <div className="container section"><ErrorNotice error={profile.error} onRetry={profile.reload} /></div>;
  const p = profile.data;
  const verified = p.verification_status === "verified";
  const refreshMoney = () => { campaigns.reload(); payouts.reload(); };

  return (
    <div className="container">
      <PageHead eyebrow="Beneficiary" title={`Hello, ${p.display_name}`} actions={<StatusPill presentation={presentVerification(p.verification_status)} testId="verification-status" />}>
        {!verified && (
          <Notice tone="pending" title="Payouts are paused until you are verified" testId="unverified-notice">
            <p>{p.verification_status === "reverification_required"
              ? "Your phone number or payout destination changed, so a reviewer must verify you again."
              : p.verification_status === "rejected" ? "A reviewer declined your verification. Contact your agent." : "A reviewer will check your details."}</p>
          </Notice>
        )}
      </PageHead>
      {config?.payouts.mode === "simulator" && (
        <div style={{ marginBottom: "1.25rem" }}>
          <Notice tone="neutral" title={<span className="row"><SimTag>Simulated payouts</SimTag> No money is sent in this environment</span>}>
            <p>Payout requests are reviewed for real, but approved payouts are not transferred to any mobile money account.</p>
          </Notice>
        </div>
      )}
      <div className="layout-2">
        <div className="stack">
          <h2>Your campaigns</h2>
          {campaigns.loading && !campaigns.data ? <Loading /> : campaigns.error ? <ErrorNotice error={campaigns.error} onRetry={campaigns.reload} /> : campaigns.data?.items.length ? (
            campaigns.data.items.map((c) => (
              <CampaignFundsCard key={c.id} campaignId={c.id} title={c.title} statusLabel={presentCampaign(c)} beneficiaryId={p.id} canRequest={verified && c.status === "published"} onRequested={refreshMoney} />
            ))
          ) : <Empty title="No campaigns yet"><p>Campaigns raised for you will appear here.</p></Empty>}
          <h2 style={{ marginTop: "2rem" }}>Payouts</h2>
          {payouts.loading && !payouts.data ? <Loading /> : payouts.error ? <ErrorNotice error={payouts.error} onRetry={payouts.reload} /> : payouts.data?.length ? (
            <div className="rows" data-testid="payout-list">{payouts.data.map((x) => <PayoutRow key={x.id} payout={x} title={titles[x.campaign_id]} />)}</div>
          ) : <Empty title="No payouts requested yet" />}
        </div>
        <aside className="stack">
          <ProfileCard profile={p} onSaved={profile.reload} />
        </aside>
      </div>
    </div>
  );
}

function CampaignFundsCard({ campaignId, title, statusLabel, beneficiaryId, canRequest, onRequested }: {
  campaignId: string; title: string; statusLabel: ReturnType<typeof presentCampaign>; beneficiaryId: string; canRequest: boolean; onRequested: () => void;
}) {
  const { client } = useSession();
  const funds = useResource(() => client.campaignFunds(campaignId), [client, campaignId]);
  return (
    <section className="card stack" data-testid="beneficiary-campaign">
      <div className="card__title"><h3>{title}</h3><StatusPill presentation={statusLabel} /></div>
      {funds.loading && !funds.data ? <Loading label="Reading the ledger" /> : funds.error ? <ErrorNotice error={funds.error} onRetry={funds.reload} /> : funds.data && (
        <>
          <FundsMeter funds={funds.data} />
          <div className="stat-grid">
            <div className="stat stat--accent"><div className="stat__label">Available</div><div className="stat__value" data-testid="available"><Money amount={funds.data.balance.available ?? "0.00"} currency={funds.data.balance.currency} /></div></div>
            <div className="stat"><div className="stat__label">Reserved</div><div className="stat__value" data-testid="reserved"><Money amount={funds.data.balance.reserved_for_payouts ?? "0.00"} currency={funds.data.balance.currency} /></div></div>
            <div className="stat"><div className="stat__label">Paid out</div><div className="stat__value"><Money amount={funds.data.balance.paid_out ?? "0.00"} currency={funds.data.balance.currency} /></div></div>
          </div>
          {canRequest && <PayoutForm funds={funds.data} beneficiaryId={beneficiaryId} onRequested={() => { funds.reload(); onRequested(); }} />}
        </>
      )}
    </section>
  );
}

function PayoutForm({ funds, beneficiaryId, onRequested }: { funds: CampaignFunds; beneficiaryId: string; onRequested: () => void }) {
  const { client } = useSession();
  const [amount, setAmount] = useState("");
  const [touched, setTouched] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [done, setDone] = useState<string | null>(null);
  const available = funds.balance.available ?? "0.00";
  const currency = funds.balance.currency;
  const invalid = !isValidAmount(amount) ? "Enter an amount greater than zero, with at most two decimals."
    : toCents(normaliseAmount(amount)) > toCents(available) ? `The most you can request is ${formatMoney(available, currency)}.` : null;

  if (toCents(available) <= 0n && !done) return <p className="small muted" style={{ margin: 0 }}>No confirmed funds are available to request yet.</p>;

  async function submit(e: FormEvent) {
    e.preventDefault();
    setTouched(true);
    if (invalid) return;
    const value = normaliseAmount(amount);
    const fingerprint = `${funds.campaign_id}|${value}`;
    setBusy(true); setError(null); setDone(null);
    try {
      const payout = await client.requestPayout({ campaign_id: funds.campaign_id, beneficiary_id: beneficiaryId, amount: value, currency }, intentKey("payout", fingerprint));
      forgetIntent("payout", fingerprint);
      setDone(formatMoney(payout.amount, payout.currency));
      setAmount(""); setTouched(false);
      onRequested();
    } catch (err) { setError(err); } finally { setBusy(false); }
  }

  return (
    <form className="form" onSubmit={submit} noValidate data-testid="payout-form">
      <Field label="Request a payout" htmlFor={`payout-${funds.campaign_id}`} help={`Up to ${formatMoney(available, currency)} available`} error={touched ? invalid : null}>
        <div className="input-affix"><span>{currency}</span>
          <input id={`payout-${funds.campaign_id}`} className="input" inputMode="decimal" value={amount} aria-invalid={touched && !!invalid} onChange={(e) => setAmount(e.target.value)} />
        </div>
      </Field>
      {done && <Notice tone="pending" title="Payout requested" testId="payout-requested"><p>{done} is reserved and waiting for a reviewer. Nothing has been sent yet.</p></Notice>}
      {error != null && <ErrorNotice error={error} />}
      <Button type="submit" variant="secondary" busy={busy} busyLabel="Requesting">Request payout</Button>
    </form>
  );
}

function ProfileCard({ profile, onSaved }: { profile: Profile; onSaved: () => void }) {
  const { client } = useSession();
  const [editing, setEditing] = useState(false);
  const [v, setV] = useState({ display_name: profile.display_name, preferred_language: profile.preferred_language, phone_number: profile.phone_number, destination: "" });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [result, setResult] = useState<string | null>(null);
  const sensitiveChange = v.phone_number.trim() !== profile.phone_number || v.destination.trim() !== "";

  async function save(e: FormEvent) {
    e.preventDefault();
    const changes: Record<string, string> = {};
    if (v.display_name.trim() && v.display_name.trim() !== profile.display_name) changes.display_name = v.display_name.trim();
    if (v.preferred_language.trim() && v.preferred_language.trim() !== profile.preferred_language) changes.preferred_language = v.preferred_language.trim();
    if (v.phone_number.trim() && v.phone_number.trim() !== profile.phone_number) changes.phone_number = v.phone_number.trim();
    if (v.destination.trim()) changes.payout_destination_reference = v.destination.trim();
    if (!Object.keys(changes).length) { setEditing(false); return; }
    setBusy(true); setError(null);
    try {
      const r = await client.updateMyBeneficiaryProfile(changes);
      setResult(r.verification_status === "reverification_required" ? "Saved. A reviewer must verify you again before payouts resume." : "Saved.");
      setEditing(false);
      onSaved();
    } catch (err) { setError(err); } finally { setBusy(false); }
  }

  return (
    <section className="card stack" data-testid="profile-card">
      <div className="card__title"><h3>Your details</h3>{!editing && <Button variant="ghost" small onClick={() => { setEditing(true); setResult(null); }}>Edit</Button>}</div>
      {result && <Notice tone={result.startsWith("Saved. A") ? "pending" : "success"} testId="profile-result">{result}</Notice>}
      {!editing ? (
        <dl className="dl">
          <dt>Name</dt><dd>{profile.display_name}</dd>
          <dt>Phone</dt><dd>{profile.phone_number}</dd>
          <dt>Country</dt><dd>{profile.country_code}</dd>
          <dt>Language</dt><dd>{profile.preferred_language}</dd>
          <dt>Payout to</dt><dd className="muted">Kept private, never shown</dd>
        </dl>
      ) : (
        <form className="form" onSubmit={save} noValidate>
          <Field label="Name" htmlFor="b-name"><input id="b-name" className="input" value={v.display_name} onChange={(e) => setV({ ...v, display_name: e.target.value })} /></Field>
          <Field label="Language" htmlFor="b-lang"><input id="b-lang" className="input" value={v.preferred_language} onChange={(e) => setV({ ...v, preferred_language: e.target.value })} /></Field>
          <Field label="Phone number" htmlFor="b-phone"><input id="b-phone" className="input" inputMode="tel" value={v.phone_number} onChange={(e) => setV({ ...v, phone_number: e.target.value })} /></Field>
          <Field label="New payout destination" htmlFor="b-dest" help="Mobile money wallet reference. Leave empty to keep the current one.">
            <input id="b-dest" className="input" autoComplete="off" value={v.destination} onChange={(e) => setV({ ...v, destination: e.target.value })} />
          </Field>
          {sensitiveChange && <Notice tone="pending" title="This pauses payouts">Changing your phone number or payout destination means a reviewer must verify you again.</Notice>}
          {error != null && <ErrorNotice error={error} />}
          <div className="row">
            <Button type="submit" busy={busy} busyLabel="Saving">Save</Button>
            <Button variant="ghost" onClick={() => setEditing(false)}>Cancel</Button>
          </div>
        </form>
      )}
    </section>
  );
}
