import { useState, type FormEvent } from "react";
import { Link, useNavigate } from "react-router-dom";
import { Button, ErrorNotice, Field, PageHead } from "../components/ui.tsx";
import { hasErrors, slugify, validateNewCampaign } from "../lib/campaignForm.ts";
import { DONATION_CURRENCIES, normaliseAmount } from "../lib/money.ts";
import { CATEGORIES } from "../lib/status.ts";
import { useSession } from "../session/SessionContext.tsx";

export function CampaignNew() {
  const { client } = useSession();
  const navigate = useNavigate();
  const [v, setV] = useState({ title: "", slug: "", description: "", category: "", goal: "", currency: "USD", beneficiaryId: "" });
  const [slugEdited, setSlugEdited] = useState(false);
  const [touched, setTouched] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const errors = validateNewCampaign(v);
  const show = (k: keyof typeof errors) => (touched ? errors[k] : null);
  const set = (k: keyof typeof v) => (value: string) => setV((s) => ({ ...s, [k]: value, ...(k === "title" && !slugEdited ? { slug: slugify(value) } : {}) }));

  async function submit(e: FormEvent) {
    e.preventDefault();
    setTouched(true);
    if (hasErrors(errors)) return;
    setBusy(true); setError(null);
    try {
      const created = await client.createCampaign({
        beneficiary_id: v.beneficiaryId.trim(), title: v.title.trim(), slug: v.slug, description: v.description.trim(),
        category: v.category, goal_amount: normaliseAmount(v.goal), goal_currency: v.currency,
      });
      navigate(`/creator/campaigns/${created.id}`, { state: { created: true } });
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="container" style={{ maxWidth: 820 }}>
      <PageHead eyebrow="New campaign" title="Tell the story">
        <p>Saving creates a draft. Donors cannot see it until you submit it and a reviewer approves it.</p>
      </PageHead>
      <form className="card form" onSubmit={submit} noValidate data-testid="campaign-form">
        <Field label="Title" htmlFor="title" error={show("title")}>
          <input id="title" className="input" value={v.title} maxLength={160} aria-invalid={!!show("title")} onChange={(e) => set("title")(e.target.value)} />
        </Field>
        <Field label="Web address" htmlFor="slug" help={<>fundbridge/<strong>{v.slug || "your-campaign"}</strong></>} error={show("slug")}>
          <input id="slug" className="input" value={v.slug} maxLength={180} aria-invalid={!!show("slug")} onChange={(e) => { setSlugEdited(true); set("slug")(e.target.value.toLowerCase()); }} />
        </Field>
        <div className="form-grid">
          <Field label="Category" htmlFor="category" error={show("category")}>
            <select id="category" className="select" value={v.category} onChange={(e) => set("category")(e.target.value)}>
              <option value="">Choose…</option>
              {Object.entries(CATEGORIES).map(([k, l]) => <option key={k} value={k}>{l}</option>)}
            </select>
          </Field>
          <Field label="Goal" htmlFor="goal" error={show("goal")}>
            <input id="goal" className="input" inputMode="decimal" value={v.goal} aria-invalid={!!show("goal")} onChange={(e) => set("goal")(e.target.value)} />
          </Field>
          <Field label="Currency" htmlFor="currency" help="PayPal currencies only" error={show("currency")}>
            <select id="currency" className="select" value={v.currency} onChange={(e) => set("currency")(e.target.value)}>
              {DONATION_CURRENCIES.map((c) => <option key={c}>{c}</option>)}
            </select>
          </Field>
        </div>
        <Field label="Story" htmlFor="description" help="Who is this for, what is needed and how the money will be used." error={show("description")}>
          <textarea id="description" className="textarea" value={v.description} aria-invalid={!!show("description")} onChange={(e) => set("description")(e.target.value)} />
        </Field>
        <Field label="Beneficiary reference" htmlFor="beneficiary" help="The agent who onboarded the beneficiary gives you this reference. Creators cannot look up beneficiaries." error={show("beneficiaryId")}>
          <input id="beneficiary" className="input mono" value={v.beneficiaryId} autoComplete="off" spellCheck={false} aria-invalid={!!show("beneficiaryId")} onChange={(e) => set("beneficiaryId")(e.target.value)} />
        </Field>
        <p className="small muted" style={{ margin: 0 }}>The goal, currency and beneficiary cannot be changed after the draft is saved.</p>
        {error != null && <ErrorNotice error={error} />}
        <div className="row">
          <Button type="submit" busy={busy} busyLabel="Saving draft">Save draft</Button>
          <Link className="btn btn--ghost" to="/creator">Cancel</Link>
        </div>
      </form>
    </div>
  );
}
