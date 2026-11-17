import { useState, type FormEvent } from "react";
import type { AccountSummary, Role } from "../api/client.ts";
import { Button, CopyField, Empty, ErrorNotice, Notice, PageHead } from "../components/ui.tsx";
import { useSession } from "../session/SessionContext.tsx";

const ROLES: Role[] = ["donor", "creator", "beneficiary", "agent", "reviewer", "admin"];

export function AdminPeople() {
  const { client, user } = useSession();
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<AccountSummary[] | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);

  async function search(e: FormEvent) {
    e.preventDefault();
    const q = query.trim();
    if (!q) return;
    setBusy(true); setError(null);
    try {
      setResults(await client.findAccounts(q.includes("@") ? { email: q } : { phone_number: q }));
    } catch (err) { setError(err); } finally { setBusy(false); }
  }

  return (
    <div className="container" style={{ maxWidth: 860 }}>
      <PageHead eyebrow="Administration" title="People and roles">
        <p>Public sign-up always creates a donor. Assign creator, beneficiary, agent, reviewer or admin roles here. Every change is audited, and you cannot change your own role.</p>
      </PageHead>
      <form className="search-bar" onSubmit={search} role="search" style={{ gridTemplateColumns: "minmax(0,1fr) auto" }}>
        <label className="visually-hidden" htmlFor="people-q">Email or phone number</label>
        <input id="people-q" className="input" placeholder="Exact email or phone number" value={query} onChange={(e) => setQuery(e.target.value)} />
        <Button type="submit" busy={busy} busyLabel="Searching">Find account</Button>
      </form>
      <div className="section--tight stack">
        {error != null && <ErrorNotice error={error} />}
        {results && (results.length ? (
          <div className="rows" data-testid="people-results">{results.map((a) => <AccountRow key={a.id} account={a} self={a.id === user?.id} />)}</div>
        ) : <Empty title="No account found"><p>Search uses the exact email or phone number.</p></Empty>)}
      </div>
    </div>
  );
}

function AccountRow({ account, self }: { account: AccountSummary; self: boolean }) {
  const { client } = useSession();
  const [current, setCurrent] = useState(account);
  const [role, setRole] = useState<Role>(account.role);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [saved, setSaved] = useState(false);

  async function save() {
    setBusy(true); setError(null); setSaved(false);
    try {
      const updated = await client.assignRole(current.id, role);
      setCurrent(updated); setRole(updated.role); setSaved(true);
    } catch (err) { setError(err); } finally { setBusy(false); }
  }

  return (
    <div className="row-item" data-testid="account-row">
      <div className="row-item__head">
        <span className="row-item__title">{current.email ?? current.phone_number}</span>
        <span className="role-tag" style={{ background: "var(--sand)" }} data-testid="account-role">{current.role}</span>
      </div>
      <div className="row-item__meta"><span>Status {current.status}</span>{self && <span>This is you</span>}</div>
      <CopyField value={current.id} label="Account ID" />
      <div className="row">
        <label htmlFor={`role-${current.id}`} className="small">Role</label>
        <select id={`role-${current.id}`} className="select" style={{ maxWidth: 220 }} value={role} disabled={self} onChange={(e) => setRole(e.target.value as Role)}>
          {ROLES.map((r) => <option key={r} value={r}>{r}</option>)}
        </select>
        <Button small onClick={save} busy={busy} busyLabel="Saving" disabled={self || role === current.role}>Change role</Button>
      </div>
      {saved && <Notice tone="success" testId="role-saved">Role changed to {current.role}. It applies from the person's next sign-in.</Notice>}
      {error != null && <ErrorNotice error={error} />}
    </div>
  );
}
