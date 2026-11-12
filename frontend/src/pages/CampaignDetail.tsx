import { Link, useParams } from "react-router-dom";
import { DonatePanel } from "../components/DonatePanel.tsx";
import { ErrorNotice, FundsMeter, Loading, Money, StatusPill } from "../components/ui.tsx";
import { categoryLabel, presentCampaign } from "../lib/status.ts";
import { formatTime } from "../lib/time.ts";
import { useResource } from "../lib/useResource.ts";
import { useSession } from "../session/SessionContext.tsx";

export function CampaignDetail() {
  const { id = "" } = useParams();
  const { client } = useSession();
  const campaign = useResource(() => client.getCampaign(id), [client, id]);
  const funds = useResource(() => client.campaignFunds(id), [client, id]);

  if (campaign.loading) return <div className="container section"><Loading label="Loading campaign" /></div>;
  if (campaign.error || !campaign.data) return <div className="container section"><ErrorNotice error={campaign.error} onRetry={campaign.reload} /></div>;
  const c = campaign.data;
  const f = funds.data;

  return (
    <div className="container">
      <div className="page-head">
        <Link to="/campaigns" className="small">← All campaigns</Link>
        <div className="row" style={{ marginTop: "1rem" }}>
          <span className="category">{categoryLabel(c.category)}</span>
          {c.status !== "published" && <StatusPill presentation={presentCampaign(c)} />}
        </div>
        <h1 style={{ marginTop: "0.5rem" }}>{c.title}</h1>
      </div>
      <div className="layout-2">
        <article className="stack">
          <section className="card stack" aria-labelledby="funds-heading">
            <h2 id="funds-heading" className="visually-hidden">Funds</h2>
            {f ? (
              <>
                <div className="amount-hero" data-testid="raised-hero"><Money amount={f.balance.raised} currency={f.balance.currency} /></div>
                <FundsMeter funds={f} large />
                {f.visibility === "full" && (
                  <div className="stat-grid" data-testid="full-funds">
                    <div className="stat stat--accent"><div className="stat__label">Available</div><div className="stat__value"><Money amount={f.balance.available ?? "0.00"} currency={f.balance.currency} /></div></div>
                    <div className="stat"><div className="stat__label">Reserved for payouts</div><div className="stat__value"><Money amount={f.balance.reserved_for_payouts ?? "0.00"} currency={f.balance.currency} /></div></div>
                    <div className="stat"><div className="stat__label">Paid out</div><div className="stat__value"><Money amount={f.balance.paid_out ?? "0.00"} currency={f.balance.currency} /></div></div>
                  </div>
                )}
                <p className="small muted" style={{ margin: 0 }}>
                  Counts confirmed payments only, from the FundBridge ledger, as of {formatTime(f.as_of)}.{" "}
                  <button type="button" className="btn btn--ghost btn--small" onClick={funds.reload}>Refresh</button>
                </p>
              </>
            ) : funds.error ? <ErrorNotice error={funds.error} onRetry={funds.reload} /> : <Loading label="Reading the ledger" />}
          </section>
          <section className="card">
            <h2>About this campaign</h2>
            <div style={{ whiteSpace: "pre-wrap" }}>{c.description}</div>
            <dl className="dl" style={{ marginTop: "1.25rem" }}>
              <dt>Goal</dt><dd><Money amount={c.goal.amount} currency={c.goal.currency} /></dd>
              <dt>Review</dt><dd>{c.status === "published" ? "Approved by a FundBridge reviewer" : presentCampaign(c).label}</dd>
            </dl>
          </section>
        </article>
        <aside className="stack">
          <DonatePanel campaign={c} />
        </aside>
      </div>
    </div>
  );
}
