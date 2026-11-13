import { useState } from "react";
import { useSearchParams } from "react-router-dom";
import type { BeneficiaryProfile, Payout, VerificationStatus } from "../api/client.ts";
import { ApiError } from "../api/client.ts";
import { Decision } from "../components/Decision.tsx";
import { PayoutRow } from "../components/PayoutList.tsx";
import { Button, CopyField, Empty, ErrorNotice, Loading, Money, Notice, PageHead, StatusPill } from "../components/ui.tsx";
import { categoryLabel, presentVerification } from "../lib/status.ts";
import { formatTime } from "../lib/time.ts";
import { useCampaignTitles } from "../lib/useCampaignTitles.ts";
import { useResource } from "../lib/useResource.ts";
import { useSession } from "../session/SessionContext.tsx";

type Tab = "campaigns" | "beneficiaries" | "payouts";
const TABS: { id: Tab; label: string }[] = [
  { id: "campaigns", label: "Campaigns" },
  { id: "beneficiaries", label: "Beneficiaries" },
  { id: "payouts", label: "Payouts" },
];

export function ReviewDesk() {
  const [params, setParams] = useSearchParams();
  const tab = (TABS.some((t) => t.id === params.get("tab")) ? params.get("tab") : "campaigns") as Tab;
  return (
    <div className="container">
      <PageHead eyebrow="Review desk" title="Decisions waiting for you">
        <p>Every decision is recorded in the audit log. You cannot review your own campaign, verify your own profile or approve a payout you requested.</p>
      </PageHead>
      <div className="tabs" role="tablist" aria-label="Review queues">
        {TABS.map((t) => (
          <button key={t.id} role="tab" id={`tab-${t.id}`} aria-selected={tab === t.id} aria-controls={`panel-${t.id}`} className="tab" onClick={() => setParams({ tab: t.id })}>{t.label}</button>
        ))}
      </div>
      <div role="tabpanel" id={`panel-${tab}`} aria-labelledby={`tab-${tab}`}>
        {tab === "campaigns" && <CampaignQueue />}
        {tab === "beneficiaries" && <BeneficiaryQueue />}
        {tab === "payouts" && <PayoutQueue />}
      </div>
    </div>
  );
}

// ------------------------------------------------------------------ campaigns

function CampaignQueue() {
  const { client } = useSession();
  const queue = useResource(() => client.reviewQueue(1, 50), [client]);
  const [busy, setBusy] = useState<{ id: string; d: "approve" | "reject" } | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [done, setDone] = useState<string | null>(null);

  async function decide(id: string, title: string, d: "approve" | "reject") {
    setBusy({ id, d }); setError(null); setDone(null);
    try {
      const updated = await client.reviewCampaign(id, d);
      setDone(updated.status === "published" ? `“${title}” is now live.` : `“${title}” was sent back to its creator as a draft.`);
    } catch (e) { setError(e); } finally { setBusy(null); queue.reload(); }
  }

  if (queue.loading && !queue.data) return <Loading />;
  if (queue.error) return <ErrorNotice error={queue.error} onRetry={queue.reload} />;
  return (
    <div className="stack">
      {done && <Notice tone="success" testId="review-result">{done}</Notice>}
      {error != null && <ErrorNotice error={error} />}
      <p className="muted small">{queue.data?.page.total ?? 0} waiting, oldest first.</p>
      {queue.data?.items.length ? (
        <div className="rows" data-testid="campaign-queue">
          {queue.data.items.map((c) => (
            <div className="row-item" key={c.id} data-testid="queue-item">
              <div className="row-item__head">
                <span className="row-item__title">{c.title}</span>
                <span className="muted small">Submitted {formatTime(c.submitted_at)}</span>
              </div>
              <div className="row-item__meta"><span>{categoryLabel(c.category)}</span><span>Goal <Money amount={c.goal.amount} currency={c.goal.currency} /></span></div>
              <details><summary className="small">Read the story</summary><p style={{ whiteSpace: "pre-wrap", marginTop: "0.5rem" }}>{c.description}</p></details>
              <BeneficiaryCheck id={c.beneficiary_id} />
              <Decision approveLabel="Approve and publish" rejectLabel="Send back" busy={busy?.id === c.id ? busy.d : null} disabled={busy !== null && busy.id !== c.id}
                onDecide={(d) => decide(c.id, c.title, d)} />
            </div>
          ))}
        </div>
      ) : <Empty title="No campaigns waiting for review" />}
    </div>
  );
}

/** Shows the beneficiary's verification next to the campaign. Publishing is not blocked by the server (AUD-8). */
function BeneficiaryCheck({ id }: { id: string }) {
  const { client } = useSession();
  const b = useResource(() => client.getBeneficiary(id), [client, id]);
  if (b.loading) return <span className="small muted">Checking beneficiary…</span>;
  if (b.error || !b.data) return <span className="small muted">Beneficiary details unavailable.</span>;
  const verified = b.data.verification_status === "verified";
  return (
    <div className="row small" data-testid="beneficiary-check">
      <span>Beneficiary <strong>{b.data.display_name}</strong></span>
      <StatusPill presentation={presentVerification(b.data.verification_status)} />
      {!verified && <span className="muted">Not verified yet. Approving will still publish the campaign.</span>}
    </div>
  );
}

// ------------------------------------------------------------------ beneficiaries

const FILTERS: { value: VerificationStatus | ""; label: string }[] = [
  { value: "unverified", label: "Waiting for verification" },
  { value: "reverification_required", label: "Re-verification needed" },
  { value: "verified", label: "Verified" },
  { value: "rejected", label: "Declined" },
  { value: "", label: "All" },
];

function BeneficiaryQueue() {
  const { client } = useSession();
  const [filter, setFilter] = useState<VerificationStatus | "">("unverified");
  const list = useResource(() => client.listBeneficiaries(filter || undefined), [client, filter]);
  return (
    <div className="stack">
      <div className="row">
        <label htmlFor="ben-filter" className="small">Show</label>
        <select id="ben-filter" className="select" style={{ maxWidth: 280 }} value={filter} onChange={(e) => setFilter(e.target.value as VerificationStatus | "")}>
          {FILTERS.map((f) => <option key={f.label} value={f.value}>{f.label}</option>)}
        </select>
        <Button small variant="ghost" onClick={list.reload}>Refresh list</Button>
      </div>
      {list.loading && !list.data ? <Loading /> : list.error ? <ErrorNotice error={list.error} onRetry={list.reload} /> : list.data?.length ? (
        <div className="rows" data-testid="beneficiary-queue">{list.data.map((b) => <BeneficiaryItem key={b.id} initial={b} />)}</div>
      ) : <Empty title="Nobody in this list" />}
    </div>
  );
}

/** A decided profile stays in place with its new status until the reviewer refreshes the list. */
function BeneficiaryItem({ initial }: { initial: BeneficiaryProfile }) {
  const { client } = useSession();
  const [b, setB] = useState(initial);
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState<"approve" | "reject" | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [info, setInfo] = useState<string | null>(null);
  const decidable = b.verification_status !== "verified" && b.verification_status !== "rejected";

  async function decide(d: "approve" | "reject") {
    setBusy(d); setError(null); setInfo(null);
    try {
      const updated = await client.decideVerification(b.id, d === "approve" ? "verify" : "reject", b.revision, reason.trim() || undefined);
      setB(updated);
      setInfo(updated.verification_status === "verified" ? "Verified." : "Verification declined.");
    } catch (e) {
      setError(e);
      if (e instanceof ApiError && e.code === "PROFILE_CHANGED") setB(await client.getBeneficiary(b.id));
    } finally { setBusy(null); }
  }

  return (
    <div className="row-item" data-testid="beneficiary-item">
      <div className="row-item__head">
        <span className="row-item__title">{b.display_name}</span>
        <StatusPill presentation={presentVerification(b.verification_status)} testId="verification-status" />
      </div>
      <div className="row-item__meta">
        <span>{b.phone_number}</span><span>{b.country_code}</span><span>Language {b.preferred_language}</span>
        <span>{b.has_payout_destination ? "Payout destination on file" : "No payout destination"}</span>
        <span>{b.user_id ? "Linked to an account" : "No linked account"}</span>
      </div>
      <CopyField value={b.id} label="Beneficiary reference" />
      {info && <Notice tone={b.verification_status === "verified" ? "success" : "neutral"}>{info}</Notice>}
      {error != null && <ErrorNotice error={error} />}
      {decidable && (
        <>
          <label className="visually-hidden" htmlFor={`reason-${b.id}`}>Reason (optional)</label>
          <input id={`reason-${b.id}`} className="input" placeholder="Reason (optional, kept in the audit log)" maxLength={200} value={reason} onChange={(e) => setReason(e.target.value)} />
          <Decision approveLabel="Verify" rejectLabel="Decline" busy={busy} onDecide={decide} />
        </>
      )}
    </div>
  );
}

// ------------------------------------------------------------------ payouts

function PayoutQueue() {
  const { client } = useSession();
  const [onlyWaiting, setOnlyWaiting] = useState(true);
  const payouts = useResource(() => client.listPayouts(), [client]);
  const titles = useCampaignTitles(client, (payouts.data ?? []).map((p) => p.campaign_id));
  const shown = (payouts.data ?? []).filter((p) => !onlyWaiting || p.status === "requested");
  return (
    <div className="stack">
      <div className="row">
        <Button small variant={onlyWaiting ? "secondary" : "ghost"} aria-pressed={onlyWaiting} onClick={() => setOnlyWaiting(true)}>Waiting for review</Button>
        <Button small variant={!onlyWaiting ? "secondary" : "ghost"} aria-pressed={!onlyWaiting} onClick={() => setOnlyWaiting(false)}>All payouts</Button>
      </div>
      {payouts.loading && !payouts.data ? <Loading /> : payouts.error ? <ErrorNotice error={payouts.error} onRetry={payouts.reload} /> : shown.length ? (
        <div className="rows" data-testid="payout-queue">{shown.map((p) => <PayoutReview key={p.id} initial={p} title={titles[p.campaign_id]} onDecided={payouts.reload} />)}</div>
      ) : <Empty title={onlyWaiting ? "No payouts waiting for review" : "No payouts yet"} />}
    </div>
  );
}

function PayoutReview({ initial, title, onDecided }: { initial: Payout; title?: string; onDecided: () => void }) {
  const { client } = useSession();
  const [p, setP] = useState(initial);
  const [busy, setBusy] = useState<"approve" | "reject" | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [info, setInfo] = useState<string | null>(null);

  async function decide(d: "approve" | "reject") {
    setBusy(d); setError(null); setInfo(null);
    try {
      const updated = await client.reviewPayout(p.id, d);
      setP(updated);
      setInfo(updated.status === "approved_for_submission"
        ? "Approved for submission. No money has been sent" + (updated.provider === "simulator" ? ": payouts are simulated here." : " yet.")
        : "Rejected. The reserved amount is available to the campaign again.");
    } catch (e) {
      setError(e);
      if (e instanceof ApiError && e.code === "INVALID_PAYOUT_TRANSITION") setP(await client.getPayout(p.id));
    } finally { setBusy(null); }
  }

  return (
    <PayoutRow payout={p} title={title}>
      {info && <Notice tone="pending" testId="payout-decision">{info}</Notice>}
      {error != null && <ErrorNotice error={error} />}
      {p.status === "requested" && <Decision approveLabel="Approve" rejectLabel="Reject" busy={busy} onDecide={decide} />}
      {p.status !== initial.status && <Button small variant="ghost" onClick={onDecided}>Refresh list</Button>}
    </PayoutRow>
  );
}
