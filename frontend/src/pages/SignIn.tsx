import { useState, type FormEvent } from "react";
import { Link, useLocation, useNavigate, useSearchParams } from "react-router-dom";
import { Button, ErrorNotice, Field } from "../components/ui.tsx";
import { roleHome, safeNext } from "../lib/roleHome.ts";
import { useSession } from "../session/SessionContext.tsx";

export function SignIn() {
  const { signIn } = useSession();
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const location = useLocation();
  const [email, setEmail] = useState((location.state as { email?: string } | null)?.email ?? "");
  const [password, setPassword] = useState("");
  const [touched, setTouched] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const emailMissing = !email.trim();
  const passwordMissing = !password;

  async function submit(e: FormEvent) {
    e.preventDefault();
    setTouched(true);
    if (emailMissing || passwordMissing) return;
    setBusy(true); setError(null);
    try {
      const user = await signIn(email.trim(), password);
      navigate(safeNext(params.get("next")) ?? roleHome(user.role), { replace: true });
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="container section" style={{ maxWidth: 480 }}>
      <form className="card form" onSubmit={submit} noValidate aria-labelledby="signin-title">
        <h1 id="signin-title" style={{ fontSize: "1.9rem" }}>Sign in</h1>
        <Field label="Email" htmlFor="email" error={touched && emailMissing ? "Enter your email." : null}>
          <input id="email" className="input" type="email" autoComplete="username" value={email} aria-invalid={touched && emailMissing} onChange={(e) => setEmail(e.target.value)} />
        </Field>
        <Field label="Password" htmlFor="password" error={touched && passwordMissing ? "Enter your password." : null}>
          <input id="password" className="input" type="password" autoComplete="current-password" value={password} aria-invalid={touched && passwordMissing} onChange={(e) => setPassword(e.target.value)} />
        </Field>
        {error != null && <ErrorNotice error={error} />}
        <Button type="submit" block busy={busy} busyLabel="Signing in">Sign in</Button>
        <p className="small muted" style={{ margin: 0 }}>Sessions last 15 minutes. New here? <Link to="/register">Create an account</Link>.</p>
      </form>
    </div>
  );
}
