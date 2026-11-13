import { useEffect, useState } from "react";
import type { FundBridgeClient } from "../api/client.ts";

/** Donation and payout payloads carry only campaign ids; titles are read per campaign. */
export function useCampaignTitles(client: FundBridgeClient, ids: string[]): Record<string, string> {
  const [titles, setTitles] = useState<Record<string, string>>({});
  const key = Array.from(new Set(ids)).sort().join(",");
  useEffect(() => {
    let alive = true;
    const unique = key ? key.split(",") : [];
    Promise.all(unique.map((id) => client.getCampaign(id).then((c) => [id, c.title] as const, () => [id, "Campaign unavailable"] as const)))
      .then((pairs) => { if (alive) setTitles(Object.fromEntries(pairs)); });
    return () => { alive = false; };
  }, [client, key]);
  return titles;
}
