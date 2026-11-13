import { Link } from "react-router-dom";
import { Loading, PageHead, SimTag } from "../components/ui.tsx";
import { useEnvironment } from "../session/EnvironmentContext.tsx";

const MODE_WORD: Record<string, string> = { live: "Live", sandbox: "Test mode", simulated: "Simulated", fallback: "Fallback", unconfigured: "Not configured" };

export function SystemModes() {
  const { modes, loading, failed } = useEnvironment();
  return (
    <div className="container">
      <PageHead eyebrow="Transparency" title="How money and messages move here">
        <p>FundBridge labels every channel that is not live. This page reads the server's own configuration; nothing here is assumed by the website.</p>
      </PageHead>
      {loading ? <Loading /> : failed ? <p>The server's configuration could not be read.</p> : (
        <div className="rows" data-testid="system-modes">
          {modes.map((m) => (
            <div className="row-item" key={m.key} data-testid={`system-${m.key}`}>
              <div className="row-item__head">
                <span className="row-item__title">{m.channel}</span>
                {m.mode === "live" ? <span className="pill" data-tone="success">Live</span> : <SimTag>{MODE_WORD[m.mode]}</SimTag>}
              </div>
              <div><strong>{m.label}.</strong> {m.detail}</div>
            </div>
          ))}
        </div>
      )}
      <section className="section--tight">
        <h2>What each status means</h2>
        <div className="grid">
          <div className="card card--flat"><h3>Donations</h3><p className="muted">“Waiting for payment confirmation” means PayPal has not yet confirmed the money. Only <strong>Donation confirmed</strong> is counted in a campaign's total.</p></div>
          <div className="card card--flat"><h3>Payouts</h3><p className="muted">“Approved, being prepared” means a reviewer approved the request. It is <strong>not</strong> paid until the status says “Paid to your mobile money account”.</p></div>
          <div className="card card--flat"><h3>Text messages</h3><p className="muted">Simulated messages are stored on the server for testing and never reach a phone.</p></div>
        </div>
        <p style={{ marginTop: "1.5rem" }}><Link to="/campaigns">Browse campaigns</Link></p>
      </section>
    </div>
  );
}
