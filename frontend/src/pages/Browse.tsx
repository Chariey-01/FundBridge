import { useState, type FormEvent } from "react";
import { useSearchParams } from "react-router-dom";
import { CampaignCard } from "../components/CampaignCard.tsx";
import { Empty, ErrorNotice, PageHead } from "../components/ui.tsx";
import { CATEGORIES } from "../lib/status.ts";
import { useResource } from "../lib/useResource.ts";
import { useSession } from "../session/SessionContext.tsx";

export function Browse() {
  const { client } = useSession();
  const [params, setParams] = useSearchParams();
  const q = params.get("q") ?? "";
  const category = params.get("category") ?? "";
  const [draftQ, setDraftQ] = useState(q);
  const [draftCategory, setDraftCategory] = useState(category);
  const campaigns = useResource(() => client.listCampaigns({ q: q || undefined, category: category || undefined }), [client, q, category]);

  function submit(e: FormEvent) {
    e.preventDefault();
    const next = new URLSearchParams();
    if (draftQ.trim()) next.set("q", draftQ.trim().slice(0, 100));
    if (draftCategory) next.set("category", draftCategory);
    setParams(next);
  }

  return (
    <div className="container">
      <PageHead eyebrow="Campaigns" title="Find a campaign to support">
        <p>Only campaigns approved by a reviewer are listed. Amounts raised count confirmed payments only.</p>
      </PageHead>
      <form className="search-bar" role="search" onSubmit={submit}>
        <label className="visually-hidden" htmlFor="q">Search campaigns</label>
        <input id="q" className="input" type="search" placeholder="Search by keyword" value={draftQ} maxLength={100} onChange={(e) => setDraftQ(e.target.value)} />
        <label className="visually-hidden" htmlFor="category">Category</label>
        <select id="category" className="select" value={draftCategory} onChange={(e) => setDraftCategory(e.target.value)}>
          <option value="">All categories</option>
          {Object.entries(CATEGORIES).map(([v, l]) => <option key={v} value={v}>{l}</option>)}
        </select>
        <button className="btn btn--primary" type="submit">Search</button>
      </form>
      <div className="section--tight">
        {campaigns.error ? <ErrorNotice error={campaigns.error} onRetry={campaigns.reload} /> : campaigns.loading ? (
          <div className="grid"><div className="skeleton" /><div className="skeleton" /><div className="skeleton" /></div>
        ) : campaigns.data && campaigns.data.length > 0 ? (
          <>
            <p className="muted small" aria-live="polite">{campaigns.data.length} campaign{campaigns.data.length === 1 ? "" : "s"}{campaigns.data.length === 50 ? " (the first 50 are shown)" : ""}</p>
            <div className="grid">{campaigns.data.map((c) => <CampaignCard key={c.id} campaign={c} />)}</div>
          </>
        ) : (
          <Empty title="No campaigns match"><p>Try another keyword or category.</p></Empty>
        )}
      </div>
    </div>
  );
}
