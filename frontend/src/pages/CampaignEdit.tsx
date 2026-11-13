import { useEffect, useState, type FormEvent } from "react";
import { Link, useLocation, useParams } from "react-router-dom";
import type { Campaign } from "../api/client.ts";
import { Button, ErrorNotice, Field, FundsMeter, Loading, Money, Notice, PageHead, StatusPill } from "../components/ui.tsx";
import { hasErrors, validateCampaign } from "../lib/campaignForm.ts";
import { CATEGORIES, presentCampaign } from "../lib/status.ts";
import { useResource } from "../lib/useResource.ts";
import { useSession } from "../session/SessionContext.tsx";

export function CampaignEdit() {
  const { id = "" } = useParams();
  const { client } = useSession();
  const location = useLocation();
  const loaded = useResource(() => client.getCampaign(id), [client, id]);
  const funds = useResource(() => client.campaignFunds(id).catch(() => null), [client, id]);
  const [campaign, setCampaign] = useState<Campaign | null>(null);
  const [v, setV] = useState({ title: "", description: "", category: "" });
  const [touched, setTouched] = useState(false);
  const [busy, setBusy] = useState<"save" | "submit" | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [message, setMessage] = useState<string | null>((location.state as { created?: boolean } | null)?.created ? "Draft saved. Donors cannot see it until it is approved." : null);

  useEffect(() => {
    if (loaded.data) {
      setCampaign(loaded.data);
      setV({ title: loaded.data.title, description: loaded.data.description, category: loaded.data.category });
    }
  }, [loaded.data]);

  if (loaded.loading && !campaign) return <div className="container section"><Loading label="Loading campaign" /></div>;
  if (loaded.error || !campaign) return <div className="container section"><ErrorNotice error={loaded.error} onRetry={loaded.reload} /></div>;

  const editable = campaign.status === "draft";
  const errors = validateCampaign(v);
  const dirty = v.title !== campaign.title || v.description !== campaign.description || v.category !== campaign.category;

  async function save(e: FormEvent) {
    e.preventDefault();
    setTouched(true);
    if (hasErrors(errors) || !campaign) return;
    setBusy("save"); setError(null); setMessage(null);
    try {
      const updated = await client.updateCampaign(campaign.id, { title: v.title.trim(), description: v.description.trim(), category: v.category });
      setCampaign((c) => ({ ...c!, ...updated }));
      setV({ title: updated.title, description: updated.description, category: updated.category });
      setMessage("Changes saved.");
    } catch (err) { setError(err); } finally { setBusy(null); }
  }

  async function submitForReview() {
    if (!campaign) return;
    setBusy("submit"); setError(null); setMessage(null);
    try {
      const updated = await client.submitCampaign(campaign.id);
      setCampaign((c) => ({ ...c!, ...updated }));
      setMessage("Submitted. A reviewer will approve it or send it back to you.");
    } catch (err) { setError(err); } finally { setBusy(null); }
  }

  return (
    <div className="container" style={{ maxWidth: 860 }}>
      <PageHead eyebrow="Campaign" title={campaign.title} actions={<StatusPill presentation={presentCampaign(campaign)} testId="campaign-status" />}>
        <p><Link to="/creator">← My campaigns</Link></p>
      </PageHead>
      <div className="stack">
        {message && <Notice tone="success" testId="editor-message">{message}</Notice>}
        {campaign.status === "draft" && campaign.review_status === "rejected" && (
          <Notice tone="failure" title="A reviewer sent this campaign back" testId="rejected-notice">
            <p>Make your changes and submit it again. FundBridge does not record reviewers' notes yet, so ask the review team what to change.</p>
          </Notice>
        )}
        {campaign.status === "submitted" && <Notice tone="pending" title="In review" testId="in-review-notice"><p>You cannot edit the campaign while it is being reviewed.</p></Notice>}
        {campaign.status === "published" && (
          <Notice tone="success" title="Live" testId="live-notice"><p>This campaign is accepting donations. <Link to={`/campaigns/${campaign.id}`}>View the public page</Link>.</p></Notice>
        )}
        {funds.data && campaign.status === "published" && <div className="card"><FundsMeter funds={funds.data} /></div>}

        <form className="card form" onSubmit={save} noValidate data-testid="campaign-edit-form">
          <Field label="Title" htmlFor="edit-title" error={touched ? errors.title : null}>
            <input id="edit-title" className="input" value={v.title} maxLength={160} readOnly={!editable} aria-invalid={touched && !!errors.title} onChange={(e) => setV({ ...v, title: e.target.value })} />
          </Field>
          <Field label="Category" htmlFor="edit-category" error={touched ? errors.category : null}>
            <select id="edit-category" className="select" value={v.category} disabled={!editable} onChange={(e) => setV({ ...v, category: e.target.value })}>
              {Object.entries(CATEGORIES).map(([k, l]) => <option key={k} value={k}>{l}</option>)}
              {!CATEGORIES[v.category] && <option value={v.category}>{v.category}</option>}
            </select>
          </Field>
          <Field label="Story" htmlFor="edit-description" error={touched ? errors.description : null}>
            <textarea id="edit-description" className="textarea" value={v.description} readOnly={!editable} aria-invalid={touched && !!errors.description} onChange={(e) => setV({ ...v, description: e.target.value })} />
          </Field>
          <dl className="dl">
            <dt>Goal</dt><dd><Money amount={campaign.goal.amount} currency={campaign.goal.currency} /> <span className="muted small">(fixed)</span></dd>
            <dt>Web address</dt><dd className="mono">{campaign.slug}</dd>
            {"beneficiary_id" in campaign && <><dt>Beneficiary</dt><dd className="mono">{String((campaign as Campaign & { beneficiary_id?: string }).beneficiary_id ?? "")}</dd></>}
          </dl>
          {error != null && <ErrorNotice error={error} />}
          {editable && (
            <div className="row">
              <Button type="submit" variant="secondary" busy={busy === "save"} busyLabel="Saving" disabled={!dirty || busy !== null}>Save changes</Button>
              <Button onClick={submitForReview} busy={busy === "submit"} busyLabel="Submitting" disabled={dirty || busy !== null} title={dirty ? "Save your changes first" : undefined}>Submit for review</Button>
              {dirty && <span className="small muted">Save your changes before submitting.</span>}
            </div>
          )}
        </form>
      </div>
    </div>
  );
}
