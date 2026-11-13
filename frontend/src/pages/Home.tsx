import { Link } from "react-router-dom";
import { CampaignCard } from "../components/CampaignCard.tsx";
import { ArrowIcon } from "../components/icons.tsx";
import { Empty, ErrorNotice } from "../components/ui.tsx";
import { useResource } from "../lib/useResource.ts";
import { useSession } from "../session/SessionContext.tsx";

export function Home() {
  const { client } = useSession();
  const campaigns = useResource(() => client.listCampaigns(), [client]);
  return (
    <>
      <section className="hero">
        <div className="container hero__inner">
          <div>
            <div className="eyebrow">Cross-border giving, accounted for</div>
            <h1>Support people directly. <em>See where every contribution stands.</em></h1>
            <p>
              FundBridge connects donors anywhere with verified beneficiaries, including people who use basic phones.
              A donation is marked confirmed only after the payment is verified, and a payout shows its real status at every step.
            </p>
            <div className="row">
              <Link to="/campaigns" className="btn btn--gold">Browse campaigns <ArrowIcon width={18} /></Link>
              <Link to="/system" className="btn btn--secondary btn--on-dark">How money moves</Link>
            </div>
          </div>
        </div>
      </section>

      <section className="section">
        <div className="container">
          <div className="spread">
            <h2>Live campaigns</h2>
            <Link to="/campaigns">See all</Link>
          </div>
          {campaigns.error ? <ErrorNotice error={campaigns.error} onRetry={campaigns.reload} /> : campaigns.loading ? (
            <div className="grid"><div className="skeleton" /><div className="skeleton" /><div className="skeleton" /></div>
          ) : campaigns.data && campaigns.data.length > 0 ? (
            <div className="grid">{campaigns.data.slice(0, 6).map((c) => <CampaignCard key={c.id} campaign={c} />)}</div>
          ) : (
            <Empty title="No live campaigns yet"><p>Campaigns appear here after a reviewer approves them.</p></Empty>
          )}
        </div>
      </section>

      <section className="section" style={{ background: "var(--paper)", borderTop: "1px solid var(--line)", borderBottom: "1px solid var(--line)" }}>
        <div className="container">
          <div className="eyebrow eyebrow--dark">How it works</div>
          <h2>From your donation to a beneficiary's wallet</h2>
          <div className="steps" style={{ marginTop: "1.5rem" }}>
            <div className="step"><h3>Reviewed campaigns</h3><p>Every campaign is checked by a reviewer before it can take donations. Beneficiaries are verified separately.</p></div>
            <div className="step"><h3>Donate through PayPal</h3><p>Your donation is “waiting for confirmation” until the server verifies PayPal's capture. Only then is it confirmed and counted.</p></div>
            <div className="step"><h3>Reviewed payouts</h3><p>Beneficiaries request payouts from confirmed funds. A reviewer approves each one before it is prepared.</p></div>
            <div className="step"><h3>Honest status</h3><p>A payout is shown as paid only when the mobile money provider confirms it. Test and simulated modes are always labelled.</p></div>
          </div>
        </div>
      </section>
    </>
  );
}
