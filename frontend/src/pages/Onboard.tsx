import { useState, type FormEvent } from "react";
import { Button, CopyField, ErrorNotice, Field, Loading, Notice, PageHead, StatusPill } from "../components/ui.tsx";
import { presentVerification } from "../lib/status.ts";
import { useResource } from "../lib/useResource.ts";
import { useSession } from "../session/SessionContext.tsx";

const EMPTY = { display_name: "", phone_number: "", country_code: "KE", preferred_language: "en", user_id: "", destination: "" };

export function Onboard() {
  const { client } = useSession();
  const [v, setV] = useState(EMPTY);
  const [touched, setTouched] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [created, setCreated] = useState<{ id: string; verification_status: string } | null>(null);
  const recent = useResource(() => client.listBeneficiaries(), [client]);
  const errors = {
    display_name: v.display_name.trim() ? null : "Enter the beneficiary's name.",
    phone_number: /^\+?[0-9 ]{7,20}$/.test(v.phone_number.trim()) ? null : "Enter a phone number, e.g. +254700000000.",
    country_code: /^[A-Z]{2}$/.test(v.country_code) ? null : "Use the two-letter country code, e.g. KE.",
  };

  async function submit(e: FormEvent) {
    e.preventDefault();
    setTouched(true);
    if (Object.values(errors).some(Boolean)) return;
    setBusy(true); setError(null); setCreated(null);
    try {
      const result = await client.onboardBeneficiary({
        display_name: v.display_name.trim(), phone_number: v.phone_number.replace(/\s+/g, ""), country_code: v.country_code,
        preferred_language: v.preferred_language.trim() || "en",
        ...(v.user_id.trim() ? { user_id: v.user_id.trim() } : {}),
        ...(v.destination.trim() ? { payout_destination_reference: v.destination.trim() } : {}),
      });
      setCreated(result); setV(EMPTY); setTouched(false); recent.reload();
    } catch (err) { setError(err); } finally { setBusy(false); }
  }

  return (
    <div className="container">
      <PageHead eyebrow="Agent" title="Onboard a beneficiary">
        <p>New profiles wait for a reviewer's verification before any payout. Share the reference with the campaign creator; they need it to start a campaign.</p>
      </PageHead>
      <div className="layout-2">
        <form className="card form" onSubmit={submit} noValidate data-testid="onboard-form">
          <Field label="Full name" htmlFor="o-name" error={touched ? errors.display_name : null}>
            <input id="o-name" className="input" value={v.display_name} onChange={(e) => setV({ ...v, display_name: e.target.value })} />
          </Field>
          <div className="form-grid">
            <Field label="Phone number" htmlFor="o-phone" error={touched ? errors.phone_number : null}>
              <input id="o-phone" className="input" inputMode="tel" value={v.phone_number} onChange={(e) => setV({ ...v, phone_number: e.target.value })} />
            </Field>
            <Field label="Country" htmlFor="o-country" error={touched ? errors.country_code : null}>
              <input id="o-country" className="input" maxLength={2} value={v.country_code} onChange={(e) => setV({ ...v, country_code: e.target.value.toUpperCase() })} />
            </Field>
            <Field label="Language" htmlFor="o-lang"><input id="o-lang" className="input" value={v.preferred_language} onChange={(e) => setV({ ...v, preferred_language: e.target.value })} /></Field>
          </div>
          <Field label="Payout destination (optional)" htmlFor="o-dest" help="Mobile money wallet reference. Payouts need one on file.">
            <input id="o-dest" className="input" autoComplete="off" value={v.destination} onChange={(e) => setV({ ...v, destination: e.target.value })} />
          </Field>
          <Field label="Link to an account (optional)" htmlFor="o-user" help="Account ID of a person who already has the beneficiary role, so they can sign in and see their funds.">
            <input id="o-user" className="input mono" autoComplete="off" spellCheck={false} value={v.user_id} onChange={(e) => setV({ ...v, user_id: e.target.value })} />
          </Field>
          {error != null && <ErrorNotice error={error} />}
          {created && (
            <Notice tone="pending" title="Profile created, waiting for verification" testId="onboard-result">
              <p>Share this reference with the campaign creator:</p>
              <CopyField value={created.id} label="Beneficiary reference" />
            </Notice>
          )}
          <Button type="submit" busy={busy} busyLabel="Creating profile">Create profile</Button>
        </form>
        <aside className="card stack">
          <h3>Recent profiles</h3>
          {recent.loading && !recent.data ? <Loading /> : recent.error ? <ErrorNotice error={recent.error} /> : (
            <div className="stack">
              {(recent.data ?? []).slice(0, 8).map((b) => (
                <div key={b.id} className="stack" style={{ borderTop: "1px solid var(--line)", paddingTop: "0.75rem" }}>
                  <div className="spread"><strong>{b.display_name}</strong><StatusPill presentation={presentVerification(b.verification_status)} /></div>
                  <CopyField value={b.id} label={`Reference for ${b.display_name}`} />
                </div>
              ))}
              {recent.data?.length === 0 && <p className="muted">No profiles yet.</p>}
            </div>
          )}
        </aside>
      </div>
    </div>
  );
}
