import { Link } from "react-router-dom";
import { presentDonation } from "../api/client.ts";
import { Empty, ErrorNotice, Loading, Money, PageHead, StatusPill } from "../components/ui.tsx";
import { useCampaignTitles } from "../lib/useCampaignTitles.ts";
import { useResource } from "../lib/useResource.ts";
import { useSession } from "../session/SessionContext.tsx";

export function MyDonations() {
  const { client } = useSession();
  const donations = useResource(() => client.myDonations(), [client]);
  const titles = useCampaignTitles(client, (donations.data ?? []).map((d) => d.campaign_id));
  return (
    <div className="container">
      <PageHead eyebrow="Your giving" title="My donations">
        <p>Only donations marked <strong>Donation confirmed</strong> have been paid and counted. Others are still waiting for PayPal or were not completed.</p>
      </PageHead>
      {donations.loading ? <Loading /> : donations.error ? <ErrorNotice error={donations.error} onRetry={donations.reload} /> : donations.data && donations.data.length ? (
        <div className="rows" data-testid="donation-list">
          {donations.data.map((d) => (
            <div className="row-item" key={d.id} data-testid="donation-row">
              <div className="row-item__head">
                <Link className="row-item__title" to={`/donations/${d.id}`}>{titles[d.campaign_id] ?? "Campaign"}</Link>
                <StatusPill presentation={presentDonation(d.status)} />
              </div>
              <div className="row-item__meta"><Money amount={d.amount} currency={d.currency} /><span>via PayPal</span></div>
            </div>
          ))}
        </div>
      ) : (
        <Empty title="No donations yet"><p><Link to="/campaigns">Find a campaign</Link> to support.</p></Empty>
      )}
    </div>
  );
}
