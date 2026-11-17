import { Link } from "react-router-dom";
import type { Campaign } from "../api/client.ts";
import { formatMoney } from "../lib/money.ts";
import { categoryLabel } from "../lib/status.ts";
import { useResource } from "../lib/useResource.ts";
import { useSession } from "../session/SessionContext.tsx";
import { FundsMeter } from "./ui.tsx";

export function CampaignCard({ campaign }: { campaign: Campaign }) {
  const { client } = useSession();
  // The list payload has no balance (G-8), so each card reads its ledger-backed funds.
  const funds = useResource(() => client.campaignFunds(campaign.id), [client, campaign.id]);
  return (
    <Link to={`/campaigns/${campaign.id}`} className="card campaign-card" data-testid="campaign-card">
      <span className="category">{categoryLabel(campaign.category)}</span>
      <h3>{campaign.title}</h3>
      <p>{campaign.description}</p>
      <div className="campaign-card__foot">
        {funds.data ? <FundsMeter funds={funds.data} /> : (
          <div className="money-line"><span>Goal</span><strong>{formatMoney(campaign.goal.amount, campaign.goal.currency)}</strong></div>
        )}
      </div>
    </Link>
  );
}
