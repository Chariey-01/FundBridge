import { Link } from "react-router-dom";
import { Empty, ErrorNotice, Loading, Money, PageHead, StatusPill } from "../components/ui.tsx";
import { categoryLabel, presentCampaign } from "../lib/status.ts";
import { useResource } from "../lib/useResource.ts";
import { useSession } from "../session/SessionContext.tsx";

export function CreatorDashboard() {
  const { client } = useSession();
  const campaigns = useResource(() => client.myCampaigns(), [client]);
  return (
    <div className="container">
      <PageHead eyebrow="Campaign creator" title="My campaigns" actions={<Link className="btn btn--primary" to="/creator/new">New campaign</Link>}>
        <p>A campaign is a draft until you submit it. A reviewer then approves it, which makes it live, or sends it back to you for changes.</p>
      </PageHead>
      {campaigns.loading ? <Loading /> : campaigns.error ? <ErrorNotice error={campaigns.error} onRetry={campaigns.reload} /> : campaigns.data?.length ? (
        <div className="rows" data-testid="creator-campaigns">
          {campaigns.data.map((c) => (
            <div className="row-item" key={c.id} data-testid="creator-campaign">
              <div className="row-item__head">
                <Link className="row-item__title" to={`/creator/campaigns/${c.id}`}>{c.title}</Link>
                <StatusPill presentation={presentCampaign(c)} testId="campaign-status" />
              </div>
              <div className="row-item__meta">
                <span>{categoryLabel(c.category)}</span>
                <span>Goal <Money amount={c.goal.amount} currency={c.goal.currency} /></span>
                {c.status === "published" && <Link to={`/campaigns/${c.id}`}>Public page</Link>}
              </div>
            </div>
          ))}
        </div>
      ) : (
        <Empty title="No campaigns yet">
          <p>You need a beneficiary reference from a FundBridge agent before you start.</p>
          <Link className="btn btn--primary" to="/creator/new">Start a campaign</Link>
        </Empty>
      )}
    </div>
  );
}
