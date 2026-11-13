import { useState, type ButtonHTMLAttributes, type ReactNode } from "react";
import type { CampaignFunds, StatusPresentation, Tone } from "../api/client.ts";
import { describeError } from "../lib/errors.ts";
import { formatMoney, percentOf } from "../lib/money.ts";
import { AlertIcon, CheckIcon, ClockIcon, InfoIcon, MinusIcon } from "./icons.tsx";

const TONE_ICON: Record<Tone, typeof CheckIcon> = { success: CheckIcon, pending: ClockIcon, failure: AlertIcon, neutral: MinusIcon };

/** Status is always icon + words + colour, never colour alone. Only "success" shows a check mark. */
export function StatusPill({ presentation, testId }: { presentation: StatusPresentation; testId?: string }) {
  const Icon = TONE_ICON[presentation.tone];
  return (
    <span className="pill" data-tone={presentation.tone} data-testid={testId}>
      <Icon />
      {presentation.label}
    </span>
  );
}

export function Notice({ tone = "neutral", title, children, testId }: { tone?: Tone; title?: ReactNode; children?: ReactNode; testId?: string }) {
  const Icon = tone === "neutral" ? InfoIcon : TONE_ICON[tone];
  return (
    <div className="notice" data-tone={tone} role={tone === "failure" ? "alert" : "status"} data-testid={testId}>
      <Icon />
      <div>
        {title && <strong>{title}</strong>}
        {children}
      </div>
    </div>
  );
}

export function ErrorNotice({ error, onRetry, testId = "error" }: { error: unknown; onRetry?: () => void; testId?: string }) {
  const view = describeError(error);
  return (
    <Notice tone="failure" title={view.title} testId={testId}>
      <p>
        {view.message}
        {view.retryAfter ? ` Try again in ${view.retryAfter} seconds.` : ""}
      </p>
      {view.requestId && <p className="small muted">Support reference: <span className="mono">{view.requestId}</span></p>}
      {onRetry && <button type="button" className="btn btn--ghost btn--small" onClick={onRetry}>Try again</button>}
    </Notice>
  );
}

export function Spinner() {
  return <span className="spinner" aria-hidden="true" />;
}

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> { variant?: "primary" | "secondary" | "ghost" | "danger" | "gold"; busy?: boolean; busyLabel?: string; small?: boolean; block?: boolean }

/** While busy the button is disabled and says what is happening, so a request is never mistaken for a result. */
export function Button({ variant = "primary", busy, busyLabel, small, block, children, className, disabled, type, ...rest }: ButtonProps) {
  const cls = ["btn", `btn--${variant}`, small && "btn--small", block && "btn--block", className].filter(Boolean).join(" ");
  return (
    <button type={type ?? "button"} className={cls} disabled={disabled || busy} aria-busy={busy || undefined} {...rest}>
      {busy && <Spinner />}
      {busy && busyLabel ? busyLabel : children}
    </button>
  );
}

export function Field({ label, htmlFor, help, error, children }: { label: string; htmlFor: string; help?: ReactNode; error?: string | null; children: ReactNode }) {
  return (
    <div className="field">
      <label htmlFor={htmlFor}>{label}</label>
      {children}
      {help && <span className="help" id={`${htmlFor}-help`}>{help}</span>}
      {error && <span className="error-text" id={`${htmlFor}-error`}>{error}</span>}
    </div>
  );
}

export function PageHead({ eyebrow, title, children, actions }: { eyebrow?: string; title: string; children?: ReactNode; actions?: ReactNode }) {
  return (
    <header className="page-head">
      <div className="spread">
        <div>
          {eyebrow && <div className="eyebrow eyebrow--dark">{eyebrow}</div>}
          <h1>{title}</h1>
        </div>
        {actions && <div className="row">{actions}</div>}
      </div>
      {children}
    </header>
  );
}

export function Empty({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="empty">
      <h3>{title}</h3>
      {children}
    </div>
  );
}

export function Loading({ label = "Loading" }: { label?: string }) {
  return (
    <div className="row muted" role="status" aria-live="polite">
      <Spinner /> {label}…
    </div>
  );
}

export function SimTag({ children = "Simulated" }: { children?: ReactNode }) {
  return <span className="sim-tag">{children}</span>;
}

export function Money({ amount, currency }: { amount: string; currency: string }) {
  return <span className="num">{formatMoney(amount, currency)}</span>;
}

/** Ledger-backed progress. "Raised" counts verified, completed payments only. */
export function FundsMeter({ funds, large }: { funds: CampaignFunds; large?: boolean }) {
  const pct = percentOf(funds.balance.raised, funds.goal.amount);
  return (
    <div className="stack" data-testid="funds-meter">
      <div className="money-line">
        <span><strong data-testid="raised">{formatMoney(funds.balance.raised, funds.balance.currency)}</strong> raised</span>
        <span>of {formatMoney(funds.goal.amount, funds.goal.currency)}</span>
      </div>
      <div className={`progress${large ? " progress--large" : ""}`} role="progressbar" aria-valuenow={pct} aria-valuemin={0} aria-valuemax={100} aria-label="Share of goal raised">
        <div className="progress__bar" style={{ width: `${pct}%` }} />
      </div>
    </div>
  );
}

export function CopyField({ value, label }: { value: string; label: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <div className="copy-field">
      <code aria-label={label}>{value}</code>
      <button
        type="button"
        className="btn btn--ghost btn--small"
        onClick={() => {
          navigator.clipboard?.writeText(value).then(() => setCopied(true), () => setCopied(false));
        }}
      >
        {copied ? "Copied" : "Copy"}
      </button>
    </div>
  );
}
