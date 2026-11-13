import { useEffect, useState } from "react";
import { Link, NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";
import type { Role } from "../api/client.ts";
import { isTestEnvironment } from "../lib/modes.ts";
import { useEnvironment } from "../session/EnvironmentContext.tsx";
import { useSession } from "../session/SessionContext.tsx";
import { BrandMark, MenuIcon } from "./icons.tsx";

const ROLE_LABEL: Record<Role, string> = {
  donor: "Donor", creator: "Creator", beneficiary: "Beneficiary", agent: "Agent", reviewer: "Reviewer", admin: "Admin",
};

const LINKS: { to: string; label: string; roles?: Role[] }[] = [
  { to: "/campaigns", label: "Campaigns" },
  { to: "/creator", label: "My campaigns", roles: ["creator", "admin"] },
  { to: "/beneficiary", label: "My funds", roles: ["beneficiary"] },
  { to: "/review", label: "Review desk", roles: ["reviewer", "admin"] },
  { to: "/agent/onboard", label: "Onboard", roles: ["agent", "admin"] },
  { to: "/admin/people", label: "People", roles: ["admin"] },
  { to: "/account/donations", label: "My donations", roles: ["donor", "creator", "beneficiary", "agent", "reviewer", "admin"] },
];

function Header() {
  const { user, signOut } = useSession();
  const [open, setOpen] = useState(false);
  const location = useLocation();
  const navigate = useNavigate();
  useEffect(() => setOpen(false), [location.pathname]);
  const visible = LINKS.filter((l) => !l.roles || (user && l.roles.includes(user.role)));
  return (
    <header className="site-header">
      <div className="container site-header__inner">
        <Link to="/" className="brand" aria-label="FundBridge home"><BrandMark />FundBridge</Link>
        <button type="button" className="menu-toggle" aria-expanded={open} aria-controls="main-nav" onClick={() => setOpen((o) => !o)}>
          <MenuIcon width={20} height={20} /> <span className="visually-hidden">Menu</span>
        </button>
        <nav id="main-nav" className="nav" data-open={open} aria-label="Main">
          {visible.map((l) => <NavLink key={l.to} to={l.to}>{l.label}</NavLink>)}
          {user ? (
            <span className="nav__account">
              <span className="role-tag" data-testid="role-tag">{ROLE_LABEL[user.role]}</span>
              <span className="nav__who" title={user.email ?? user.phone_number ?? ""}>{user.email ?? user.phone_number}</span>
              {/* No server-side logout exists (tokens expire after 15 minutes); this forgets the token here. */}
              <button type="button" className="linklike" onClick={() => { signOut(); navigate("/"); }}>Sign out</button>
            </span>
          ) : (
            <span className="nav__account">
              <NavLink to="/signin">Sign in</NavLink>
              <NavLink to="/register">Create account</NavLink>
            </span>
          )}
        </nav>
      </div>
    </header>
  );
}

function ModeStrip() {
  const { modes, loading, failed } = useEnvironment();
  if (loading) return <div className="mode-strip" aria-hidden="true"><div className="container mode-strip__inner">&nbsp;</div></div>;
  return (
    <section className="mode-strip" aria-label="Environment status" data-testid="mode-strip">
      <div className="container mode-strip__inner">
        <span className="mode-strip__title">{failed ? "Status unavailable" : isTestEnvironment(modes) ? "Test environment" : "Live"}</span>
        {failed ? (
          <span className="chip" data-mode="unconfigured"><span className="chip__dot" />Could not read the server's payment and payout modes</span>
        ) : (
          modes.filter((m) => m.key === "paypal" || m.key === "payouts" || m.key === "sms").map((m) => (
            <span key={m.key} className="chip" data-mode={m.mode} data-testid={`mode-${m.key}`} title={m.detail}>
              <span className="chip__dot" />{m.label}
            </span>
          ))
        )}
        <Link to="/system">What this means</Link>
      </div>
    </section>
  );
}

function Footer() {
  return (
    <footer className="site-footer">
      <div className="container site-footer__inner">
        <p>FundBridge shows a donation as confirmed only after PayPal's capture is verified by the server, and a payout as paid only when the provider confirms it.</p>
        <p><Link to="/system">Environment and integrations</Link></p>
      </div>
    </footer>
  );
}

export function Layout() {
  const { notice, clearNotice } = useSession();
  return (
    <>
      <a href="#main" className="skip-link">Skip to content</a>
      <Header />
      <ModeStrip />
      {notice && (
        <div className="container" style={{ paddingTop: "1rem" }}>
          <div className="notice" data-tone="pending" role="status" data-testid="session-notice">
            <div className="spread" style={{ width: "100%" }}>
              <span>{notice}</span>
              <button type="button" className="btn btn--ghost btn--small" onClick={clearNotice}>Dismiss</button>
            </div>
          </div>
        </div>
      )}
      <main id="main">
        <Outlet />
      </main>
      <Footer />
    </>
  );
}
